"""REVIEW-015: partial sitemap planning includes omitted, retained extra pages."""
from dataclasses import replace
import json

import lxml.etree as etree
import pytest

from articulous.ownership import ownership_path
from articulous.pipeline import run_build
from test_composition import page


@pytest.mark.parametrize('engine', ['native', 'lxml'])
@pytest.mark.parametrize('listings', [False, True])
@pytest.mark.parametrize('loss', ['none', 'missing', 'corrupt'])
def test_review015_retained_eligibility_survives_partial_sitemap(site_root, seo_config, engine, listings, loss):
    cli, config = seo_config
    config['engines']['sitemap'] = engine
    config['sitemap']['include_listings'] = listings
    extras = [page(config), page(config, 'list', 'listing'), page(config, 'excluded', 'excluded')]
    hidden = page(config, 'hidden')
    extras.append(replace(hidden, route=replace(hidden.route, sitemap=False)))
    run_build(cli, config, site_root, extra_pages=extras)
    expected = etree.parse(str(site_root / 'output/sitemap.xml')).xpath('//*[local-name()="loc"]/text()')
    cache = site_root / '.build-cache.json'
    if loss == 'missing':
        cache.unlink()
    elif loss == 'corrupt':
        cache.write_bytes(b'{broken')
    cli.only_sections = ['sitemap']
    run_build(cli, config, site_root)
    actual = etree.parse(str(site_root / 'output/sitemap.xml')).xpath('//*[local-name()="loc"]/text()')
    assert sorted(actual) == sorted(expected)
    assert len(actual) == len(set(actual))
    assert all((site_root / 'output' / item.route.output_path).is_file() for item in extras)


def test_review015_replacement_and_full_removal_override_retained_route(site_root, seo_config):
    cli, config = seo_config
    extra = page(config)
    run_build(cli, config, site_root, extra_pages=[extra])
    cli.only_sections = ['sitemap']
    replacement = replace(extra, route=replace(extra.route, sitemap=False))
    run_build(cli, config, site_root, extra_pages=[replacement])
    assert extra.route.url not in (site_root / 'output/sitemap.xml').read_text()
    cli.only_sections = None
    run_build(cli, config, site_root)
    assert not (site_root / 'output/about/index.html').exists()


def test_review015_unknown_retained_page_cannot_silently_leave_sitemap(site_root, seo_config):
    cli, config = seo_config
    run_build(cli, config, site_root, extra_pages=[page(config)])
    state = ownership_path(site_root / 'output')
    data = json.loads(state.read_text())
    data.pop('routes')
    state.write_text(json.dumps(data))
    (site_root / '.build-cache.json').unlink()
    before = (site_root / 'output/sitemap.xml').read_bytes(), state.read_bytes()
    cli.only_sections = ['sitemap']
    with pytest.raises(ValueError, match='route metadata unavailable'):
        run_build(cli, config, site_root)
    assert ((site_root / 'output/sitemap.xml').read_bytes(), state.read_bytes()) == before
