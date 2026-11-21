"""REVIEW-029: every served file obeys requested and resolved path policy."""
import http.client
import random
from urllib.parse import quote

import pytest

from articulous.preview import Handler, preview_path
from test_preview import running


def request(server, method, route):
    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
    try:
        connection.request(method, route)
        response = connection.getresponse()
        return response.status, response.read(), response.getheader('Cache-Control')
    finally:
        connection.close()


@pytest.mark.parametrize('protected', ['.private', 'hosting'])
@pytest.mark.parametrize('form', ['file', 'directory', 'index'])
def test_review029_get_and_head_deny_protected_aliases(tmp_path, protected, form):
    private = tmp_path / protected
    private.mkdir()
    (private / 'secret.txt').write_text('secret')
    (tmp_path / '404.html').write_text('missing')
    alias = tmp_path / 'alias'
    if form == 'directory':
        alias.symlink_to(private, target_is_directory=True)
        route = '/alias/secret.txt'
    elif form == 'index':
        alias.mkdir()
        (alias / 'index.html').symlink_to(private / 'secret.txt')
        route = '/alias/'
    else:
        alias.symlink_to(private / 'secret.txt')
        route = '/alias'
    with running(tmp_path, internal=('hosting',), not_found='/404.html') as server:
        assert request(server, 'GET', route) == (404, b'missing', 'no-store')
        assert request(server, 'HEAD', route) == (404, b'', 'no-store')


@pytest.mark.parametrize('protected', ['.private', 'hosting'])
@pytest.mark.parametrize('alias', [False, True])
def test_review029_fallback_cannot_disclose_protected_file(tmp_path, protected, alias):
    target = tmp_path / protected
    target.write_text('secret')
    fallback = '/' + protected
    if alias:
        (tmp_path / '404.html').symlink_to(target)
        fallback = '/404.html'
    with running(tmp_path, internal=('hosting',), not_found=fallback) as server:
        assert request(server, 'GET', '/absent') == (404, b'Not found\n', 'no-store')
        assert request(server, 'HEAD', '/absent') == (404, b'', 'no-store')


def test_review029_public_aliases_and_ordinary_fallback_remain_supported(tmp_path):
    (tmp_path / 'public').mkdir()
    (tmp_path / 'public/index.html').write_text('public')
    (tmp_path / 'alias').symlink_to(tmp_path / 'public', target_is_directory=True)
    (tmp_path / '404.html').write_text('missing')
    with running(tmp_path, not_found='/404.html') as server:
        assert request(server, 'GET', '/alias/') == (200, b'public', 'no-store')
        assert request(server, 'HEAD', '/alias/') == (200, b'', 'no-store')
        assert request(server, 'GET', '/absent') == (404, b'missing', 'no-store')


def test_review029_seeded_encoded_aliases_and_outside_control(tmp_path):
    private = tmp_path / '.private'
    private.write_text('secret')
    randomizer = random.Random(29)
    for _ in range(32):
        name = 'alias' + ''.join(randomizer.choice('é日 #?%') for _ in range(12))
        (tmp_path / name).symlink_to(private)
        assert preview_path(tmp_path, '/' + quote(name, safe=''), ()) is None
    (tmp_path / 'outside').symlink_to(tmp_path.parent)
    assert preview_path(tmp_path, '/outside/secret', ()) is None


def test_review029_absolute_form_opens_the_validated_public_target(tmp_path):
    (tmp_path / '.private').write_text('secret')
    (tmp_path / 'public').write_text('public')
    alternate = tmp_path / 'http:/example.test'
    alternate.mkdir(parents=True)
    (alternate / 'public').symlink_to(tmp_path / '.private')
    with running(tmp_path) as server:
        assert request(server, 'GET', 'http://example.test/public') == (200, b'public', 'no-store')


def test_review029_surrogate_escape_cannot_select_a_different_file(tmp_path):
    (tmp_path / '.private').write_text('secret')
    (tmp_path / ('alias' + '\ufffd' * 3)).write_text('public')
    (tmp_path / 'alias\udc80').symlink_to(tmp_path / '.private')
    with running(tmp_path) as server:
        assert request(server, 'GET', '/alias%ED%B2%80') == (404, b'Not found\n', 'no-store')


def test_review029_decode_boundaries_and_direct_translation_rejection(tmp_path):
    (tmp_path / '\ufffd').write_text('public')
    assert preview_path(tmp_path, '/%80', ()) == tmp_path / '\ufffd'
    handler = object.__new__(Handler)
    handler.root = tmp_path
    handler.internal = frozenset()
    with pytest.raises(ValueError, match='not public'):
        handler.translate_path('/.private')


def test_review28_62_serves_boundary_and_custom_404_over_component_limit(tmp_path):
    import os
    limit = os.pathconf(tmp_path, 'PC_NAME_MAX')
    root = random.Random(62)
    (tmp_path / '404.html').write_bytes(b'missing')
    with running(tmp_path, not_found='/404.html') as server:
        for length in (limit - 1, limit, limit + 1, limit + 2, limit + 16):
            name = ''.join(root.choices('abcxyz', k=length))
            if length <= limit:
                (tmp_path / name).write_bytes(b'public')
                assert request(server, 'GET', '/' + name) == (200, b'public', 'no-store')
            else:
                assert request(server, 'GET', '/' + name) == (404, b'missing', 'no-store')
                assert request(server, 'HEAD', '/' + name) == (404, b'', 'no-store')


def test_review28_62_unreadable_404_route_uses_plain_fallback(tmp_path, monkeypatch):
    from pathlib import Path
    (tmp_path / '404.html').write_bytes(b'fallback')
    is_file = Path.is_file

    def probe(path):
        if path.name == '404.html':
            raise OSError('unavailable metadata')
        return is_file(path)

    monkeypatch.setattr(Path, 'is_file', probe)
    with running(tmp_path, not_found='/404.html') as server:
        assert request(server, 'GET', '/missing') == (404, b'Not found\n', 'no-store')


def test_review28_63_preview_distinguishes_directory_and_file_urls(tmp_path):
    (tmp_path / 'page.html').write_bytes(b'page')
    (tmp_path / '404.html').write_bytes(b'missing')
    (tmp_path / 'alias').symlink_to('page.html')
    (tmp_path / 'dir').mkdir()
    (tmp_path / 'dir/index.html').write_bytes(b'index')
    with running(tmp_path, not_found='/404.html') as server:
        for route in ('/page.html/', '/page.html///?v=1', '/alias/?v=2'):
            assert request(server, 'GET', route) == (404, b'missing', 'no-store')
            assert request(server, 'HEAD', route) == (404, b'', 'no-store')
        assert request(server, 'GET', '/dir/?v=1') == (200, b'index', 'no-store')
        assert request(server, 'GET', '/page.html?q=/') == (200, b'page', 'no-store')
