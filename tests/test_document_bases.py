"""REVIEW-030: HTML references use the first active document base."""
import random
from urllib.parse import quote

import pytest

from articulous.site_validation import read_pages, validate_pages
from articulous.validation_contracts import ValidationPlan
from test_site_validation import html_page


def validate_document(root, base, head, body, extra=None):
    source = html_page(base + '/', body).replace('<head>', '<head>' + head)
    (root / 'index.html').write_text(source)
    urls = {'index.html': base + '/', **(extra or {})}
    plan = ValidationPlan(urls, frozenset(), frozenset(), '', '', {})
    failures = []
    validate_pages(root, base, plan, read_pages(root, failures), failures)
    return failures


@pytest.mark.parametrize('base', ['', '/blog', 'https://example.test/blog'])
@pytest.mark.parametrize('relative', [False, True])
def test_review030_base_directory_does_not_require_its_own_page(tmp_path, base, relative):
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/icon.png').write_bytes(b'image')
    href = 'docs/' if relative else base + '/docs/'
    head = f'<base href="{href}">'
    assert validate_document(tmp_path, base, head, '<img src="icon.png">') == []
    failures = validate_document(tmp_path, base, head, '<img src="missing.png">')
    assert failures == ['index.html: missing missing.png']


def test_review030_first_active_base_wins_and_templates_stay_inert(tmp_path):
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/icon.png').write_bytes(b'image')
    head = ('<base target="_blank"><template><base href="/inert/"></template>'
            '<base href="/docs/"><base href="/ignored/">')
    assert validate_document(tmp_path, 'https://example.test', head, '<img src="icon.png">') == []
    record = read_pages(tmp_path, [])[tmp_path / 'index.html']
    assert type(record.base_href) is str and record.base_href == '/docs/'


@pytest.mark.parametrize('href', ['https://remote.test/', '//remote.test/', 'https://example.test/outside/'])
def test_review030_remote_and_outside_prefix_bases_are_unowned(tmp_path, href):
    assert validate_document(tmp_path, 'https://example.test/blog', f'<base href="{href}">',
                             '<img src="absent.png"><a href="#absent">remote</a>') == []


@pytest.mark.parametrize('head', ['', '<base href="">', '<base href="javascript:alert(1)">',
                                '<base href="data:text/html,ignored">', '<base href="http://[">'])
def test_review030_absent_empty_and_invalid_bases_use_document_url(tmp_path, head):
    (tmp_path / 'icon.png').write_bytes(b'image')
    body = '<img src="icon.png"><b id="ok">target</b><a href="#ok">self</a>'
    assert validate_document(tmp_path, 'https://example.test', head, body) == []


@pytest.mark.parametrize('fragment,broken', [('ok', False), ('missing', True)])
def test_review030_fragments_belong_to_base_target_document(tmp_path, fragment, broken):
    base = 'https://example.test'
    (tmp_path / 'target.html').write_text(html_page(base + '/target.html', '<b id="ok">target</b>'))
    failures = validate_document(tmp_path, base, '<base href="target.html">',
                                 f'<a href="#{fragment}">target</a>', {'target.html': base + '/target.html'})
    assert bool(failures) is broken
    assert all('missing fragment' in message for message in failures)


def test_review030_seeded_encoded_directory_bases(tmp_path):
    randomizer = random.Random(30)
    for _ in range(32):
        name = ''.join(randomizer.choice('aé日 #?%') for _ in range(12))
        directory = tmp_path / name
        directory.mkdir()
        (directory / 'icon.png').write_bytes(b'image')
        head = '<base href="/' + quote(name, safe='') + '/">'
        assert validate_document(tmp_path, 'https://example.test', head, '<img src="icon.png">') == []
