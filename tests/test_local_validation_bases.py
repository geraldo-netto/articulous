"""REVIEW-017: local publication links are checked with or without a web origin."""
from urllib.parse import quote
import random

import pytest

from articulous.site_validation import local_path, validate_site
from articulous.validation_contracts import ValidationPlan
from test_site_validation import html_page


@pytest.mark.parametrize('base', ['', '/blog', 'https://example.test/blog'])
def test_review017_missing_links_and_valid_local_boundaries(tmp_path, base):
    (tmp_path / 'index.html').write_text(html_page(base + '/', '<a href="missing.html">broken</a>'))
    (tmp_path / 'search.json').write_text('[]')
    (tmp_path / 'map.xml').write_text('<urlset/>')
    plan = ValidationPlan({'index.html': base + '/'}, frozenset(), frozenset(), 'search.json', 'map.xml', {})
    with pytest.raises(ValueError, match='missing missing.html'):
        validate_site(tmp_path, base, plan)
    body = '<b id="café">target</b><a href="#caf%C3%A9">valid</a><img src="image.png">'
    (tmp_path / 'index.html').write_text(html_page(base + '/', body))
    (tmp_path / 'image.png').write_bytes(b'image')
    assert validate_site(tmp_path, base, plan).html_pages == 1


@pytest.mark.parametrize('base', ['', '/blog'])
@pytest.mark.parametrize('url', ['https://remote.test/missing', '//remote.test/missing', 'mailto:a@example.test'])
def test_review017_remote_urls_remain_unowned(tmp_path, base, url):
    assert local_path(tmp_path, url, base) is None


@pytest.mark.parametrize('base', ['', '/blog', 'https://example.test/blog'])
def test_review017_seeded_paths_and_escape_boundaries(tmp_path, base):
    randomizer = random.Random(17)
    for _ in range(32):
        name = ''.join(randomizer.choice('aé日 #?%') for _ in range(8))
        url = base + '/' + quote(name, safe='') + '/'
        assert local_path(tmp_path, url, base) == tmp_path / name / 'index.html'
    with pytest.raises(ValueError, match='escapes'):
        local_path(tmp_path, base + '/%2e%2e/escape', base)
