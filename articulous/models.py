"""
Per-section model builders + URL helpers.

A "model" is the abstract per-page input that the section builder
will later serialise into a temp XML file and feed to its XSLT
stylesheet (or, in the case of search, directly to JSON).

Every builder here takes a :class:`articulous.build.BuildCtx` and
returns plain dicts so the build layer can paginate, hash, and
schedule them without caring about the underlying config dict.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from .articles import normalize_slug

if TYPE_CHECKING:
    from .build import BuildCtx


def build_rel_path_from_pattern(pattern: str, **kwargs) -> Path:
    """Resolve a URL pattern into a relative ``…/index.html`` path."""
    url = pattern.format(**kwargs).strip("/")
    return Path(url) / "index.html"


def build_url_from_pattern(base_url: str, pattern: str, **kwargs) -> str:
    """Resolve a URL pattern into an absolute URL."""
    rel = pattern.format(**kwargs).lstrip("/")
    return f"{base_url.rstrip('/')}/{rel}"


def build_index_models(articles, ctx: "BuildCtx"):
    """Build paginated index models, one set per configured language."""
    pattern = ctx.url_patterns["index"]

    pages = []
    for lang in ctx.languages:
        lang_articles = [a for a in articles if a["lang"] == lang]
        total = len(lang_articles)
        if total == 0:
            continue
        num_pages = (total + ctx.per_page - 1) // ctx.per_page
        for page in range(1, num_pages + 1):
            start = (page - 1) * ctx.per_page
            end = start + ctx.per_page
            subset = lang_articles[start:end]
            pages.append({
                "lang": lang,
                "page": page,
                "total_pages": num_pages,
                "articles": subset,
                "output_path": build_rel_path_from_pattern(
                    pattern, lang=lang, page=page,
                ),
                "url": build_url_from_pattern(
                    ctx.base_url, pattern, lang=lang, page=page,
                ),
            })
    return pages


def build_tags_models(articles, ctx: "BuildCtx"):
    """
    Build tag pages: one page per (language, tag) pair. Tag values are
    slugified for filesystem paths and URL-encoded for URLs.
    """
    pattern = ctx.url_patterns["tag"]

    models = []
    for lang in ctx.languages:
        lang_articles = [a for a in articles if a["lang"] == lang]
        tag_map = {}
        for art in lang_articles:
            for tag in art.get("tags", []):
                tag_map.setdefault(tag, []).append(art)

        for tag, items in tag_map.items():
            tag_slug = normalize_slug(tag)
            if not tag_slug:
                logging.warning(
                    f"Tag {tag!r} slugifies to empty string — skipping"
                )
                continue
            url_tag = quote(tag_slug, safe="")
            models.append({
                "lang": lang,
                "tag": tag,
                "tag_slug": tag_slug,
                "articles": items,
                "output_path": build_rel_path_from_pattern(
                    pattern, lang=lang, tag=tag_slug,
                ),
                "url": build_url_from_pattern(
                    ctx.base_url, pattern, lang=lang, tag=url_tag,
                ),
            })
    return models


def build_rss_model(articles, ctx: "BuildCtx"):
    """Build RSS feed model."""
    pattern = ctx.url_patterns["rss"]
    return {
        "articles": articles[:ctx.rss_items],
        "output_path": Path(pattern.lstrip("/")),
        "url": build_url_from_pattern(ctx.base_url, pattern),
    }


def build_sitemap_model(articles, ctx: "BuildCtx"):
    """Build sitemap model."""
    pattern = ctx.url_patterns["sitemap"]
    return {
        "urls": [art["url"] for art in articles],
        "output_path": Path(pattern.lstrip("/")),
        "url": build_url_from_pattern(ctx.base_url, pattern),
    }


def build_search_model(articles, ctx: "BuildCtx"):
    """Build search index model."""
    pattern = ctx.url_patterns["search"]
    items = [
        {
            "title": art["title"],
            "description": art["description"],
            "url": art["url"],
            "tags": art["tags"],
        }
        for art in articles
    ]
    return {
        "items": items,
        "output_path": Path(pattern.lstrip("/")),
        "url": build_url_from_pattern(ctx.base_url, pattern),
    }
