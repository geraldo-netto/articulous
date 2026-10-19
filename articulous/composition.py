"""Portable page and route contracts for composed builds."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path, PurePosixPath
import sqlite3
from urllib.parse import quote

from .sections import validate_base_url


def _validate_relative_output(value, *, reserved=('assets',)):
    if not isinstance(value, str) or not value:
        raise ValueError('Invalid output path')
    parts = value.split('/')
    if any(part in ('', '.', '..') for part in parts) or parts[0] in reserved:
        raise ValueError('Invalid output path: empty/dot segments or reserved assets')
    if '\\' in value or ':' in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('Invalid output path')


@dataclass(frozen=True)
class Route:
    key: str
    section: str
    url: str
    output_path: str
    language: str | None = None
    category: str = 'excluded'
    sitemap: bool = True

    def __post_init__(self):
        _validate_relative_output(self.output_path)
        if not isinstance(self.key, str) or not self.key or not isinstance(self.section, str) or not self.section:
            raise ValueError('Route key and section must be nonempty strings')
        if self.language is not None and not isinstance(self.language, str):
            raise ValueError('Route language must be a string or None')
        if self.category not in ('article', 'static', 'listing', 'excluded') or type(self.sitemap) is not bool:
            raise ValueError('Invalid sitemap category or eligibility')
        validate_base_url(self.url)

    def included(self, include_listings: bool) -> bool:
        return self.sitemap and (self.category in ('article', 'static') or
                                 self.category == 'listing' and include_listings)


@dataclass(frozen=True)
class ExtraPage:
    route: Route
    model: bytes
    stylesheet: Path
    engine: str = 'lxml'
    role: str = 'page'

    def __post_init__(self):
        if self.route.section != 'pages' or not self.route.key.startswith('page:'):
            raise ValueError('Extra pages require section pages and page: keys')
        if not isinstance(self.model, bytes) or not self.model:
            raise ValueError('Extra page model must contain XML bytes')
        if self.engine not in ('lxml', 'saxonc'):
            raise ValueError('Extra page engine must be lxml or saxonc')
        if self.role not in ('page', 'not-found'):
            raise ValueError('Unknown extra page role')
        if self.role == 'not-found' and self.route.category != 'excluded':
            raise ValueError('not-found pages must be excluded from the sitemap')


class RouteCatalog:
    def __init__(self):
        self._db = sqlite3.connect('')
        self._db.execute('CREATE TABLE routes (key TEXT PRIMARY KEY, data TEXT NOT NULL)')

    def record(self, route: Route) -> None:
        self._db.execute('INSERT INTO routes VALUES (?, ?)', (route.key, json.dumps(asdict(route))))

    def __iter__(self):
        for row in self._db.execute('SELECT data FROM routes ORDER BY rowid'):
            yield Route(**json.loads(row[0]))

    def __len__(self):
        return self._db.execute('SELECT COUNT(*) FROM routes').fetchone()[0]

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def route_from_output(base_url: str, key: str, output_path: str) -> Route:
    prefix, _, tail = key.partition(':')
    section = {'article': 'articles', 'tag': 'tags'}.get(prefix, prefix)
    directory = prefix in ('article', 'index', 'tag')
    relative = str(PurePosixPath(output_path).parent) + '/' if directory else output_path
    relative = '' if relative == './' else relative
    category = {'article': 'article', 'index': 'listing', 'tag': 'listing'}.get(prefix, 'excluded')
    language = tail.split(':', 1)[0] if directory else None
    return Route(key, section, base_url.rstrip('/') + '/' + quote(relative, safe='/'),
                 output_path, language, category)


def validate_page_url(page: ExtraPage, base_url: str) -> None:
    relative = page.route.output_path
    if page.route.url.endswith('/'):
        relative = relative.removesuffix('index.html')
    if page.route.url != base_url.rstrip('/') + '/' + quote(relative, safe='/'):
        raise ValueError('Extra page canonical URL does not match its output path')
