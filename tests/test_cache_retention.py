"""DG-01: configurable inactivity expiry for shared build caches."""
import json
import random

import pytest

from articulous.builds import check_build
from articulous.configuration_contracts import BuildRequest, ConfigurationError
from articulous.config import load_or_create_config, normalize_configuration
from articulous.ownership import ownership_path
from articulous.pipeline import run_build
from articulous.publication import build_site

DAY = 86_400


def _cache(site_root):
    return site_root / '.build-cache.json'


def _roots(site_root):
    return json.loads(_cache(site_root).read_text())['__output_roots__']


def _output_config(site_root, name):
    config = load_or_create_config(site_root / 'config.json')
    config['paths']['output_dir'] = name
    return config


@pytest.mark.parametrize('age, expires', [(3 * DAY - 1, False), (3 * DAY, True)])
def test_dg01_default_retention_boundary(site_root, cache_clock, age, expires):
    request = BuildRequest()
    output = site_root / 'output'
    run_build(request, _output_config(site_root, 'output'), site_root)
    old_ownership = ownership_path(output).read_bytes()
    old_output = (output / 'rss.xml').read_bytes()
    cache_clock[0] += age
    run_build(request, _output_config(site_root, 'second'), site_root)
    assert (str(output) not in _roots(site_root)) == expires
    assert ownership_path(output).read_bytes() == old_ownership
    assert (output / 'rss.xml').read_bytes() == old_output


def test_dg01_noop_build_refreshes_activity_and_prunes_inactive_roots(site_root, cache_clock):
    request = BuildRequest()
    active = _output_config(site_root, 'output')
    run_build(request, active, site_root)
    cache_clock[0] += DAY
    run_build(request, _output_config(site_root, 'second'), site_root)
    cache_clock[0] += DAY
    output = site_root / 'output'
    page = output / 'rss.xml'
    before = page.stat().st_mtime_ns
    run_build(request, active, site_root)
    assert page.stat().st_mtime_ns == before
    assert _roots(site_root)[str(output)]['__last_used__'] == cache_clock[0]
    cache_clock[0] += 2 * DAY
    run_build(request, _output_config(site_root, 'third'), site_root)
    assert set(_roots(site_root)) == {str(output), str(site_root / 'third')}


@pytest.mark.parametrize('days,age,expires', [(0, 0, True), (1, DAY, True), (5, 4 * DAY, False), (10**100, 4 * DAY, False)])
def test_dg01_configured_retention_applies_to_native_publication(site_root, cache_clock, days, age, expires):
    run_build(BuildRequest(), _output_config(site_root, 'output'), site_root)
    cache_clock[0] += age
    config = _output_config(site_root, 'second')
    config['build']['cache_retention_days'] = days
    build_site(BuildRequest(), config, site_root)
    assert (str(site_root / 'output') not in _roots(site_root)) == expires
    assert str(site_root / 'second') in _roots(site_root)


def test_dg01_dry_run_and_validation_preserve_cache(site_root, cache_clock):
    config = _output_config(site_root, 'output')
    run_build(BuildRequest(), config, site_root)
    before = _cache(site_root).read_bytes()
    cache_clock[0] += 4 * DAY
    other = _output_config(site_root, 'second')
    run_build(BuildRequest(dry_run=True), other, site_root)
    check_build(BuildRequest(), other, site_root)
    assert _cache(site_root).read_bytes() == before


@pytest.mark.parametrize('seed', range(8))
def test_dg01_seeded_config_boundaries(site_root, seed):
    rng = random.Random(seed)
    for value in (None, False, True, [1], {}, -1, -rng.getrandbits(256) - 1, rng.random(), str(seed)):
        with pytest.raises(ConfigurationError, match='build.cache_retention_days'):
            normalize_configuration({'build': {'cache_retention_days': value}}, BuildRequest(), site_root)
    for value in (0, 1, 3, rng.getrandbits(256)):
        config = normalize_configuration({'build': {'cache_retention_days': value}}, BuildRequest(), site_root)
        assert config['build']['cache_retention_days'] == value


def test_dg01_legacy_root_without_activity_preserves_ownership_fallback(site_root, cache_clock):
    first = _output_config(site_root, 'output')
    run_build(BuildRequest(), first, site_root)
    output = site_root / 'output'
    roots = _roots(site_root)
    roots[str(output)].pop('__last_used__')
    _cache(site_root).write_text(json.dumps({'__output_roots__': roots}))
    ownership_path(output).unlink()
    cache_clock[0] += 4 * DAY
    run_build(BuildRequest(), _output_config(site_root, 'second'), site_root)
    assert str(output) in _roots(site_root)
    run_build(BuildRequest(), first, site_root)
    assert ownership_path(output).is_file()


def test_dg01_publication_rollback_restores_marker_and_expired_root(site_root, cache_clock, monkeypatch):
    from articulous.backends.posix import PosixPublicationBackend
    request = BuildRequest()
    first = _output_config(site_root, 'output')
    second = _output_config(site_root, 'second')
    run_build(request, first, site_root)
    before = _cache(site_root).read_bytes()
    cache_clock[0] += 4 * DAY
    backend = PosixPublicationBackend()
    original = backend._write_state

    def fail(publication):
        original(publication)
        assert set(_roots(site_root)) == {str(site_root / 'second')}
        raise OSError('write interrupted')
    monkeypatch.setattr(backend, '_write_state', fail)
    with pytest.raises(OSError, match='write interrupted'):
        build_site(request, second, site_root, backend=backend)
    assert _cache(site_root).read_bytes() == before
    assert not (site_root / 'second').exists()


def test_dg01_clock_rollback_does_not_shorten_inactivity_window(site_root, cache_clock):
    config = _output_config(site_root, 'output')
    run_build(BuildRequest(), config, site_root)
    cache_clock[0] -= 2 * DAY
    run_build(BuildRequest(), config, site_root)
    cache_clock[0] += 3 * DAY
    run_build(BuildRequest(), _output_config(site_root, 'second'), site_root)
    assert str(site_root / 'output') in _roots(site_root)


def test_dg01_publication_projects_cache_after_recovery(site_root, monkeypatch):
    from articulous.backends.posix import PosixPublicationBackend
    from articulous.builds import prepare_build, render_prepared, validate_generated
    from articulous.publication import publish_validated

    request = BuildRequest()
    cache_path = _cache(site_root)
    cache_path.write_text(json.dumps({'__output_roots__': {'displaced': {}}}))
    backend = PosixPublicationBackend()

    def recover(_output, cache):
        cache.write_text(json.dumps({'__output_roots__': {'restored': {}}}))
    monkeypatch.setattr(backend, 'recover', recover)
    with prepare_build(request, _output_config(site_root, 'output'), site_root) as prepared:
        publish_validated(validate_generated(render_prepared(prepared)), backend=backend)
    assert set(_roots(site_root)) == {'restored', str(site_root / 'output')}
