"""SQLite route catalog and output-to-route boundary projections."""
from contextlib import closing
from dataclasses import asdict
import json
from pathlib import PurePosixPath
import sqlite3
from urllib.parse import quote

from . import composition_contracts as contracts


class RouteCatalog:
    def __init__(self):
        self._db = sqlite3.connect('')
        self._readers = set()
        self._closed = False
        try:
            with closing(self._db.execute('CREATE TABLE routes (key TEXT PRIMARY KEY, data TEXT NOT NULL)')):
                pass
        except BaseException:
            self._db.close()
            raise

    def _require_open(self):
        if self._closed:
            raise ValueError('Route catalog is closed')

    def record(self, route: contracts.Route) -> None:
        self._require_open()
        with closing(self._db.execute('INSERT INTO routes VALUES (?, ?)', (route.key, json.dumps(asdict(route))))):
            pass

    def _reader(self):
        self._require_open()
        reader = self._db.execute('SELECT data FROM routes ORDER BY rowid')
        try:
            self._readers.add(reader)
        except BaseException:
            reader.close()
            raise
        return reader

    def _release_reader(self, reader):
        if reader in self._readers:
            reader.close()
            self._readers.remove(reader)

    def __iter__(self):
        reader = self._reader()
        try:
            while True:
                self._require_open()
                row = reader.fetchone()
                if row is None:
                    return
                yield contracts.Route(**json.loads(row[0]))
        finally:
            self._release_reader(reader)

    def __len__(self):
        self._require_open()
        with closing(self._db.execute('SELECT COUNT(*) FROM routes')) as reader:
            return reader.fetchone()[0]

    def close(self):
        self._closed = True
        for reader in tuple(self._readers):
            self._release_reader(reader)
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def route_from_output(base_url: str, key: str, output_path: str) -> contracts.Route:
    prefix, _, tail = key.partition(':')
    section = {'article': 'articles', 'tag': 'tags'}.get(prefix, prefix)
    directory = prefix in ('article', 'index', 'tag')
    relative = str(PurePosixPath(output_path).parent) + '/' if directory else output_path
    relative = '' if relative == './' else relative
    category = {'article': 'article', 'index': 'listing', 'tag': 'listing'}.get(prefix, 'excluded')
    language = tail.split(':', 1)[0] if directory else None
    return contracts.Route(key, section, base_url.rstrip('/') + '/' + quote(relative, safe='/'),
                 output_path, language, category)


def validate_page_url(page: contracts.ExtraPage, base_url: str) -> None:
    relative = page.route.output_path
    if page.route.url.endswith('/'):
        relative = relative.removesuffix('index.html')
    if page.route.url != base_url.rstrip('/') + '/' + quote(relative, safe='/'):
        raise ValueError('Extra page canonical URL does not match its output path')
