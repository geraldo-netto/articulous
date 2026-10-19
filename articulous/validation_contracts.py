"""Generated-publication expectations independent of parser and theme implementations."""
from dataclasses import dataclass
from typing import NamedTuple


class PageReferences(NamedTuple):
    canonicals: tuple[str, ...]
    links: tuple[str, ...]
    anchors: frozenset[str]


@dataclass(frozen=True)
class ValidationPlan:
    page_urls: dict[str, str]
    search_urls: frozenset[str]
    sitemap_urls: frozenset[str]
    search_path: str
    sitemap_path: str
    redirects: dict[str, str]


@dataclass(frozen=True)
class ValidationResult:
    html_pages: int
    search_entries: int
    sitemap_urls: int
