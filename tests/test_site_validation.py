"""VALID-001: neutral publication URLs, compact DOM-free references and faulty output."""
from articulous.site_validation import local_path
from articulous.validation_contracts import ValidationPlan


import json
import pytest
from articulous.site_validation import (
    check_link, read_pages, validate_site,
)


def test_valid001_deployment_prefix_resolves_inside_publication(tmp_path):
    assert local_path(tmp_path, 'https://example.test/blog/caf%C3%A9/?q=1#top', 'https://example.test/blog') == tmp_path / 'café/index.html'



def html_page(canonical, body=''):
    return f'<!doctype html><html><head><meta charset="utf-8"><title>Neutral</title><link rel="canonical" href="{canonical}"></head><body>{body}</body></html>'


@pytest.fixture
def publication(tmp_path):
    base = 'https://example.test/blog'
    (tmp_path / 'index.html').write_text(html_page(base + '/', '<h2 id="café">Target</h2><a name="old">Old</a><template><a href="__url__"><span id="inert">Inert</span></a></template>'))
    (tmp_path / 'old.html').write_text(html_page(base + '/'))
    (tmp_path / 'lookup.json').write_text(json.dumps([{'url': base + '/'}]))
    (tmp_path / 'map.xml').write_text('<urlset><url><loc>' + base + '/</loc></url></urlset>')
    plan = ValidationPlan({'index.html': base + '/', 'old.html': base + '/'},
                          frozenset({base + '/'}), frozenset({base + '/'}),
                          'lookup.json', 'map.xml', {'/old.html': '/'})
    return tmp_path, base, plan


def test_valid001_neutral_publication_and_dom_lifetime(publication):
    root, base, plan = publication
    result = validate_site(root, base, plan)
    assert (result.html_pages, result.search_entries, result.sitemap_urls) == (2, 1, 1)
    failures = []
    pages = read_pages(root, failures)
    record = pages[root / 'index.html']
    assert all(type(value) is str for value in (*record.canonicals, *record.links, *record.anchors))
    assert 'inert' not in record.anchors
    assert '__url__' not in record.links
    for link in ['#caf%C3%A9', '#old', '#top', '#café:~:text=Target', 'old.html#café', 'https://other.test/absent', 'https://example.test/elsewhere/', 'lookup.json#anything']:
        check_link(root, link, base + '/', base, plan.redirects, pages, failures, 'neutral')
    assert failures == []


@pytest.mark.parametrize('link,expected', [('missing.html', 'missing'), ('#absent', 'fragment'), ('#inert', 'fragment')])
def test_valid001_bad_links(publication, link, expected):
    root, base, plan = publication
    (root / 'index.html').write_text(html_page(base + '/', f'<a href="{link}">Broken</a>'))
    with pytest.raises(ValueError, match=expected):
        validate_site(root, base, plan)


@pytest.mark.parametrize('url', ['https://other.test/blog/', 'http://example.test/blog/', 'mailto:a@example.test', 'https://example.test/blogger/'])
def test_valid001_urls_outside_publication_are_unowned(tmp_path, url):
    assert local_path(tmp_path, url, 'https://example.test/blog') is None


def test_valid001_origin_ports_and_escape(tmp_path):
    assert local_path(tmp_path, 'https://example.test:443/blog', 'https://example.test/blog') == tmp_path / 'index.html'
    with pytest.raises(ValueError, match='escapes'):
        local_path(tmp_path, 'https://example.test/blog/%2e%2e/secret', 'https://example.test/blog')


@pytest.mark.parametrize('target', ['/old.html', '/missing.html'])
def test_valid001_redirect_loops_and_missing_targets(publication, target):
    root, base, plan = publication
    plan.redirects['/old.html'] = target
    failures = []
    pages = read_pages(root, failures)
    check_link(root, 'old.html#top', base + '/', base, plan.redirects, pages, failures, 'neutral')
    assert failures


@pytest.mark.parametrize('defect', ['canonical', 'missing-page', 'duplicate-search', 'missing-search', 'duplicate-sitemap', 'foreign-sitemap', 'missing-sitemap', 'invalid-html', 'empty-html'])
def test_valid001_output_fault_controls(publication, defect):
    root, base, plan = publication
    if defect == 'canonical':
        (root / 'index.html').write_text(html_page(base + '/wrong'))
    elif defect == 'missing-page':
        (root / 'old.html').unlink()
    elif defect == 'invalid-html':
        with pytest.raises(ValueError, match='HTML parse errors'):
            validate_site(root, base, plan, html_errors=reported_errors)
        return
    elif defect == 'empty-html':
        (root / 'index.html').write_text('')
    elif defect.endswith('search'):
        entries = [{'url': base + '/'}] * (2 if defect.startswith('duplicate') else 0)
        (root / 'lookup.json').write_text(json.dumps(entries))
    else:
        url = base + '/' if defect.startswith('duplicate') else base + '/missing'
        urls = [url, url] if defect.startswith('duplicate') else [url]
        (root / 'map.xml').write_text('<urlset>' + ''.join('<loc>' + value + '</loc>' for value in urls) + '</urlset>')
    with pytest.raises(ValueError):
        validate_site(root, base, plan)


def reported_errors(source):
    return ['injected syntax error']


@pytest.mark.parametrize('data', [{}, [None], [{'url': 4}], [{}]])
def test_valid001_invalid_search_schema(publication, data):
    root, base, plan = publication
    (root / 'lookup.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Search'):
        validate_site(root, base, plan)


def test_valid001_sitemap_shards_and_invalid_indexes(publication):
    root, base, plan = publication
    (root / 'shard.xml').write_bytes((root / 'map.xml').read_bytes())
    (root / 'map.xml').write_text('<sitemapindex><sitemap><loc>' + base + '/shard.xml</loc></sitemap></sitemapindex>')
    assert validate_site(root, base, plan).sitemap_urls == 1
    for location in [base + '/missing.xml', 'https://outside.test/sitemap.xml', base + '/map.xml']:
        (root / 'map.xml').write_text('<sitemapindex><loc>' + location + '</loc></sitemapindex>')
        with pytest.raises(ValueError, match='Sitemap|sitemap'):
            validate_site(root, base, plan)
    (root / 'map.xml').write_text('<unexpected/>')
    with pytest.raises(ValueError, match='Unsupported sitemap'):
        validate_site(root, base, plan)
