"""REVIEW-016: persisted listing routes preserve the models' exact canonical URL."""
import lxml.etree as etree
import pytest

from articulous.composition import RouteCatalog
from articulous.pipeline import run_build


@pytest.mark.parametrize('suffix', ['', '/'])
@pytest.mark.parametrize('first', [False, True])
def test_review016_listing_canonicals_survive_partial_discovery(site_root, seo_config, suffix, first):
    cli, config = seo_config
    config['urls']['index'] = '/{lang}/page/{page}' + suffix
    config['urls']['tag'] = '/{lang}/tags/{tag}' + suffix
    config['urls']['index_first'] = '/{lang}/' if first else None
    config['site']['pagination'].update(per_page=1, paginate_tags=True)
    config['sitemap']['include_listings'] = True
    with RouteCatalog() as catalog:
        run_build(cli, config, site_root, route_catalog=catalog)
        expected = {route.key: route for route in catalog}
    sitemap = set(etree.parse(str(site_root / 'output/sitemap.xml')).xpath('//*[local-name()="loc"]/text()'))
    listings = [route for route in expected.values() if route.section in ('index', 'tags')]
    assert listings
    for route in listings:
        document = etree.HTML((site_root / 'output' / route.output_path).read_bytes())
        assert document.xpath('//link[@rel="canonical"]/@href') == [route.url]
        assert route.url in sitemap
    first_url = 'https://example.test/en/' if first else 'https://example.test/en/page/1' + suffix
    assert expected['index:en:1'].url == first_url
    assert expected['tag:en:intro'].url == 'https://example.test/en/tags/intro' + suffix
    assert expected['tag:en:news/page/2'].url == 'https://example.test/en/tags/news/page/2/'
    (site_root / '.build-cache.json').unlink()
    cli.only_sections = ['rss']
    with RouteCatalog() as catalog:
        run_build(cli, config, site_root, route_catalog=catalog)
        assert {route.key: route for route in catalog} == expected
