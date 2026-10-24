"""Independent route/page/artifact schemas and route collection interfaces."""
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .sections import validate_base_url


def _invalid_output_character(char):
    return char in '\\:' or ord(char) < 32 or ord(char) == 127


def validate_relative_output(value, *, reserved=('assets',)):
    if not isinstance(value, str) or not value:
        raise ValueError('Invalid output path')
    parts = value.split('/')
    if any(part in ('', '.', '..') for part in parts) or parts[0] in reserved:
        raise ValueError('Invalid output path: empty/dot segments or reserved assets')
    if any(_invalid_output_character(char) for char in value):
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
        validate_relative_output(self.output_path)
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


@dataclass(frozen=True)
class ExtraArtifact:
    output_path: str
    content: bytes

    def __post_init__(self):
        validate_relative_output(self.output_path)
        if not isinstance(self.content, bytes):
            raise ValueError('Artifact content must be bytes')


def artifact_values(values):
    result = tuple(values)
    if not all(isinstance(item, ExtraArtifact) for item in result):
        raise ValueError('Extra artifacts must contain ExtraArtifact values')
    return result


class RouteReader(Protocol):
    def __iter__(self) -> Iterator[Route]:
        ...

    def __len__(self) -> int:
        ...


class RouteWriter(RouteReader, Protocol):
    def record(self, route: Route) -> None:
        ...
