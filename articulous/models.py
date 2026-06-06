"""
Per-section model builders + URL helpers.

A "model" is the abstract per-page input that the section builder will
later serialise into XML and feed to its XSLT stylesheet.

Model builders take a :class:`SiteModelCtx` — a structural protocol
with the fields they actually need — and return typed page dataclasses
(``IndexPage``, ``TagPage``, ``RssFeed``, ``Sitemap``, ``SearchIndex``).
The Protocol means we have no import-time dependency on ``BuildCtx``;
any object with the right attributes will do.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from .articles import normalize_slug
from .sections import output_path_from_pattern


class SiteModelCtx(Protocol):
    """
    Structural view of the bits of build context the models need.

    Declared as read-only properties so the protocol is satisfied by
    frozen-dataclass implementations (e.g. :class:`BuildCtx`) without
    static-type warnings about writability.
    """
    @property
    def base_url(self) -> str:
        ...
    @property
    def languages(self) -> list:
        ...
    @property
    def per_page(self) -> int:
        ...
    @property
    def rss_items(self) -> int:
        ...
    @property
    def url_patterns(self) -> dict:
        ...


# ------------------------------------------------------------
# Typed page models
# ------------------------------------------------------------

@dataclass(frozen=True)
class IndexPage:
    lang: str
    page: int
    total_pages: int
    articles: list
    output_path: Path
    url: str


@dataclass(frozen=True)
class TagPage:
    lang: str
    tag: str
    tag_slug: str
    articles: list
    output_path: Path
    url: str


@dataclass(frozen=True)
class RssFeed:
    articles: list
    output_path: Path
    url: str


@dataclass(frozen=True)
class Sitemap:
    urls: list
    output_path: Path
    url: str


@dataclass(frozen=True)
class SearchIndex:
    items: list
    output_path: Path


# ------------------------------------------------------------
# URL helpers
# ------------------------------------------------------------

def build_rel_path_from_pattern(pattern: str, **kwargs) -> Path:
    """Resolve a URL pattern into a relative ``…/index.html`` path."""
    return output_path_from_pattern("articles", pattern, **kwargs)


def build_output_path_from_pattern(section: str, pattern: str, **kwargs) -> Path:
    """Resolve a section URL pattern into its relative output path."""
    return output_path_from_pattern(section, pattern, **kwargs)


def build_url_from_pattern(base_url: str, pattern: str, **kwargs) -> str:
    """Resolve a URL pattern into an absolute URL."""
    rel = pattern.format(**kwargs).lstrip("/")
    return f"{base_url.rstrip('/')}/{rel}"


# ------------------------------------------------------------
# Model builders
# ------------------------------------------------------------

def build_index_models(
    lang_articles, lang: str, ctx: SiteModelCtx,
) -> list[IndexPage]:
    """
    Paginate one language's already-sorted article list.

    Caller is responsible for filtering articles to ``lang`` and
    sorting by datetime (newest first); this function only paginates.
    """
    pattern = ctx.url_patterns["index"]
    total = len(lang_articles)
    if total == 0:
        return []
    num_pages = (total + ctx.per_page - 1) // ctx.per_page
    pages: list[IndexPage] = []
    for page in range(1, num_pages + 1):
        start = (page - 1) * ctx.per_page
        end = start + ctx.per_page
        pages.append(IndexPage(
            lang=lang,
            page=page,
            total_pages=num_pages,
            articles=lang_articles[start:end],
            output_path=build_output_path_from_pattern(
                "index", pattern, lang=lang, page=page,
            ),
            url=build_url_from_pattern(
                ctx.base_url, pattern, lang=lang, page=page,
            ),
        ))
    return pages


def build_tags_models(
    lang_articles, lang: str, ctx: SiteModelCtx,
) -> list[TagPage]:
    """
    Build tag pages for one language. Tag values are slugified for
    filesystem paths and URL-encoded for URLs.
    """
    pattern = ctx.url_patterns["tag"]
    tag_map: dict = {}
    for art in lang_articles:
        for tag in art.tags:
            tag_map.setdefault(tag, []).append(art)

    models: list[TagPage] = []
    for tag, items in tag_map.items():
        tag_slug = normalize_slug(tag)
        if not tag_slug:
            logging.warning(
                f"Tag {tag!r} slugifies to empty string — skipping"
            )
            continue
        url_tag = quote(tag_slug, safe="")
        models.append(TagPage(
            lang=lang,
            tag=tag,
            tag_slug=tag_slug,
            articles=items,
            output_path=build_output_path_from_pattern(
                "tags", pattern, lang=lang, tag=tag_slug,
            ),
            url=build_url_from_pattern(
                ctx.base_url, pattern, lang=lang, tag=url_tag,
            ),
        ))
    return models


def build_rss_model(articles, ctx: SiteModelCtx) -> RssFeed:
    """
    Build RSS feed model. ``articles`` is expected to be the already
    selected top-N (newest first); the pipeline builds it via a
    streaming heap so no full-list sort is required.
    """
    pattern = ctx.url_patterns["rss"]
    return RssFeed(
        articles=list(articles[:ctx.rss_items]),
        output_path=build_output_path_from_pattern("rss", pattern),
        url=build_url_from_pattern(ctx.base_url, pattern),
    )


def build_sitemap_model(urls, ctx: SiteModelCtx) -> Sitemap:
    """
    Build sitemap model from a list of URL strings.

    The pipeline accumulates these incrementally during its phase-1
    streaming pass, so we never hold the full Article set just to
    project the URL field.
    """
    pattern = ctx.url_patterns["sitemap"]
    return Sitemap(
        urls=list(urls),
        output_path=build_output_path_from_pattern("sitemap", pattern),
        url=build_url_from_pattern(ctx.base_url, pattern),
    )


def build_search_model(items, ctx: SiteModelCtx) -> SearchIndex:
    """
    Build search index model from a list of pre-projected dicts
    (``{title, description, url, tags}``).

    Output is handled by the configured search XSLT; no canonical URL
    field is attached since there is no shape-preserving place to put it.
    """
    pattern = ctx.url_patterns["search"]
    return SearchIndex(
        items=list(items),
        output_path=build_output_path_from_pattern("search", pattern),
    )
