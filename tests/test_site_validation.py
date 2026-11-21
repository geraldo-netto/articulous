"""VALID-001: neutral publication URLs, compact DOM-free references and faulty output."""
from articulous.site_validation import local_path
from articulous.validation_contracts import ValidationPlan
from urllib.parse import quote


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
    (tmp_path / 'map.xml').write_text('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>' + base + '/</loc></url></urlset>')
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


@pytest.mark.parametrize('name', ['a#b', 'a?b', 'a%b', 'a%23b', '日本語', 'a b'])
@pytest.mark.parametrize('prefix', ['', '/blog%23name'])
def test_review004_filesystem_routes_are_encoded_before_url_resolution(tmp_path, name, prefix):
    from articulous.site_validation import validate_pages
    base = 'https://example.test' + prefix
    directory = tmp_path / name
    directory.mkdir()
    path = directory / 'index.html'
    canonical = base + '/' + quote(name, safe='') + '/'
    path.write_text(html_page(canonical, '<img src="image.png"><a href="#café">self</a><b id="café">anchor</b>'))
    (directory / 'image.png').write_bytes(b'image')
    plan = ValidationPlan({f'{name}/index.html': canonical}, frozenset(), frozenset(), '', '', {})
    failures = []
    pages = read_pages(tmp_path, failures)
    validate_pages(tmp_path, base, plan, pages, failures)
    assert failures == []
    (directory / 'image.png').unlink()
    validate_pages(tmp_path, base, plan, pages, failures)
    assert failures == [f'{name}/index.html: missing image.png']


def test_review004_encoded_redirect_routes_preserve_fragment_checks(publication):
    root, base, plan = publication
    (root / 'old#name.html').write_text(html_page(base + '/'))
    plan.redirects['/old%23name.html'] = '/'
    failures = []
    pages = read_pages(root, failures)
    check_link(root, 'old%23name.html#café', base + '/', base, plan.redirects, pages, failures, 'encoded')
    assert failures == []
    check_link(root, 'old%23name.html#missing', base + '/', base, plan.redirects, pages, failures, 'encoded')
    assert failures == ['encoded: missing fragment old%23name.html#missing']


@pytest.mark.parametrize('fragment', ['', '#top', '#café'])
@pytest.mark.parametrize('target', ['/old.html', '/missing.html'])
def test_review005_redirect_loops_and_missing_targets(publication, target, fragment):
    root, base, plan = publication
    plan.redirects['/old.html'] = target
    failures = []
    pages = read_pages(root, failures)
    check_link(root, 'old.html' + fragment, base + '/', base, plan.redirects, pages, failures, 'neutral')
    assert failures


@pytest.mark.parametrize('fragment', ['', '#top', '#café'])
def test_review005_valid_redirect_chain_and_cycle(publication, fragment):
    root, base, plan = publication
    (root / 'older.html').write_text(html_page(base + '/'))
    plan.redirects['/older.html'] = '/old.html'
    failures = []
    pages = read_pages(root, failures)
    check_link(root, 'older.html' + fragment, base + '/', base, plan.redirects, pages, failures, 'chain')
    assert failures == []
    plan.redirects['/old.html'] = '/older.html'
    check_link(root, 'older.html' + fragment, base + '/', base, plan.redirects, pages, failures, 'chain')
    assert failures == ['chain: redirect loop for /older.html']


@pytest.mark.parametrize('defect', ['canonical', 'missing-page', 'duplicate-search', 'missing-search', 'duplicate-sitemap', 'foreign-sitemap', 'missing-sitemap', 'invalid-html', 'empty-html'])
def test_valid001_output_fault_controls(publication, defect):
    root, base, plan = publication
    if defect == 'invalid-html':
        with pytest.raises(ValueError, match='HTML parse errors'):
            validate_site(root, base, plan, html_errors=reported_errors)
        return
    corrupt_output(root, base, defect)
    with pytest.raises(ValueError):
        validate_site(root, base, plan)


def corrupt_output(root, base, defect):
    if defect == 'canonical':
        (root / 'index.html').write_text(html_page(base + '/wrong'))
    elif defect == 'missing-page':
        (root / 'old.html').unlink()
    elif defect == 'empty-html':
        (root / 'index.html').write_text('')
    elif defect.endswith('search'):
        entries = [{'url': base + '/'}] * (2 if defect.startswith('duplicate') else 0)
        (root / 'lookup.json').write_text(json.dumps(entries))
    else:
        url = base + '/' if defect.startswith('duplicate') else base + '/missing'
        urls = [url, url] if defect.startswith('duplicate') else [url]
        (root / 'map.xml').write_text('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join('<url><loc>' + value + '</loc></url>' for value in urls) + '</urlset>')


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
    (root / 'map.xml').write_text('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>' + base + '/shard.xml</loc></sitemap></sitemapindex>')
    assert validate_site(root, base, plan).sitemap_urls == 1
    for location in [base + '/missing.xml', 'https://outside.test/sitemap.xml', base + '/map.xml']:
        (root / 'map.xml').write_text('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>' + location + '</loc></sitemap></sitemapindex>')
        with pytest.raises(ValueError, match='Sitemap|sitemap'):
            validate_site(root, base, plan)
    (root / 'map.xml').write_text('<unexpected/>')
    with pytest.raises(ValueError, match='Unsupported sitemap'):
        validate_site(root, base, plan)


@pytest.mark.parametrize('url', ['http://localhost:PORT/', 'http://localhost:99999/', 'http://[', 'a%00b.html'])
def test_review28_40_malformed_reference_preserves_other_failures(tmp_path, url):
    from articulous.site_validation import check_link, sitemap_index_targets
    failures = ['other.html: missing file']
    check_link(tmp_path, url, 'http://localhost/page', 'http://localhost', {}, {}, failures, 'page.html')
    assert len(failures) == 2
    assert failures[-1].startswith(f'page.html: invalid link {url}:')  # AUDIT1121-19
    assert list(sitemap_index_targets(tmp_path, 'http://localhost', [url], failures)) == []
    assert url in failures[-1]


@pytest.mark.parametrize('port', [0, 80, 65535])
def test_review28_40_valid_ipv6_and_port_boundaries(tmp_path, port):
    from articulous.site_validation import check_link
    base = f'http://[::1]:{port}'
    (tmp_path / 'real.html').write_text('ok')
    failures = []
    check_link(tmp_path, base + '/real.html', base + '/', base, {}, {}, failures, 'index.html')
    assert failures == []


def test_review28_41_directory_with_html_suffix_preserves_page_validation(publication):
    root, base, plan = publication
    directory = root / 'a-folder.html'
    directory.mkdir()
    (directory / 'child.html').write_text(html_page(base + '/a-folder.html/child.html'))
    plan.page_urls['a-folder.html/child.html'] = base + '/a-folder.html/child.html'
    (root / 'alias-file.html').symlink_to('a-folder.html/child.html')
    (root / 'alias-folder.html').symlink_to('a-folder.html', target_is_directory=True)
    (root / 'dangling.html').symlink_to('absent')
    assert validate_site(root, base, plan).html_pages == 3

    (root / 'outside.html').symlink_to(root.parent, target_is_directory=True)
    (directory / 'child.html').write_text(
        html_page(plan.page_urls['a-folder.html/child.html'], '<a href="absent.html">missing</a>')
    )
    with pytest.raises(ValueError) as errors:
        validate_site(root, base, plan)
    assert str(errors.value).splitlines() == [
        'outside.html: HTML page escapes output',
        'a-folder.html/child.html: missing absent.html',
    ]


@pytest.mark.parametrize('search', [None, '{', '[]]', '{}', '[null]'])
def test_audit1121_02_collects_independent_artifact_failures(publication, search):
    root, base, plan = publication
    (root / 'index.html').write_text(html_page(base + '/', '<a href="missing.html">broken</a>'))
    lookup = root / plan.search_path
    if search is None:
        lookup.unlink()
    else:
        lookup.write_text(search)
    (root / plan.sitemap_path).write_text('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f'<sitemap><loc>{base}/one.xml</loc></sitemap><sitemap><loc>{base}/two.xml</loc></sitemap></sitemapindex>')
    (root / 'one.xml').write_text('<broken')
    (root / 'two.xml').write_text('<unexpected/>')
    with pytest.raises(ValueError) as error:
        validate_site(root, base, plan)
    for name in ('missing.html', 'lookup.json', 'one.xml', 'two.xml'):
        assert name in str(error.value)


@pytest.mark.parametrize('end,problem', [('/start/', 'loop'), ('/absent', 'missing'), ('/#lost', 'fragment'),
                                        ('/%00', 'invalid'), ('/#caf%C3%A9', None), ('/lookup.json', None)])
def test_audit1121_10_validates_unlinked_redirects(publication, end, problem):
    root, base, plan = publication
    plan.redirects.update({'/start/': '/middle/', '/middle/': end})
    if problem is None:
        assert validate_site(root, base, plan).html_pages == 2
    else:
        with pytest.raises(ValueError, match=problem):
            validate_site(root, base, plan)


@pytest.mark.parametrize('length', [1, 2, 5])
def test_audit1121_11_symlink_loops_preserve_other_diagnostics(publication, length):
    root, base, plan = publication
    names = [f'loop-{index}.html' for index in range(length)]
    for index, name in enumerate(names):
        (root / name).symlink_to(names[(index + 1) % length])
    plan.page_urls[names[0]] = base + '/' + names[0]
    (root / 'index.html').write_text(html_page(base + '/', f'<a href="{names[0]}">loop</a><img src="absent.png">'))
    with pytest.raises(ValueError) as failure:
        validate_site(root, base, plan)
    for name in names:
        assert f'{name}: cannot read HTML page' in str(failure.value)
    assert 'missing absent.png' in str(failure.value)


def test_audit1121_18_keeps_disappearing_file_diagnostic(publication, monkeypatch):
    from pathlib import Path
    root, base, plan = publication
    page = root / 'disappearing.html'
    page.write_text('temporary')
    (root / 'index.html').write_text(html_page(base + '/', '<img src="absent.png">'))
    read = Path.read_bytes
    def remove_before_read(path):
        if path == page:
            path.unlink()
        return read(path)
    monkeypatch.setattr(Path, 'read_bytes', remove_before_read)
    with pytest.raises(ValueError) as failure:
        validate_site(root, base, plan)
    assert 'disappearing.html: cannot read HTML page' in str(failure.value)
    assert 'missing absent.png' in str(failure.value)
