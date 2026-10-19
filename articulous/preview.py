"""Optional loopback preview with owned sockets and configurable publication policy."""
import argparse
import functools
import http.server
import io
from pathlib import Path
import socket
import threading
from urllib.parse import unquote, urlsplit
import webbrowser


class PreviewServer(http.server.ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = True

    def __init__(self, address, handler):
        self._clients = set()
        self._client_lock = threading.Lock()
        self._closing = False
        super().__init__(address, handler)

    def get_request(self):
        client, address = super().get_request()
        with self._client_lock:
            if self._closing:
                client.close()
                raise OSError('Preview is closing')
            self._clients.add(client)
        return client, address

    def close_request(self, request):
        with self._client_lock:
            self._clients.discard(request)
            super().close_request(request)

    def server_close(self):
        with self._client_lock:
            self._closing = True
            for client in self._clients:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        super().server_close()


def preview_path(root, value, internal):
    try:
        parts = Path(unquote(urlsplit(value).path)).parts
        if any(part == '..' or part.startswith('.') or part in internal for part in parts):
            return None
        target = root.joinpath(*parts[1:]) if parts and parts[0] == '/' else root.joinpath(*parts)
        if not target.resolve().is_relative_to(root.resolve()):
            return None
        return target
    except ValueError:
        return None


class Handler(http.server.SimpleHTTPRequestHandler):
    timeout = 10

    def __init__(self, *args, directory, internal=(), not_found=None, **kwargs):
        self.root = Path(directory).resolve()
        self.internal = frozenset(internal)
        self.not_found_route = not_found
        super().__init__(*args, directory=str(self.root), **kwargs)

    def send_head(self):
        target = preview_path(self.root, self.path, self.internal)
        if target is None:
            return self.not_found()
        if target.is_dir():
            target /= 'index.html'
        if not target.is_file() or not target.resolve().is_relative_to(self.root):
            return self.not_found()
        return super().send_head()

    def not_found(self):
        target = preview_path(self.root, self.not_found_route, ()) if self.not_found_route else None
        body = target.read_bytes() if target is not None and target.is_file() else b'Not found\n'
        self.send_response(404)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if target else 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        return None if self.command == 'HEAD' else io.BytesIO(body)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, format, *args):
        if not args or not str(args[1] if len(args) > 1 else '').startswith('2'):
            super().log_message(format, *args)


def serve(root, port=8000, *, internal=(), not_found=None, open_browser=False):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('port must be from 0 through 65535')
    if not root.is_dir():
        print(f'{root} does not exist yet: build the site first')
        return 1
    handler = functools.partial(Handler, directory=str(root), internal=internal, not_found=not_found)
    with PreviewServer(('127.0.0.1', port), handler) as server:
        url = f'http://127.0.0.1:{server.server_port}/'
        print(f'serving {root} at {url}  (only non-200s are logged)')
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('\nstopped')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--not-found')
    parser.add_argument('--internal', action='append', default=[])
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('--port must be from 0 through 65535')
    return serve(args.root, args.port, internal=args.internal, not_found=args.not_found, open_browser=args.open)


if __name__ == '__main__':
    raise SystemExit(main())
