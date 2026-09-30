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
from itertools import islice
from pathlib import Path
import sys
from typing import Iterator, Protocol
from urllib.parse import quote
from xml.etree.ElementTree import Element, SubElement, tostring

from .articles import normalize_slug
from .sections import bare_pattern, output_path_from_pattern, url_key_for_section, validate_index_first_pattern


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
    @property
    def default_language(self) -> str:
        ...
    @property
    def bare_default_language(self) -> tuple:
        ...


# ------------------------------------------------------------
# Typed page models
# ------------------------------------------------------------

@dataclass(frozen=True)
class IndexOptions:
    first_pattern: str | None = None
    include_empty: bool = False

    def __post_init__(self):
        if self.first_pattern is not None:
            validate_index_first_pattern(self.first_pattern)
        if not isinstance(self.include_empty, bool):
            raise ValueError('include_empty must be a boolean')


@dataclass(frozen=True)
class IndexPage:
    lang: str
    page: int
    total_pages: int
    articles: list
    output_path: Path
    url: str
    previous_url: str = ""
    next_url: str = ""


@dataclass(frozen=True)
class TagPage:
    lang: str
    tag: str
    tag_slug: str
    articles: list
    output_path: Path
    url: str
    page: int = 1
    total_pages: int = 1
    previous_url: str = ""
    next_url: str = ""


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


@dataclass(frozen=True)
class TagSummary:
    tag: str
    slug: str
    count: int
    url: str


@dataclass(frozen=True)
class TagIndex:
    lang: str
    tags: tuple[TagSummary, ...]

    def to_xml(self) -> bytes:
        root = Element('tag-index', lang=self.lang)
        for tag in self.tags:
            SubElement(root, 'tag', slug=tag.slug, count=str(tag.count), url=tag.url).text = tag.tag
        return tostring(root, encoding='utf-8')


# ------------------------------------------------------------
# URL helpers
# ------------------------------------------------------------

def build_output_path_from_pattern(section: str, pattern: str, **kwargs) -> Path:
    """Resolve a section URL pattern into its relative output path."""
    return output_path_from_pattern(section, pattern, **kwargs)


def section_pattern(ctx: SiteModelCtx, section: str, lang: str | None) -> str:
    """The URL pattern for ``section`` as it applies to ``lang``.

    With ``site.bare_default_language`` naming the section, the default
    language drops its ``/{lang}/`` segment, so it owns the bare routes the
    way a site's untranslated pages usually do. API contexts predate the
    setting and may not carry it; they keep the configured pattern.
    """
    pattern = ctx.url_patterns[url_key_for_section(section)]
    bare = section in getattr(ctx, "bare_default_language", ())
    if bare and lang is not None and lang == getattr(ctx, "default_language", None):
        return bare_pattern(pattern)
    return pattern


def build_url_from_pattern(base_url: str, pattern: str, **kwargs) -> str:
    """Join the formatted pattern to base_url; an empty base gives a root-relative URL."""
    rel = pattern.format(**kwargs).lstrip("/")
    return f"{base_url.rstrip('/')}/{quote(rel, safe='/')}"


# ------------------------------------------------------------
# Model builders
# ------------------------------------------------------------

def _page_batches(articles, per_page: int):
    iterator = iter(articles)
    while batch := list(islice(iterator, min(per_page, sys.maxsize))):
        yield batch


def _index_pattern(page, lang, ctx, options):
    if page != 1 or options.first_pattern is None:
        return section_pattern(ctx, 'index', lang)
    pattern = options.first_pattern
    if 'index' in getattr(ctx, 'bare_default_language', ()) and lang == ctx.default_language:
        return bare_pattern(pattern)
    return pattern


def _index_url(page: int, total: int, lang: str, ctx: SiteModelCtx, options: IndexOptions) -> str:
    if not 1 <= page <= total:
        return ""
    return build_url_from_pattern(ctx.base_url, _index_pattern(page, lang, ctx, options), lang=lang, page=page)


def _index_options(ctx, lang, options):
    options = getattr(ctx, 'index_options', IndexOptions()) if options is None else options
    if not isinstance(options, IndexOptions):
        raise ValueError('options must be IndexOptions')
    if type(ctx.per_page) is not int or ctx.per_page < 1:
        raise ValueError('per_page must be a positive integer')
    if lang not in ctx.languages:
        raise ValueError('index language must be enabled')
    return options


def build_index_models(
    lang_articles, lang: str, ctx: SiteModelCtx, *, options: IndexOptions | None = None,
) -> Iterator[IndexPage]:
    """
    Paginate one language's already-sorted article list.

    Caller is responsible for filtering articles to ``lang`` and
    sorting by datetime (newest first); this function only paginates.
    """
    options = _index_options(ctx, lang, options)
    total = len(lang_articles)
    if total == 0 and not options.include_empty:
        return
    num_pages = max(1, (total + ctx.per_page - 1) // ctx.per_page)
    batches = _page_batches(lang_articles, ctx.per_page) if total else iter([[]])
    for page, articles in enumerate(
        batches, start=1,
    ):
        yield IndexPage(
            lang=lang,
            page=page,
            total_pages=num_pages,
            articles=articles,
            output_path=build_output_path_from_pattern(
                "index", _index_pattern(page, lang, ctx, options), lang=lang, page=page,
            ),
            url=_index_url(page, num_pages, lang, ctx, options),
            previous_url=_index_url(page - 1, num_pages, lang, ctx, options),
            next_url=_index_url(page + 1, num_pages, lang, ctx, options),
        )


def _tag_page_pattern(pattern: str, page: int) -> str:
    return pattern if page == 1 else f"{pattern.rstrip('/')}/page/{page}/"


def _tag_url(page, total, pattern, lang, tag_slug, ctx):
    if not 1 <= page <= total:
        return ""
    return build_url_from_pattern(
        ctx.base_url, _tag_page_pattern(pattern, page), lang=lang, tag=tag_slug,
    )


def _tag_pages(tag, items, lang, ctx, paginate):
    tag_slug = normalize_slug(tag)
    if not tag_slug:
        logging.warning(f"Tag {tag!r} slugifies to empty string — skipping")
        return
    size = ctx.per_page if paginate else len(items)
    total = (len(items) + size - 1) // size
    pattern = section_pattern(ctx, "tags", lang)
    for number, batch in enumerate(_page_batches(items, size), 1):
        yield TagPage(
            lang=lang, tag=tag, tag_slug=tag_slug, articles=batch,
            output_path=build_output_path_from_pattern(
                "tags", _tag_page_pattern(pattern, number), lang=lang, tag=tag_slug,
            ),
            url=_tag_url(number, total, pattern, lang, tag_slug, ctx),
            page=number, total_pages=total,
            previous_url=_tag_url(number - 1, total, pattern, lang, tag_slug, ctx),
            next_url=_tag_url(number + 1, total, pattern, lang, tag_slug, ctx),
        )


def build_tags_models(
    lang_articles, lang: str, ctx: SiteModelCtx, *, paginate: bool = False,
) -> list[TagPage]:
    """Group already-sorted, publication-filtered articles by tag.

    Opt-in pagination uses ``ctx.per_page``. Page one keeps the configured
    tag route; subsequent pages append ``page/N/``. API callers can supply
    a global tag pattern without ``{lang}`` and an empty language.
    """
    if not isinstance(paginate, bool):
        raise ValueError("paginate must be a boolean")
    tag_map: dict = {}
    for art in lang_articles:
        for tag in dict.fromkeys(art.tags):
            tag_map.setdefault(tag, []).append(art)
    models: list[TagPage] = []
    for tag, items in tag_map.items():
        models.extend(_tag_pages(tag, items, lang, ctx, paginate))
    return models


def build_rss_model(articles, ctx: SiteModelCtx, lang: str | None = None) -> RssFeed:
    """
    Build RSS feed model. ``articles`` is expected to be the already
    selected top-N (newest first); the pipeline builds it via a
    streaming heap so no full-list sort is required. ``lang`` is supplied
    when ``urls.rss`` names ``{lang}`` and the site publishes one feed per
    language.
    """
    pattern = section_pattern(ctx, "rss", lang)
    fields = {"lang": lang} if lang is not None else {}
    return RssFeed(
        articles=list(articles[:ctx.rss_items]),
        output_path=build_output_path_from_pattern("rss", pattern, **fields),
        url=build_url_from_pattern(ctx.base_url, pattern, **fields),
    )


def build_tag_index_model(articles, lang: str, ctx: SiteModelCtx) -> TagIndex:
    tags = {}
    for page in build_tags_models(articles, lang, ctx):
        if page.tag_slug in tags:
            raise ValueError(f'Duplicate tag slug: {page.tag_slug}')
        tags[page.tag_slug] = TagSummary(page.tag, page.tag_slug, len(page.articles), page.url)
    return TagIndex(lang, tuple(tags.values()))


def build_sitemap_model(urls, ctx: SiteModelCtx) -> Sitemap:
    """
    Build sitemap metadata and materialize the supplied URL iterable.
    Streaming section builders pass an empty iterable for metadata and
    consume their URL sink separately.
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

    Output is handled by the configured search engine; no canonical URL
    field is attached since there is no shape-preserving place to put it.
    """
    pattern = ctx.url_patterns["search"]
    return SearchIndex(
        items=list(items),
        output_path=build_output_path_from_pattern("search", pattern),
    )
