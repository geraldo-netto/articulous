"""API-006: route semantics survive disposable fingerprint-cache loss."""
from dataclasses import replace
import json

import pytest

from articulous.composition import RouteCatalog
from articulous.composition_contracts import ExtraArtifact
from articulous.ownership import ownership_path
from articulous.pipeline import run_build
from articulous.publication import build_site
from test_composition import page
from test_prepared_build import snapshot


@pytest.mark.parametrize('publisher', [run_build, build_site])
@pytest.mark.parametrize('loss', ['missing', 'corrupt', 'switch'])
def test_api006_routes_survive_cache_loss(site_root, seo_config, publisher, loss):
    cli, config = seo_config
    source = site_root / 'content/en/first-post.xml'
    source.write_text(source.read_text().replace('</article>', '<indexing>noindex</indexing></article>'))
    extra = page(config)
    extra = replace(extra, route=replace(extra.route, language='fr', sitemap=False))
    options = {'extra_pages': [extra], 'extra_artifacts': [ExtraArtifact('report.txt', b'report')]}
    publisher(cli, config, site_root, **options)
    cli.dry_run = True
    with RouteCatalog() as routes:
        run_build(cli, config, site_root, route_catalog=routes, **options)
        expected = {route.key: route for route in routes}
    cli.dry_run = False
    api006_lose_cache(site_root, config, loss)
    cli.only_sections = ['rss']
    with RouteCatalog() as routes:
        run_build(cli, config, site_root, route_catalog=routes)
        assert {route.key: route for route in routes} == expected


def api006_lose_cache(root, config, loss):
    cache = root / '.build-cache.json'
    if loss == 'missing':
        cache.unlink()
    elif loss == 'corrupt':
        cache.write_bytes(b'{broken')
    else:
        config['build']['cache_file'] = 'new-cache.json'


def test_api006_old_unknown_routes_require_full_discovery(site_root, seo_config):
    cli, config = seo_config
    run_build(cli, config, site_root, extra_pages=[page(config)])
    state = ownership_path(site_root / 'output')
    legacy = json.loads(state.read_text())
    legacy.pop('routes', None)
    state.write_text(json.dumps(legacy))
    (site_root / '.build-cache.json').unlink()
    cli.only_sections = ['rss']
    before = snapshot(site_root / 'output'), state.read_bytes()
    with RouteCatalog() as routes:
        with pytest.raises(ValueError, match='route metadata unavailable'):
            run_build(cli, config, site_root, route_catalog=routes)
    assert (snapshot(site_root / 'output'), state.read_bytes()) == before


@pytest.mark.parametrize('invalid', [None, [], {'page:about': None}, {'wrong': {}},
    {'page:about': {'key': 'page:about'}},
    {'page:about': {'key': 'page:about', 'section': 'pages', 'url': None, 'output_path': 'about/index.html'}},
    {'wrong': {'key': 'page:about', 'section': 'pages', 'url': '/about/', 'output_path': 'about/index.html'}},
    {'page:about': {'key': 'page:about', 'section': 'pages', 'url': '/about/', 'output_path': 'unknown/index.html'}},
])
def test_api006_malformed_durable_routes_preserve_generation(site_root, seo_config, invalid):
    cli, config = seo_config
    run_build(cli, config, site_root, extra_pages=[page(config)])
    state = ownership_path(site_root / 'output')
    data = json.loads(state.read_text())
    data['routes'] = invalid
    state.write_text(json.dumps(data))
    before = snapshot(site_root / 'output'), state.read_bytes()
    with pytest.raises(ValueError, match='route metadata'):
        run_build(cli, config, site_root)
    assert (snapshot(site_root / 'output'), state.read_bytes()) == before


@pytest.mark.parametrize('defect', ['none', 'absent', 'scalar', 'invalid', 'mismatch'])
def test_api006_legacy_metadata_admission(site_root, seo_config, defect):
    cli, config = seo_config
    run_build(cli, config, site_root, extra_pages=[page(config)])
    state = ownership_path(site_root / 'output')
    legacy = json.loads(state.read_text())
    legacy.pop('routes')
    state.write_text(json.dumps(legacy))
    cache = site_root / '.build-cache.json'
    data = json.loads(cache.read_text())
    metadata = data['__output_roots__'][str(site_root / 'output')]
    api006_damage_metadata(metadata, defect)
    cache.write_text(json.dumps(data))
    cli.only_sections = ['rss']
    with RouteCatalog() as routes:
        if defect == 'none':
            run_build(cli, config, site_root, route_catalog=routes)
            assert next(route for route in routes if route.key == 'page:about') == page(config).route
        else:
            with pytest.raises(ValueError, match='route metadata'):
                run_build(cli, config, site_root, route_catalog=routes)


def api006_damage_metadata(metadata, defect):
    if defect == 'absent':
        metadata['__routes__'] = {}
    elif defect == 'scalar':
        metadata['__routes__'] = []
    elif defect == 'invalid':
        metadata['__routes__'] = {key: None for key in metadata['__routes__']}
    elif defect == 'mismatch':
        for value in metadata['__routes__'].values():
            value['output_path'] = 'unknown/index.html'


def test_api006_unknown_metadata_never_invents_routes_without_discovery(site_root, seo_config):
    cli, config = seo_config
    run_build(cli, config, site_root, extra_pages=[page(config)])
    state = ownership_path(site_root / 'output')
    data = json.loads(state.read_text())
    data.pop('routes')
    state.write_text(json.dumps(data))
    (site_root / '.build-cache.json').unlink()
    cli.only_sections = ['rss']
    before = (site_root / 'output/about/index.html').read_bytes()
    run_build(cli, config, site_root)
    assert (site_root / 'output/about/index.html').read_bytes() == before
    assert 'page:about' not in json.loads(state.read_text())['routes']


def test_api006_disposable_metadata_cannot_override_owner(site_root, seo_config):
    cli, config = seo_config
    extra = page(config)
    run_build(cli, config, site_root, extra_pages=[extra])
    cache = site_root / '.build-cache.json'
    data = json.loads(cache.read_text())
    data['__output_roots__'][str(site_root / 'output')]['__routes__'] = {'page:about': None}
    cache.write_text(json.dumps(data))
    cli.only_sections = ['rss']
    with RouteCatalog() as routes:
        run_build(cli, config, site_root, route_catalog=routes)
        assert next(route for route in routes if route.key == extra.route.key) == extra.route
