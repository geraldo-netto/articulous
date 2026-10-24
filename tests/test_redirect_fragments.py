"""REVIEW-018: redirects inherit or replace fragments on each hop."""
import pytest
import random
from urllib.parse import quote

from articulous.site_validation import check_link, read_pages
from test_site_validation import html_page


@pytest.mark.parametrize('base', ['', '/blog', 'https://example.test/blog'])
@pytest.mark.parametrize('incoming,target,expected', [
    ('', '/new.html#absent', True),
    ('#absent', '/new.html#good', False),
    ('#good', '/new.html', False),
    ('#absent', '/new.html', True),
    ('#absent', '/new.html#', False),
    ('#absent', '/new.html#caf%C3%A9', False),
    ('', '/new.html#caf%C3%A9:~:text=target', False),
])
def test_review018_target_fragments_replace_or_inherit(tmp_path, base, incoming, target, expected):
    for name in ('old.html', 'new.html'):
        (tmp_path / name).write_text(html_page(base + '/' + name, '<b id="good">target</b><i id="café">target</i>'))
    failures = []
    pages = read_pages(tmp_path, failures)
    check_link(tmp_path, 'old.html' + incoming, base + '/', base,
               {'/old.html': target}, pages, failures, 'redirect')
    assert bool(failures) is expected
    assert all('missing fragment' in error for error in failures)


@pytest.mark.parametrize('last', ['/new.html', '/new.html#good', '/new.html#'])
def test_review018_fragment_state_survives_redirect_chain(tmp_path, last):
    base = 'https://example.test/blog'
    for name in ('older.html', 'old.html', 'new.html'):
        (tmp_path / name).write_text(html_page(base + '/' + name, '<b id="good">target</b>'))
    redirects = {'/older.html': '/old.html#good', '/old.html': last}
    failures = []
    pages = read_pages(tmp_path, failures)
    check_link(tmp_path, 'older.html#absent', base + '/', base, redirects, pages, failures, 'chain')
    assert failures == []


def test_review018_seeded_fragment_values(tmp_path):
    base = 'https://example.test'
    for name in ('old.html', 'new.html'):
        (tmp_path / name).write_text(html_page(base + '/' + name, '<b id="good">target</b>'))
    pages = read_pages(tmp_path, [])
    randomizer = random.Random(18)
    for _ in range(64):
        fragment = ''.join(randomizer.choice('abé%/#\0') for _ in range(randomizer.randrange(129)))
        failures = []
        check_link(tmp_path, 'old.html#good', base + '/', base,
                   {'/old.html': '/new.html#' + quote(fragment, safe='')}, pages, failures, 'seeded')
        assert bool(failures) == bool(fragment)
