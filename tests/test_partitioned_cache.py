"""PERF-31 and PERF-37: root-local fingerprints, migration and isolation."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
from threading import Barrier

import pytest

from articulous import cache_store, pipeline, publication_adapter
from articulous.backends.posix import PosixPublicationBackend
from articulous.builds import check_build
from articulous.config import normalize_configuration
from articulous.configuration_contracts import BuildRequest, ConfigurationError
from articulous.filesystem import cache_lock_path, lock_file
from articulous.ownership import ownership_path
from articulous.publication import build_site, lock_site, recover_publication
from articulous.publication_paths import transaction_path

DAY = 86_400
REQUEST = BuildRequest()


def _config(name='output', enable=True, days=3):
    return {'paths': {'output_dir': name},
            'build': {'partition_cache': enable, 'cache_retention_days': days, 'parallelism': 2}}


def _base(root):
    return root / '.build-cache.json'


def _selected(root, name):
    return cache_store.select_cache(_base(root), root / name)


def _record(root, name):
    return json.loads(_selected(root, name).path.read_text())['__output_roots__'][str(root / name)]


@pytest.mark.parametrize('seed', range(4))
def test_perf31_partition_setting_rejects_non_boolean_values(site_root, seed):
    rng = random.Random(seed)
    for invalid in (None, 0, 1, rng.getrandbits(256), rng.random(), [], {}, 'true'):
        with pytest.raises(ConfigurationError, match='build.partition_cache'):
            normalize_configuration({'build': {'partition_cache': invalid}}, REQUEST, site_root)
    for value in (False, True):
        config = normalize_configuration({'build': {'partition_cache': value}}, REQUEST, site_root)
        assert config['build']['partition_cache'] is value


def test_perf31_migrates_shared_roots_and_admits_only_active_records(site_root, cache_clock, monkeypatch):
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    pipeline.run_build(REQUEST, _config('second', enable=False), site_root)
    second = _record(site_root, 'second')
    cache_clock[0] += DAY
    pipeline.run_build(REQUEST, _config(), site_root)
    assert _selected(site_root, 'output').partitioned
    assert _record(site_root, 'second') == second
    old = _base(site_root).read_bytes()
    reads = []
    load = pipeline.load_cache

    def observe(path):
        reads.append(path)
        return load(path)

    monkeypatch.setattr(pipeline, 'load_cache', observe)
    cache_clock[0] += 1
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    assert reads == [_selected(site_root, 'output').path]
    assert _base(site_root).read_bytes() == old
    assert _record(site_root, 'output')['__last_used__'] == cache_clock[0]


def test_perf31_custom_backend_keeps_cache_text_and_active_path_contract(site_root, monkeypatch):
    class Recorder(PosixPublicationBackend):
        def publish(self, publication):
            assert isinstance(publication.cache_text, str)
            assert publication.cache_path == _selected(site_root, 'output').path
            roots = json.loads(publication.cache_text)['__output_roots__']
            assert set(roots) == {str(publication.destination)}
            super().publish(publication)

    pipeline.run_build(REQUEST, _config('second'), site_root)
    cache = _selected(site_root, 'second').path
    before = cache.read_bytes()
    loads = []
    load = publication_adapter.load_cache

    def observe(path):
        loads.append(path)
        return load(path)

    monkeypatch.setattr(publication_adapter, 'load_cache', observe)
    build_site(REQUEST, _config(), site_root, backend=Recorder())
    assert loads == [_selected(site_root, 'output').path]
    assert cache.read_bytes() == before


def test_perf31_dry_run_and_check_leave_layout_and_fingerprints_unchanged(site_root, cache_clock):
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    prior = _base(site_root).read_bytes()
    cache_clock[0] += 4 * DAY
    pipeline.run_build(BuildRequest(dry_run=True), _config('second'), site_root)
    check_build(REQUEST, _config('second'), site_root)
    assert not _selected(site_root, 'output').partitioned
    assert _base(site_root).read_bytes() == prior
    pipeline.run_build(REQUEST, _config(), site_root)
    active = _selected(site_root, 'output').path
    before = active.read_bytes()
    cache_clock[0] += 4 * DAY
    pipeline.run_build(BuildRequest(dry_run=True), _config('second'), site_root)
    check_build(REQUEST, _config('second'), site_root)
    assert active.read_bytes() == before


@pytest.mark.parametrize('age,days,expired', [(3 * DAY - 1, 3, False), (3 * DAY, 3, True), (0, 0, True)])
def test_perf31_partition_retention_preserves_ownership(site_root, cache_clock, age, days, expired):
    pipeline.run_build(REQUEST, _config(), site_root)
    output = site_root / 'output'
    owner = ownership_path(output).read_bytes()
    page = (output / 'rss.xml').read_bytes()
    cache_clock[0] += age
    build_site(REQUEST, _config('second', days=days), site_root)
    assert _selected(site_root, 'output').path.exists() is not expired
    assert ownership_path(output).read_bytes() == owner
    assert (output / 'rss.xml').read_bytes() == page
    if expired:
        pipeline.run_build(BuildRequest(only_sections=('rss',)), _config(), site_root)
        assert _selected(site_root, 'output').path.is_file()


def test_perf31_undated_records_remain_available_after_migration(site_root, cache_clock):
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    raw = json.loads(_base(site_root).read_text())
    raw['__output_roots__'][str(site_root / 'output')].pop('__last_used__')
    ownership_path(site_root / 'output').unlink()
    _base(site_root).write_text(json.dumps(raw))
    cache_clock[0] += 4 * DAY
    pipeline.run_build(REQUEST, _config('second', days=0), site_root)
    assert '__last_used__' not in _record(site_root, 'output')
    pipeline.run_build(REQUEST, _config('third', days=0), site_root)
    assert _selected(site_root, 'output').path.is_file()
    pipeline.run_build(REQUEST, _config(), site_root)
    assert ownership_path(site_root / 'output').is_file()


def test_rel43_losing_partitions_cannot_reuse_retired_shared_fingerprints(site_root):
    pipeline.run_build(REQUEST, _config(), site_root)
    page = site_root / 'output/en/articles/first-post/index.html'
    original_output = page.read_bytes()
    source = site_root / 'content/en/first-post.xml'
    original_source = source.read_text()
    source.write_text(original_source.replace('Inaugural article.', 'Changed after partitioning.'))
    pipeline.run_build(REQUEST, _config(), site_root)
    assert page.read_bytes() != original_output
    source.write_text(original_source)
    shutil.rmtree(cache_store.cache_namespace(_base(site_root)))
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    assert page.read_bytes() == original_output


def test_perf37_disjoint_builds_overlap_and_same_root_is_excluded(site_root):
    pipeline.run_build(REQUEST, _config(), site_root)
    concurrent = Barrier(2)

    def validate(_stage):
        concurrent.wait(timeout=20)

    with ThreadPoolExecutor(max_workers=2) as pool:
        submissions = [pool.submit(build_site, REQUEST, _config(name), site_root, validators=(validate,))
                       for name in ('output', 'second')]
        assert all(task.result().routes > 0 for task in submissions)
    with lock_site(REQUEST, _config(), site_root):
        with pytest.raises(FileExistsError):
            build_site(REQUEST, _config(), site_root)
        pipeline.run_build(REQUEST, _config('third', days=0), site_root)
        assert _selected(site_root, 'output').path.is_file()
    pipeline.run_build(REQUEST, _config('third', days=0), site_root)
    assert not _selected(site_root, 'output').path.exists()


def _interrupt_publication(site_root, output, phase='installed'):
    script = '''
import os, sys
from pathlib import Path
from articulous.backends.posix import PosixPublicationBackend
from articulous.configuration_contracts import BuildRequest
from articulous.publication import build_site
class Interrupted(PosixPublicationBackend):
    def _set_phase(self, path, data, phase):
        super()._set_phase(path, data, phase)
        if phase == sys.argv[3]:
            os._exit(91)
build_site(BuildRequest(), {"paths":{"output_dir":sys.argv[2]}}, Path(sys.argv[1]),
           backend=Interrupted())
'''
    result = subprocess.run([sys.executable, '-c', script, str(site_root), output, phase],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True)
    assert result.returncode == 91, result.stderr.decode()


def test_perf37_publication_recovery_uses_active_root_after_interruption(site_root, cache_clock):
    pipeline.run_build(REQUEST, _config(), site_root)
    build_site(REQUEST, _config('second'), site_root)
    second = _selected(site_root, 'second').path
    before = second.read_bytes()
    _interrupt_publication(site_root, 'second')
    cache_clock[0] += 4 * DAY
    pipeline.run_build(REQUEST, _config(), site_root)
    first = _selected(site_root, 'output').path
    newer = first.read_bytes()
    assert second.exists()
    recover_publication(site_root / 'second', _base(site_root))
    assert second.read_bytes() == before
    assert first.read_bytes() == newer
    assert not transaction_path(site_root / 'second').exists()


def test_perf31_migration_waits_for_pending_legacy_journals(site_root, caplog):
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    _interrupt_publication(site_root, 'nested/second', 'prepared')
    pipeline.run_build(REQUEST, _config(), site_root)
    assert not _selected(site_root, 'output').partitioned
    assert 'partitioning pending recovery' in caplog.text
    recover_publication(site_root / 'nested/second', _base(site_root))
    pipeline.run_build(REQUEST, _config(), site_root)
    assert _selected(site_root, 'output').partitioned


def test_perf37_lock_selection_retries_if_layout_changes_before_lock(site_root):
    base = _base(site_root)
    root = site_root / 'output'
    paths = []

    @contextmanager
    def lock(path):
        paths.append(path)
        with lock_file(cache_lock_path(path)):
            if path == base:
                cache_store.finish_cache_update(_selected(site_root, 'output'), root, 3, True)
            yield

    with cache_store.lock_selected_cache(base, root, lock) as selected:
        assert selected.partitioned
    assert paths == [base, selected.path]


def test_perf31_refuses_aliased_cache_namespace_and_partitions(site_root):
    namespace = cache_store.cache_namespace(_base(site_root))
    overlap = _config(namespace.name + '/html')
    with pytest.raises(ValueError, match='overlaps fingerprint cache'):
        pipeline.run_build(REQUEST, overlap, site_root)
    namespace.mkdir()
    with pytest.raises(ValueError, match='Unrecognized fingerprint cache'):
        pipeline.run_build(REQUEST, _config(), site_root)
    namespace.rmdir()
    pipeline.run_build(REQUEST, _config(), site_root)
    cache = _selected(site_root, 'output').path
    os.link(cache, site_root / 'unexpected')
    with pytest.raises(ValueError, match='multiple hardlinks'):
        pipeline.run_build(REQUEST, _config(), site_root)


@pytest.mark.parametrize('raw,blocks', [('invalid', True), ('[]', True), ('{"cache":"/other"}', False)])
def test_perf31_activation_distinguishes_pending_journal_identity(tmp_path, raw, blocks):
    base = _base(tmp_path)
    pending = transaction_path(tmp_path / 'other')
    pending.mkdir()
    (pending / 'journal.json').write_text(raw)
    assert cache_store._has_pending_journal(base) is blocks


def test_perf31_activation_preserves_state_if_directory_cannot_be_scanned(tmp_path, monkeypatch, caplog):
    base = _base(tmp_path)
    base.write_text('{"fingerprint": [1]}')
    selected = cache_store.select_cache(base, tmp_path / 'output')

    def unreadable(*args, onerror):
        onerror(PermissionError('unreadable directory'))

    monkeypatch.setattr(cache_store.os, 'walk', unreadable)
    cache_store.finish_cache_update(selected, tmp_path / 'output', 3, True)
    assert base.read_text() == '{"fingerprint": [1]}'
    assert 'cache maintenance failed: unreadable directory' in caplog.text


@pytest.mark.parametrize('value', [None, '{"fingerprint":[1]}'])
def test_perf31_legacy_flat_values_bind_to_migrating_output(tmp_path, value):
    base = _base(tmp_path)
    if value is not None:
        base.write_text(value)
    destination = tmp_path / 'output'
    assert cache_store._migration_records(base, destination) == (
        {} if value is None else {str(destination): json.loads(value)}
    )


def test_perf31_malformed_legacy_root_paths_are_ignored(tmp_path):
    base = _base(tmp_path)
    invalid_paths = ('relative', str(tmp_path.parent), str(tmp_path / 'bad\0path'))
    value = {'__output_roots__': dict.fromkeys(invalid_paths, {'fingerprint': [1]})}
    base.write_text(json.dumps(value))
    assert cache_store._migration_records(base, tmp_path / 'output') == {}


@pytest.mark.parametrize('fault', ['hardlink', 'wrong-root', 'not-string', 'missing'])
def test_perf31_does_not_expire_unverified_cache_headers(tmp_path, fault):
    namespace = cache_store.cache_namespace(_base(tmp_path))
    namespace.mkdir()
    path = cache_store._root_path(namespace, str(tmp_path / 'output'))
    if fault != 'missing':
        other = 42 if fault == 'not-string' else str(tmp_path / 'other')
        path.write_text(json.dumps({'__output_roots__': {other: {'__last_used__': 0}}}, indent=2))
    if fault == 'hardlink':
        os.link(path, namespace / 'unknown')
    cache_store._prune_root(path, None)
    assert path.exists() is (fault != 'missing')
