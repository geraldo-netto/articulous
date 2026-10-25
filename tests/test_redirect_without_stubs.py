"""REVIEW-027: host redirects precede terminal filesystem validation."""
import random
from urllib.parse import quote

import pytest

from articulous.site_validation import check_link, read_pages
from test_site_validation import html_page


@pytest.mark.parametrize('base', ['', '/blog', 'https://example.test/blog'])
@pytest.mark.parametrize('route', ['/old.html', '/old/', '/old%23name/', '/caf%C3%A9.html'])
@pytest.mark.parametrize('stub', [False, True])
def test_review027_redirects_need_no_source_or_intermediate_stub(tmp_path, base, route, stub):
    (tmp_path / 'new.html').write_text(html_page(base + '/new.html', '<b id="ok">target</b>'))
    if stub:
        (tmp_path / 'middle.html').write_text('obsolete')
    failures = []
    redirects = {route: '/middle.html#ok', '/middle.html': '/new.html'}
    check_link(tmp_path, base + route + '#missing', base + '/', base,
               redirects, read_pages(tmp_path, []), failures, 'chain')
    assert failures == []


@pytest.mark.parametrize('target,diagnostic', [
    ('/absent.html', 'missing'), ('/new.html#absent', 'missing fragment'),
    ('/old.html', 'redirect loop'),
    ('//remote.test/missing', 'missing redirect target'),
])
def test_review027_terminal_faults_and_cycles_remain_visible(tmp_path, target, diagnostic):
    (tmp_path / 'new.html').write_text(html_page('/new.html', '<b id="ok">target</b>'))
    failures = []
    check_link(tmp_path, '/old.html#ok', '/', '', {'/old.html': target},
               read_pages(tmp_path, []), failures, 'chain')
    assert len(failures) == 1 and diagnostic in failures[0]


def test_review027_seeded_encoded_routes_and_outside_origins(tmp_path):
    (tmp_path / 'new.html').write_text(html_page('/new.html', '<b id="ok">target</b>'))
    pages = read_pages(tmp_path, [])
    randomizer = random.Random(27)
    for _ in range(32):
        name = ''.join(randomizer.choice('aé日 #?%') for _ in range(12))
        route = '/' + quote(name, safe='') + '/'
        failures = []
        check_link(tmp_path, route + '#ok', 'https://example.test/', 'https://example.test',
                   {route: '/new.html'}, pages, failures, 'seeded')
        assert failures == []
    for url in ('https://remote.test/old.html', 'https://example.test/outside/old.html'):
        failures = []
        check_link(tmp_path, url, 'https://example.test/blog/', 'https://example.test/blog',
                   {'/old.html': '/missing.html'}, pages, failures, 'outside')
        assert failures == []
