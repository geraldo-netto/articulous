"""REVIEW28-27: compact fingerprints preserve transform and translation identity."""
from hashlib import sha256
import json

import pytest

from articulous import pipeline
from articulous.ownership import load_ownership
from articulous.publication import build_site
from test_seo_translations import _translation_pair


def _active_record(root):
    return json.loads((root / '.build-cache.json').read_bytes())['__output_roots__'][str(root / 'output')]


@pytest.mark.parametrize('publish', [pipeline.run_build, build_site])
def test_review28_27_cache_omits_routes_and_full_parameters(site_root, seo_config, publish):
    cli, config = seo_config
    _translation_pair(site_root)
    publish(cli, config, site_root)
    cache = _active_record(site_root)
    assert '__routes__' not in cache and '__outputs__' not in cache
    owners = load_ownership(site_root / 'output')
    for key, pair in owners.translations.items():
        assert cache[key][-1] == pair
    assert len(owners.translations) == 2
    assert 'articulous-jsonld' not in json.dumps(cache)
    (site_root / '.build-cache.json').unlink()
    cli.only_sections = ['rss']
    pipeline.run_build(cli, config, site_root)
    assert load_ownership(site_root / 'output').translations == owners.translations


def test_review28_27_parameter_digest_tracks_values_and_ignores_order(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    key = 'article:en:first-post'
    params = {'second': 'é', 'first': 'one'}
    monkeypatch.setattr(pipeline, '_article_parameters', lambda *_: params)
    pipeline.run_build(cli, config, site_root)
    expected = sha256(json.dumps(params, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert _active_record(site_root)[key][4] == expected
    page = site_root / 'output/en/articles/first-post/index.html'
    original = page.stat().st_ino
    params = dict(reversed(params.items()))
    pipeline.run_build(cli, config, site_root)
    assert page.stat().st_ino == original
    params['first'] = 'two'
    pipeline.run_build(cli, config, site_root)
    assert page.stat().st_ino != original
    assert _active_record(site_root)[key][4] != expected


@pytest.mark.parametrize('redundant', ['__routes__', '__outputs__'])
def test_review28_27_obsolete_fingerprints_are_disposable(site_root, seo_config, redundant):
    cli, config = seo_config
    pipeline.run_build(cli, config, site_root)
    cache_file = site_root / '.build-cache.json'
    envelope = json.loads(cache_file.read_bytes())
    stored = envelope['__output_roots__'][str(site_root / 'output')]
    stored[redundant] = {'retained': 'obsolete'}
    cache_file.write_text(json.dumps(envelope))
    before = load_ownership(site_root / 'output')
    cli.only_sections = ['rss']
    pipeline.run_build(cli, config, site_root)
    cache = _active_record(site_root)
    assert redundant not in cache
    assert 'article:en:first-post' not in cache
    assert load_ownership(site_root / 'output').routes == before.routes
