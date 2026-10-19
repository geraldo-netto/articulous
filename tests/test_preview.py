"""DEV-001: loopback confinement, native socket settlement and CLI boundaries."""
from contextlib import contextmanager
import functools
import http.client
import http.server
import socket
import threading

import pytest

from articulous import preview


@contextmanager
def running(root, **kwargs):
    server = preview.PreviewServer(('127.0.0.1', 0), functools.partial(preview.Handler, directory=str(root), **kwargs))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        assert not any(worker.is_alive() for worker in getattr(server, '_threads'))
        assert not server._clients


@pytest.mark.parametrize('method,path,status,body', [
    ('GET', '/', 200, b'home'), ('GET', '/nested/', 200, b'nested'),
    ('GET', '/folder/', 404, b'missing'), ('GET', '/absent', 404, b'missing'),
    ('HEAD', '/absent', 404, b''), ('GET', '/.secret', 404, b'missing'),
    ('GET', '/rules', 404, b'missing'), ('GET', '/%2e%2e/secret', 404, b'missing'),
    ('GET', '/escape', 404, b'missing'), ('GET', '/escape-dir/', 404, b'missing'),
])
def test_dev001_native_preview(tmp_path, method, path, status, body):
    root = tmp_path / 'site'
    root.mkdir()
    for name, content in [('index.html', 'home'), ('404.html', 'missing'), ('.secret', 'secret'), ('rules', 'secret')]:
        (root / name).write_text(content)
    (root / 'nested').mkdir()
    (root / 'nested/index.html').write_text('nested')
    (root / 'folder').mkdir()
    (tmp_path / 'outside').write_text('private')
    (root / 'escape').symlink_to(tmp_path / 'outside')
    (root / 'escape-dir').symlink_to(tmp_path, target_is_directory=True)
    with running(root, internal=('rules',), not_found='/404.html') as server:
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            assert (response.status, response.read()) == (status, body)
            assert response.getheader('Cache-Control') == 'no-store'
        finally:
            connection.close()


def test_dev001_idle_client_is_fenced_before_root_release(tmp_path):
    admitted = threading.Event()
    class Observed(preview.Handler):
        def setup(self):
            super().setup()
            admitted.set()
    with preview.PreviewServer(('127.0.0.1', 0), functools.partial(Observed, directory=str(tmp_path))) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        with socket.create_connection(('127.0.0.1', server.server_port), timeout=2) as client:
            assert admitted.wait(2)
            server.shutdown()
            server.server_close()
            thread.join()
            assert client.recv(1) == b''
            assert not server._clients
            assert not any(worker.is_alive() for worker in getattr(server, '_threads'))


@pytest.mark.parametrize('value', ['/../secret', '/%2e%2e/secret', '/.secret', '/rules', 'http://['])
def test_dev001_invalid_path_policy(tmp_path, value):
    assert preview.preview_path(tmp_path, value, ('rules',)) is None


def test_dev001_relative_and_outside_paths(tmp_path):
    assert preview.preview_path(tmp_path, 'index.html', ()) == tmp_path / 'index.html'
    (tmp_path / 'escape').symlink_to(tmp_path.parent)
    assert preview.preview_path(tmp_path, 'escape/other', ()) is None


def test_dev001_accept_after_cutoff_and_shutdown_fault(tmp_path, monkeypatch):
    with preview.PreviewServer(('127.0.0.1', 0), preview.Handler) as server:
        client, peer = socket.socketpair()
        try:
            server._closing = True
            monkeypatch.setattr(http.server.ThreadingHTTPServer, 'get_request', admitted_request(client))
            with pytest.raises(OSError, match='closing'):
                server.get_request()
            assert client.fileno() == -1
            server._clients.add(client)
            server.server_close()
            server.close_request(client)
        finally:
            client.close()
            peer.close()


def admitted_request(client):
    def accept(server):
        return client, ('127.0.0.1', 0)
    return accept


@pytest.mark.parametrize('port', [-1, 65536, True, '0'])
def test_dev001_invalid_port(tmp_path, port):
    with pytest.raises(ValueError, match='port'):
        preview.serve(tmp_path, port)


def stop(server):
    raise KeyboardInterrupt


def test_dev001_cli_and_default_missing(tmp_path, monkeypatch, capsys):
    assert preview.serve(tmp_path / 'absent') == 1
    monkeypatch.setattr(preview.PreviewServer, 'serve_forever', stop)
    opened = []
    monkeypatch.setattr(preview.webbrowser, 'open', opened.append)
    assert preview.main([str(tmp_path), '--port', '0', '--open']) == 0
    assert opened[0] != 'http://127.0.0.1:0/'
    assert 'stopped' in capsys.readouterr().out
    assert preview.serve(tmp_path, 0) == 0
    with pytest.raises(SystemExit):
        preview.main([str(tmp_path), '--port', '-1'])
    monkeypatch.undo()
    with running(tmp_path) as server:
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
        try:
            connection.request('GET', '/absent')
            response = connection.getresponse()
            assert response.read() == b'Not found\n'
            assert response.getheader('Content-Type') == 'text/plain; charset=utf-8'
        finally:
            connection.close()


def test_dev001_log_boundary(monkeypatch):
    handler = object.__new__(preview.Handler)
    calls = []
    monkeypatch.setattr(http.server.SimpleHTTPRequestHandler, 'log_message', record_log(calls))
    handler.log_message('empty')
    handler.log_message('one', 'request')
    handler.log_message('ok', 'request', '200')
    assert len(calls) == 2


def record_log(calls):
    def record(self, *args):
        calls.append(args)
    return record
