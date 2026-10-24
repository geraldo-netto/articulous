"""ARCH-003: caller-owned pages share engine routes, safety and sitemap policy."""
from dataclasses import replace
from pathlib import Path
import json
import random
from types import SimpleNamespace

import lxml.etree as etree
import pytest

from articulous.composition import RouteCatalog
from articulous.composition_contracts import ExtraPage, Route
from articulous.models import build_tag_index_model
from articulous.pipeline import build_ctx_from_config, run_build


def page(config, name='about', category='static'):
    base = config['site']['base_url']
    return ExtraPage(Route('page:' + name, 'pages', base + '/' + name + '/',
                           name + '/index.html', 'en', category),
                     b'<index lang="en" page="1" total="1"/>',
                     Path(config['paths']['xsl_dir']) / 'pages/index.xsl')


@pytest.mark.parametrize('engine', ['native', 'lxml'])
@pytest.mark.parametrize('listings', [False, True])
def test_arch003_extra_pages_sitemap_and_cached_routes(site_root, seo_config, engine, listings):
    cli, config = seo_config
    config['engines']['sitemap'] = engine
    config['sitemap']['include_listings'] = listings
    extra = [page(config), page(config, 'tags', 'listing'), page(config, 'missing', 'excluded')]
    with RouteCatalog() as routes:
        run_build(cli, config, site_root, extra_pages=extra, route_catalog=routes)
        first = list(routes)
        assert len(routes) == len(first)
        assert list(routes) == first
        assert all((site_root / 'output' / route.output_path).is_file() for route in first)
    urls = etree.parse(str(site_root / 'output/sitemap.xml')).xpath('//*[local-name()="loc"]/text()')
    assert extra[0].route.url in urls
    assert (extra[1].route.url in urls) == listings
    assert extra[2].route.url not in urls
    with RouteCatalog() as routes:
        run_build(cli, config, site_root, extra_pages=extra, route_catalog=routes)
        assert list(routes) == first


def test_arch003_tag_index_reuses_memberships(seo_config):
    _, config = seo_config
    context = build_ctx_from_config(config, False)
    articles = [SimpleNamespace(tags=['Linux', 'Linux']), SimpleNamespace(tags=['Linux', ''])]
    model = build_tag_index_model(articles, 'en', context)
    assert [(tag.tag, tag.count) for tag in model.tags] == [('Linux', 2)]
    assert model.tags[0].url.endswith('/en/tags/linux/')
    assert b'count="2"' in model.to_xml()
    assert build_tag_index_model([], 'fr', context).tags == ()
    with pytest.raises(ValueError, match='Duplicate tag slug'):
        build_tag_index_model([SimpleNamespace(tags=['A B', 'a-b'])], 'en', context)


@pytest.mark.parametrize('seed', range(32))
def test_arch003_invalid_route_fuzz(seo_config, seed):
    _, config = seo_config
    invalid = random.Random(seed).choice([
        '../index.html', '/absolute', 'assets/a.html', './index.html', 'a//b',
        'a/../b', 'a\\b', '', 'a\x00b', 'a/',
    ])
    with pytest.raises(ValueError, match='output path'):
        replace(page(config).route, output_path=invalid)


@pytest.mark.parametrize('changes', [
    {'category': 'other'}, {'language': []}, {'key': ''}, {'section': ''},
    {'sitemap': 1}, {'url': '//external/'}
])
def test_arch003_invalid_route_metadata(seo_config, changes):
    _, config = seo_config
    with pytest.raises(ValueError):
        replace(page(config).route, **changes)


@pytest.mark.parametrize('target', ['en/articles/first-post', 'en/articles/first-post/index.html/child', 'assets'])
def test_arch003_collisions_preserve_previous_output(site_root, seo_config, target):
    cli, config = seo_config
    run_build(cli, config, site_root)
    source = site_root / 'output/en/articles/first-post/index.html'
    before = source.read_bytes()
    with pytest.raises(ValueError):
        run_build(cli, config, site_root, extra_pages=[page(config, target)])
    assert source.read_bytes() == before


def test_arch003_invalid_page_contracts(site_root, seo_config):
    cli, config = seo_config
    extra = page(config)
    with pytest.raises(ValueError, match='XML bytes'):
        replace(extra, model='bad')
    with pytest.raises(ValueError, match='pages'):
        replace(extra, route=replace(extra.route, section='index'))
    with pytest.raises(ValueError, match='canonical'):
        run_build(cli, config, site_root, extra_pages=[replace(extra, route=replace(extra.route, url='https://wrong.test/'))])
    with pytest.raises(ValueError, match='engine'):
        replace(extra, engine='native')
    with pytest.raises(ValueError, match='not-found'):
        replace(extra, role='not-found')
    with pytest.raises(ValueError, match='role'):
        replace(extra, role='unknown')


def test_arch003_retained_routes_and_not_found(site_root, seo_config):
    cli, config = seo_config
    extra = page(config, '404.html', 'excluded')
    extra = replace(extra, route=replace(extra.route, output_path='404.html', url=config['site']['base_url']+'/404.html'), role='not-found')
    run_build(cli, config, site_root, extra_pages=[extra])
    cli.only_sections = ['rss']
    with RouteCatalog() as routes:
        run_build(cli, config, site_root, route_catalog=routes)
        retained = {r.key: r for r in routes}
        assert retained[extra.route.key] == extra.route
        assert retained['article:en:first-post'].category == 'article'


def test_arch003_dry_route_discovery(site_root, seo_config):
    cli, config = seo_config
    cli.dry_run = True
    with RouteCatalog() as routes:
        run_build(cli, config, site_root, extra_pages=[page(config)], route_catalog=routes)
        assert any(route.key == 'page:about' for route in routes)
    assert not (site_root / 'output').exists()


def test_arch003_reserved_feed_fails_before_publication(site_root, seo_config):
    cli, config = seo_config
    cli.only_sections = ['rss']
    config['urls']['rss'] = '/assets/rss.xml'
    with pytest.raises(ValueError, match='reserved assets'):
        run_build(cli, config, site_root)
    assert not (site_root / 'output').exists()


def test_arch003_corrupt_retained_metadata_preserves_output(site_root, seo_config):
    cli, config = seo_config
    run_build(cli, config, site_root)
    cache = site_root / '.build-cache.json'
    data = json.loads(cache.read_text())
    routes = data['__output_roots__'][str(site_root / 'output')]['__routes__']
    routes['article:en:first-post']['output_path'] = 'other/index.html'
    cache.write_text(json.dumps(data))
    cli.only_sections = ['rss']
    before = (site_root / 'output/rss.xml').read_bytes()
    with pytest.raises(ValueError, match='Retained route metadata'):
        run_build(cli, config, site_root)
    assert (site_root / 'output/rss.xml').read_bytes() == before
