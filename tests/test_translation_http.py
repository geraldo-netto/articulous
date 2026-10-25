"""REVIEW-024: native loopback HTTP, response ownership and failed-job controls."""
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import random
import sys
import threading
import urllib.error

import lxml.etree as etree
import pytest

from articulous.backends.translation_http import HttpProvider
from articulous.markup_contracts import MarkupPolicy
from articulous.translation_cache import open_cache
from articulous.translation_client import Translator
from articulous.translation_contracts import XmlTranslationLayout
from articulous.translation_xml import mirror_xml


@dataclass(frozen=True)
class Reply:
    wire: bytes
    pause: bool = False
    disconnect: bool = False


def response(body, status=200, *, extra_length=0, disconnect=False):
    headers = (f'HTTP/1.1 {status} Test\r\nContent-Type: application/json; charset=utf-8\r\n'
               f'Content-Length: {len(body) + extra_length}\r\nConnection: keep-alive\r\n\r\n')
    return Reply(headers.encode('ascii') + body, disconnect=disconnect)


def success(content='  Risultato 世界😀  '):
    return response(json.dumps({'choices': [{'message': {'content': content}}]}, ensure_ascii=False).encode())


class LoopbackServer(HTTPServer):
    def __init__(self, replies):
        self.replies = deque(replies)
        self.requests = []
        self.connections = []
        self.peers = []
        self.errors = []
        self.release = threading.Event()
        super().__init__(('127.0.0.1', 0), ProviderHandler)

    @property
    def endpoint(self):
        return f'http://127.0.0.1:{self.server_port}/api/'

    def get_request(self):
        client, address = super().get_request()
        client.settimeout(3)
        self.connections.append(client)
        return client, address

    def handle_error(self, request, client_address):
        self.errors.append(repr(sys.exception()))


class ProviderHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_POST(self):
        server = self.server
        assert isinstance(server, LoopbackServer)
        size = int(self.headers.get('Content-Length', '0'))
        assert 0 < size <= 8192
        server.requests.append((self.command, self.path, dict(self.headers), self.rfile.read(size)))
        reply = server.replies.popleft()
        self.connection.sendall(reply.wire)
        if reply.pause:
            server.release.wait()
        if not reply.disconnect:
            server.peers.append(self.connection.recv(1))
        self.close_connection = True

    def log_message(self, format, *args):
        pass


@contextmanager
def running(replies):
    with pytest.MonkeyPatch.context() as environment, LoopbackServer(replies) as server:
        environment.setenv('no_proxy', '127.0.0.1')
        environment.setenv('NO_PROXY', '127.0.0.1')
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
        thread.start()
        try:
            yield server
        finally:
            server.release.set()
            server.shutdown()
            thread.join()
            assert not thread.is_alive()
            assert not server.errors
            assert not server.replies
            assert server.peers == [b''] * sum(not reply.disconnect for reply in replies)
            assert all(client.fileno() == -1 for client in server.connections)
    assert server.socket.fileno() == -1


def test_review024_real_request_unicode_and_cache():
    with running([success()]) as server, open_cache(':memory:') as cache:
        provider = HttpProvider(server.endpoint, 'modèle 世界', 0, 1)
        translator = Translator(provider, cache, prompt, str.strip, log, retries=0)
        assert translator.translate('Caffè 日本😀', 'it', 'ja', False) == 'Risultato 世界😀'
        assert translator.translate('Caffè 日本😀', 'it', 'ja', False) == 'Risultato 世界😀'
        assert (translator.calls, translator.cache_hits) == (1, 1)
        method, path, headers, body = server.requests[0]
        assert (method, path) == ('POST', '/api/v1/chat/completions')
        assert headers['Content-Type'] == 'application/json'
        assert int(headers['Content-Length']) == len(body)
        assert json.loads(body) == {'model': 'modèle 世界', 'temperature': 0, 'stream': False,
                                   'messages': [{'role': 'system', 'content': 'Translate it to ja'},
                                                {'role': 'user', 'content': 'Caffè 日本😀'}]}


@pytest.mark.parametrize('status', [400, 429, 500])
def test_review024_http_error_response_is_closed(status):
    with running([response(b'{"error":"retry"}', status)]) as server:
        with pytest.raises(urllib.error.HTTPError) as caught:
            HttpProvider(server.endpoint, 'model', timeout=1).post('System', 'User')
        try:
            assert caught.value.code == status
            assert caught.value.closed, 'REVIEW-024: retained HTTPError still owns an open response'
        finally:
            caught.value.close()


def invalid_bodies():
    shapes = [None, False, 0, '', [], {}, {'choices': []}, {'choices': [None]},
              {'choices': [{'message': {'content': None}}]},
              {'choices': [{'message': {'content': 4}}]}]
    bodies = [json.dumps(value).encode() for value in shapes]
    randomizer = random.Random(24024)
    bodies.extend(b'!' + randomizer.randbytes(size) for size in range(32))
    return bodies + [b'', b'{', b'\xff\xfe\x00', b'{"choices":[']


@pytest.mark.parametrize('body', invalid_bodies())
def test_review024_invalid_response_closes_native_connection(body):
    with running([response(body)]) as server:
        with pytest.raises(urllib.error.URLError, match='Invalid translation response'):
            HttpProvider(server.endpoint, 'model', timeout=1).post('System', 'User')


@pytest.mark.parametrize('content', ['', ' ', '日本😀', 'x' * 4096])
def test_review024_valid_response_boundaries(content):
    with running([success(content)]) as server:
        assert HttpProvider(server.endpoint, 'model', timeout=1).post('', 'User') == content.strip()


@pytest.mark.parametrize('reply,error', [
    (Reply(b'', disconnect=True), http.client.RemoteDisconnected),
    (response(b'{', extra_length=10, disconnect=True), http.client.IncompleteRead),
    (Reply(b'', pause=True), TimeoutError),
    (Reply(b'HTTP/1.1 200 OK\r\nContent-Length: 50\r\n\r\n{', pause=True), TimeoutError),
])
def test_review024_transport_faults_settle(reply, error):
    with running([reply]) as server:
        with pytest.raises(error):
            HttpProvider(server.endpoint, 'model', timeout=1).post('System', 'User')


def prompt(source, target, keep):
    return f'Translate {source} to {target}'


def log(*args):
    pass


def digest(value):
    return hashlib.sha256(value).hexdigest()


def translate_draft(tmp_path, provider, cache):
    source, target = tmp_path / 'original.xml', tmp_path / 'draft.xml'
    source.write_text('<entry><title>Original 世界</title><body/></entry>')
    original = source.read_bytes()
    translator = Translator(provider, cache, prompt, str.strip, log, retries=0)
    stats = {'units': 0, 'failed': 0}
    layout = XmlTranslationLayout(('title',), False, False, None, digest)
    mirror_xml(source, target, 'it', 'ja', translator, stats, layout, MarkupPolicy(), log)
    assert source.read_bytes() == original
    return etree.parse(str(target)), stats


@pytest.mark.parametrize('reply', [response(b'{"error":"retry"}', 503), response(b'{'),
                                   response(b'{', extra_length=10, disconnect=True),
                                   Reply(b'', disconnect=True)])
def test_review024_failed_http_job_has_no_success_provenance(tmp_path, monkeypatch, reply):
    from articulous import translation_client
    monkeypatch.setattr(translation_client.time, 'sleep', log)
    with running([reply]) as server, open_cache(':memory:') as cache:
        tree, stats = translate_draft(tmp_path, HttpProvider(server.endpoint, 'model', timeout=1), cache)
        assert stats == {'units': 1, 'failed': 1}
        assert tree.findtext('title') == 'Original 世界'
        assert tree.find('source-hash') is None
        assert cache.connection.execute('SELECT COUNT(*) FROM tr').fetchone() == (0,)


def test_review024_native_retry_then_cache_success(monkeypatch):
    from articulous import translation_client
    monkeypatch.setattr(translation_client.time, 'sleep', log)
    with running([response(b'busy', 429), success('Translated')]) as server, open_cache(':memory:') as cache:
        translator = Translator(HttpProvider(server.endpoint, 'model', timeout=1), cache,
                                prompt, str.strip, log, retries=1)
        assert translator.translate('Original', 'it', 'ja', False) == 'Translated'
        assert translator.translate('Original', 'it', 'ja', False) == 'Translated'
        assert (translator.calls, translator.cache_hits) == (2, 1)
        assert len(server.requests) == 2


def cancel_read(*args, **kwargs):
    raise KeyboardInterrupt


def test_review024_cancelled_native_read_closes_response(monkeypatch):
    with running([success()]) as server:
        monkeypatch.setattr(http.client.HTTPResponse, 'read', cancel_read)
        with pytest.raises(KeyboardInterrupt):
            HttpProvider(server.endpoint, 'model', timeout=1).post('System', 'User')


def fail_close(self):
    raise OSError('close fault')


def test_review024_close_failure_retains_response_owner(monkeypatch):
    original_close = urllib.error.HTTPError.close
    with running([response(b'busy', 503)]) as server:
        monkeypatch.setattr(urllib.error.HTTPError, 'close', fail_close)
        with pytest.raises(OSError, match='close fault') as caught:
            HttpProvider(server.endpoint, 'model', timeout=1).post('System', 'User')
        retained = caught.value.__context__
        assert isinstance(retained, urllib.error.HTTPError)
        try:
            assert retained.code == 503
            assert not retained.closed
        finally:
            original_close(retained)
        assert retained.closed
