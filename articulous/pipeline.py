"""
Build pipeline: typed BuildCtx, section builders, and the
:func:`run_build` orchestrator.

This layer composes :mod:`articulous.runtime` (cache, parallel, file
I/O) and :mod:`articulous.engines` (transform strategies) into the
end-to-end build. Section builders here are intentionally thin: they
synthesise per-section model XML and hand it to the shared
:func:`_make_xslt_task` plumbing.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from xml.sax.saxutils import escape as _xml_escape, quoteattr as _xml_attr

from .articles import iter_articles
from .engines import (
    SECTION_XSL,
    SaxonCEngine,
    TransformEngine,
    configure_saxonc,
    make_engine,
    validate_engines,
)
from .models import (
    build_index_models,
    build_rel_path_from_pattern,
    build_rss_model,
    build_search_model,
    build_sitemap_model,
    build_tags_models,
    build_url_from_pattern,
)
from .runtime import (
    WorkerCount,
    file_hash,
    load_cache,
    run_parallel_tasks,
    save_cache,
    should_rebuild,
    timed,
    update_cache,
)


_ASSET_CACHE_KEY = "assets"
_OUTPUT_MANIFEST_KEY = "__outputs__"


# ================================================================
# Build context
# ================================================================

@dataclass(frozen=True)
class BuildCtx:
    """
    Typed projection of the inputs each build step needs.

    Section / model builders consume ``BuildCtx`` fields and never read
    the raw config dict. :func:`build_ctx_from_config` is the only
    place that knows the config dict's deep shape.
    """
    # paths
    content_dir: Path
    xsl_dir: Path
    output_dir: Path
    assets_dir: Path
    # build flags
    force: bool = False
    dry_run: bool = False
    parallelism: WorkerCount = "auto"
    cache_file: str = ".build-cache.json"
    # engine map: section name -> TransformEngine
    engines: dict = field(default_factory=dict)
    # site / URL model
    site_name: str = ""
    base_url: str = ""
    languages: list = field(default_factory=list)
    default_language: str = "en"
    url_patterns: dict = field(default_factory=dict)
    per_page: int = 10
    rss_items: int = 20

    def xsl_for(self, section: str) -> Path:
        return self.xsl_dir / "pages" / SECTION_XSL[section]

    def engine_for(self, section: str) -> TransformEngine:
        return self.engines[section]


def _require_positive_int(value, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(
            f"config {name} must be a positive int, got {value!r}"
        )
    return value


def _require_non_negative_int(value, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(
            f"config {name} must be a non-negative int, got {value!r}"
        )
    return value


def _require_worker_count(value) -> WorkerCount:
    if value == "auto":
        return value
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(
            f"config build.parallelism must be 'auto' or a positive int, got {value!r}"
        )
    return value


def build_ctx_from_config(config: dict, dry_run: bool) -> BuildCtx:
    """
    Project the raw config dict into a :class:`BuildCtx`.

    This is the only function in the package that reads the raw config
    dict's deep shape. It also validates the configured engine names
    and resolves the SaxonC binary, so callers downstream see only a
    typed ctx — no config dict, no string-compared engine names.

    Integer fields that the pipeline divides or slices by
    (``per_page``, ``rss_items``) are bounds-checked here so a malformed
    value fails loudly at startup instead of producing a
    ``ZeroDivisionError`` (per_page == 0) or empty-heap ``IndexError``
    (rss_items < 0) deep inside the build.
    """
    validate_engines(config)
    saxonc_bin = configure_saxonc(config)
    engines = {
        section: make_engine(name, saxonc_bin)
        for section, name in config["engines"].items()
    }
    pagination = config["site"]["pagination"]
    per_page = _require_positive_int(
        pagination["per_page"], "site.pagination.per_page",
    )
    rss_items = _require_non_negative_int(
        pagination["rss_items"], "site.pagination.rss_items",
    )
    parallelism = _require_worker_count(config["build"]["parallelism"])
    return BuildCtx(
        content_dir=Path(config["paths"]["content_dir"]),
        xsl_dir=Path(config["paths"]["xsl_dir"]),
        output_dir=Path(config["paths"]["output_dir"]),
        assets_dir=Path(config["paths"]["assets_dir"]),
        force=config["build"]["force_full_build"],
        dry_run=dry_run,
        parallelism=parallelism,
        # Reduce user-controlled value to a bare filename; the path
        # prefix is added in _cache_path_for to prevent traversal.
        cache_file=Path(config["build"]["cache_file"]).name,
        engines=engines,
        site_name=config["site"]["site_name"],
        base_url=config["site"]["base_url"],
        languages=list(config["site"]["languages"]),
        default_language=config["site"]["default_language"],
        url_patterns=dict(config["urls"]),
        per_page=per_page,
        rss_items=rss_items,
    )


# ================================================================
# Asset + URL helpers
# ================================================================

def _safe_output_path(ctx: BuildCtx, output_path: Path) -> Path:
    root = ctx.output_dir.resolve()
    candidate = output_path if output_path.is_absolute() else ctx.output_dir / output_path
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(
            f"Generated output path escapes output_dir: {output_path} "
            f"(output_dir={ctx.output_dir})"
        )
    return resolved


def _output_relpath(ctx: BuildCtx, output_path: Path) -> str:
    return _safe_output_path(ctx, output_path).relative_to(
        ctx.output_dir.resolve()
    ).as_posix()


def _assert_non_overlapping_trees(src: Path, dest: Path) -> None:
    src_resolved = src.resolve()
    dest_resolved = dest.resolve()
    overlaps = (
        src_resolved == dest_resolved
        or src_resolved.is_relative_to(dest_resolved)
        or dest_resolved.is_relative_to(src_resolved)
    )
    if overlaps:
        raise ValueError(
            f"assets_dir and output assets directory overlap: "
            f"{src_resolved} <-> {dest_resolved}"
        )


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            h.update(f"D\0{rel}\0".encode("utf-8"))
        else:
            h.update(f"F\0{rel}\0".encode("utf-8"))
            h.update(file_hash(path).encode("ascii"))
    return h.hexdigest()


def copy_assets(ctx: BuildCtx, cache: Optional[dict] = None) -> None:
    """
    Mirror ``ctx.assets_dir`` into ``<output_dir>/assets``.
    No-op if the source is missing; honours dry-run.
    """
    if not ctx.assets_dir.exists():
        logging.debug(f"Assets directory not present, skipping: {ctx.assets_dir}")
        return

    dest = _safe_output_path(ctx, ctx.output_dir / "assets")
    _assert_non_overlapping_trees(ctx.assets_dir, dest)
    assets_hash = _tree_hash(ctx.assets_dir)

    if ctx.dry_run:
        logging.debug(f"[DRY RUN] Would copy assets: {ctx.assets_dir} -> {dest}")
        return

    if cache is not None and not should_rebuild(
        _ASSET_CACHE_KEY, cache, (assets_hash,), ctx.force, output_path=dest,
    ):
        logging.debug("Skipping unchanged assets")
        return

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ctx.assets_dir, dest)
    if cache is not None:
        update_cache(cache, _ASSET_CACHE_KEY, (assets_hash,))
    logging.info(f"Copied assets: {ctx.assets_dir} -> {dest}")


def _article_url_builder(ctx: BuildCtx):
    """
    Return a ``(lang, slug) -> url`` callable bound to ``ctx``. Used by
    :func:`iter_articles` so each :class:`Article` is constructed with
    its public URL already attached.
    """
    pattern = ctx.url_patterns["article"]
    base_url = ctx.base_url

    def build(lang: str, slug: str) -> str:
        return build_url_from_pattern(base_url, pattern, lang=lang, slug=slug)

    return build


# ================================================================
# XML synthesis helpers
# ================================================================

def _xml_doc(root_tag: str, children: list, attrs: str = "") -> str:
    return f"<{root_tag}{attrs}>{''.join(children)}</{root_tag}>"


def _article_xml(a) -> str:
    return (
        f"<article><title>{_xml_escape(a.title)}</title>"
        f"<url>{_xml_escape(a.url)}</url></article>"
    )


def _rss_item_xml(a) -> str:
    return (
        f"<item><title>{_xml_escape(a.title)}</title>"
        f"<url>{_xml_escape(a.url)}</url></item>"
    )


def _sitemap_url_xml(url: str) -> str:
    return f"<url>{_xml_escape(url)}</url>"


def _search_item_xml(item) -> str:
    tags = "".join(f"<tag>{_xml_escape(t)}</tag>" for t in item["tags"])
    return (
        f"<item><title>{_xml_escape(item['title'])}</title>"
        f"<description>{_xml_escape(item['description'])}</description>"
        f"<url>{_xml_escape(item['url'])}</url>"
        f"<tags>{tags}</tags></item>"
    )


# Per-section root-element synthesisers. Each one folds the page-model
# metadata (canonical URL, pagination counters, display name) into the
# XML attributes / children so XSL templates can render headers,
# `<link rel="canonical">`, "page N of M", etc. Without these helpers
# the model fields would be computed and discarded.
def _index_doc(page, site_name: str) -> str:
    attrs = (
        f" site={_xml_attr(site_name)} "
        f"lang={_xml_attr(page.lang)} "
        f'page="{page.page}" total="{page.total_pages}" '
        f"self={_xml_attr(page.url)}"
    )
    return _xml_doc(
        "index", [_article_xml(a) for a in page.articles], attrs,
    )


def _tag_doc(page, site_name: str) -> str:
    attrs = (
        f" site={_xml_attr(site_name)} "
        f"lang={_xml_attr(page.lang)} "
        f"slug={_xml_attr(page.tag_slug)} "
        f"self={_xml_attr(page.url)}"
    )
    children = [f"<display-name>{_xml_escape(page.tag)}</display-name>"]
    children.extend(_article_xml(a) for a in page.articles)
    return _xml_doc("tag", children, attrs)


def _rss_doc(feed, site_name: str) -> str:
    attrs = f" site={_xml_attr(site_name)} self={_xml_attr(feed.url)}"
    return _xml_doc(
        "rss", [_rss_item_xml(a) for a in feed.articles], attrs,
    )


def _sitemap_doc(sitemap, site_name: str) -> str:
    attrs = f" site={_xml_attr(site_name)} self={_xml_attr(sitemap.url)}"
    return _xml_doc(
        "sitemap", [_sitemap_url_xml(u) for u in sitemap.urls], attrs,
    )


def _search_doc(index, site_name: str) -> str:
    attrs = f" site={_xml_attr(site_name)}"
    json_text = json.dumps(index.items, indent=2)
    children = [f"<json>{_xml_escape(json_text)}</json>"]
    children.extend(_search_item_xml(item) for item in index.items)
    return _xml_doc("search", children, attrs)


# ================================================================
# Shared XSLT task plumbing
# ================================================================

def _find_output_owner(manifest: dict, relpath: str) -> Optional[str]:
    for key, value in manifest.items():
        if value == relpath:
            return key
    return None


def _record_planned_output(
    manifest: Optional[dict],
    ctx: BuildCtx,
    cache_key: str,
    output_path: Path,
) -> Path:
    output_path = _safe_output_path(ctx, output_path)
    if manifest is None:
        return output_path
    relpath = _output_relpath(ctx, output_path)
    if cache_key in manifest:
        raise ValueError(f"Duplicate generated cache key: {cache_key}")
    owner = _find_output_owner(manifest, relpath)
    if owner is not None:
        raise ValueError(
            f"Duplicate generated output path: {relpath} "
            f"for {owner!r} and {cache_key!r}"
        )
    manifest[cache_key] = relpath
    return output_path

def _make_xslt_task(
    *,
    xml_input,            # Path on disk (article XML) or bytes (in-memory model)
    xsl_path: Path,
    xsl_hash: str,        # PERF-01: caller hashes the section's XSL once
    output_path: Path,
    cache: dict,
    cache_key: str,
    engine: TransformEngine,
    ctx: BuildCtx,
    manifest: Optional[dict] = None,
) -> Optional[Callable]:
    """
    Return a transform task for an XSLT-driven section, or ``None`` if
    the cache says the output is up to date.

    ``xml_input`` is either a :class:`Path` (article XML on disk) or
    :class:`bytes` (a freshly-synthesised model XML). In the bytes case
    we hash the buffer directly — PERF-02 — instead of writing it to
    a temp file just so :func:`file_hash` can read it back.

    ``xsl_hash`` is precomputed by the caller so per-section XSL hashing
    is amortised across every page in that section.

    The cache entry is committed *inside* the returned task, after a
    successful transform — failed transforms leave the prior cache
    entry intact.
    """
    output_path = _record_planned_output(manifest, ctx, cache_key, output_path)
    if isinstance(xml_input, bytes):
        xml_hash = hashlib.sha256(xml_input).hexdigest()
    else:
        xml_hash = file_hash(xml_input)

    if not should_rebuild(
        cache_key, cache, (xml_hash, xsl_hash), ctx.force, output_path=output_path,
    ):
        return None
    hashes = (xml_hash, xsl_hash)

    def task(xml_input=xml_input, xsl_path=xsl_path, output_path=output_path):
        engine.run(xml_input, xsl_path, output_path, dry_run=ctx.dry_run)
        update_cache(cache, cache_key, hashes)

    return timed(cache_key, task)


# ================================================================
# Section builders
# ================================================================

def _encode_xml(content: str) -> bytes:
    return content.encode("utf-8")


def build_articles_section(lang_articles, ctx: BuildCtx, cache, manifest=None):
    """
    Build article pages for one language's article batch.

    Called once per language by :func:`run_build`; the input is a
    per-language sorted list, not the global article set.
    """
    tasks = []
    xsl_path = ctx.xsl_for("articles")
    engine = ctx.engine_for("articles")
    pattern = ctx.url_patterns["article"]
    xsl_hash = file_hash(xsl_path)  # PERF-01: once per section, not per item

    for art in lang_articles:
        output_path = ctx.output_dir / build_rel_path_from_pattern(
            pattern, lang=art.lang, slug=art.slug,
        )
        task = _make_xslt_task(
            xml_input=art.source_path,
            xsl_path=xsl_path,
            xsl_hash=xsl_hash,
            output_path=output_path,
            cache=cache,
            cache_key=f"article:{art.lang}:{art.slug}",
            engine=engine,
            ctx=ctx,
            manifest=manifest,
        )
        if task is None:
            logging.debug(f"Skipping unchanged article: {art.slug}")
            continue
        tasks.append(task)

    return tasks


def build_index_section(lang_articles, lang: str, ctx: BuildCtx, cache, manifest=None):
    """Build paginated index pages for one language."""
    tasks = []
    xsl_path = ctx.xsl_for("index")
    engine = ctx.engine_for("index")
    xsl_hash = file_hash(xsl_path)

    for page in build_index_models(lang_articles, lang, ctx):
        xml_bytes = _encode_xml(_index_doc(page, ctx.site_name))
        task = _make_xslt_task(
            xml_input=xml_bytes,
            xsl_path=xsl_path,
            xsl_hash=xsl_hash,
            output_path=ctx.output_dir / page.output_path,
            cache=cache,
            cache_key=f"index:{page.lang}:{page.page}",
            engine=engine,
            ctx=ctx,
            manifest=manifest,
        )
        if task is None:
            logging.debug(f"Skipping unchanged index page {page.page}")
            continue
        tasks.append(task)

    return tasks


def build_tags_section(lang_articles, lang: str, ctx: BuildCtx, cache, manifest=None):
    """Build tag pages for one language."""
    tasks = []
    xsl_path = ctx.xsl_for("tags")
    engine = ctx.engine_for("tags")
    xsl_hash = file_hash(xsl_path)

    for page in build_tags_models(lang_articles, lang, ctx):
        xml_bytes = _encode_xml(_tag_doc(page, ctx.site_name))
        task = _make_xslt_task(
            xml_input=xml_bytes,
            xsl_path=xsl_path,
            xsl_hash=xsl_hash,
            output_path=ctx.output_dir / page.output_path,
            cache=cache,
            cache_key=f"tag:{page.lang}:{page.tag_slug}",
            engine=engine,
            ctx=ctx,
            manifest=manifest,
        )
        if task is None:
            logging.debug(
                f"Skipping unchanged tag page: {page.lang}/{page.tag_slug}"
            )
            continue
        tasks.append(task)

    return tasks


def build_rss_section(rss_articles, ctx: BuildCtx, cache, manifest=None):
    """
    Build the RSS feed. ``rss_articles`` is the already-selected top-N
    list (newest first) produced by :func:`_stream_projections`.
    """
    feed = build_rss_model(rss_articles, ctx)
    xsl_path = ctx.xsl_for("rss")
    xml_bytes = _encode_xml(_rss_doc(feed, ctx.site_name))
    task = _make_xslt_task(
        xml_input=xml_bytes,
        xsl_path=xsl_path,
        xsl_hash=file_hash(xsl_path),
        output_path=ctx.output_dir / feed.output_path,
        cache=cache,
        cache_key="rss",
        engine=ctx.engine_for("rss"),
        ctx=ctx,
        manifest=manifest,
    )
    if task is None:
        logging.debug("Skipping unchanged RSS feed")
        return []
    return [task]


def build_sitemap_section(urls, ctx: BuildCtx, cache, manifest=None):
    """Build sitemap.xml from a streamed list of URL strings."""
    sitemap = build_sitemap_model(urls, ctx)
    xsl_path = ctx.xsl_for("sitemap")
    xml_bytes = _encode_xml(_sitemap_doc(sitemap, ctx.site_name))
    task = _make_xslt_task(
        xml_input=xml_bytes,
        xsl_path=xsl_path,
        xsl_hash=file_hash(xsl_path),
        output_path=ctx.output_dir / sitemap.output_path,
        cache=cache,
        cache_key="sitemap",
        engine=ctx.engine_for("sitemap"),
        ctx=ctx,
        manifest=manifest,
    )
    if task is None:
        logging.debug("Skipping unchanged sitemap")
        return []
    return [task]


def build_search_section(items, ctx: BuildCtx, cache, manifest=None):
    """Build search.json through the configured search XSLT engine."""
    index = build_search_model(items, ctx)
    xsl_path = ctx.xsl_for("search")
    xml_bytes = _encode_xml(_search_doc(index, ctx.site_name))
    task = _make_xslt_task(
        xml_input=xml_bytes,
        xsl_path=xsl_path,
        xsl_hash=file_hash(xsl_path),
        output_path=ctx.output_dir / index.output_path,
        cache=cache,
        cache_key="search",
        engine=ctx.engine_for("search"),
        ctx=ctx,
        manifest=manifest,
    )
    if task is None:
        logging.debug("Skipping unchanged search index")
        return []
    return [task]


# ================================================================
# Streaming dispatch
# ================================================================

# Section name -> "per-lang" vs "cross-lang" classification. Per-lang
# builders are called once per configured language with that language's
# sorted article batch; cross-lang builders are called once with a
# streaming projection built during phase 1.
_PER_LANG_SECTIONS = ("articles", "index", "tags")
_CROSS_LANG_SECTIONS = ("rss", "sitemap", "search")

# Exposed for tests / documentation: the complete section name set.
SECTION_NAMES = _PER_LANG_SECTIONS + _CROSS_LANG_SECTIONS


@dataclass
class StreamProjection:
    sitemap_urls: list
    search_items: list
    rss_heap: list
    total: int
    articles_by_lang: dict = field(default_factory=dict)


def _passes_cli_filters(art, cli) -> bool:
    if cli.only_langs and art.lang not in cli.only_langs:
        return False
    if cli.only_slugs and art.slug not in cli.only_slugs:
        return False
    return True


def _stream_projections(
    stream_factory,
    cli,
    ctx: BuildCtx,
    *,
    collect_cross: bool = True,
    collect_articles: bool = False,
) -> StreamProjection:
    """
    Single filtered article pass.

    Cross-language sections use projected lists/heaps; per-language
    sections reuse ``articles_by_lang`` so the XML tree is not reparsed
    once for every configured language.
    """
    projection = StreamProjection([], [], [], 0)
    seq = 0  # monotonic tie-breaker for the heap
    for art in stream_factory():
        if not _passes_cli_filters(art, cli):
            continue
        projection.total += 1
        if collect_articles:
            projection.articles_by_lang.setdefault(art.lang, []).append(art)
        if collect_cross:
            _add_cross_projection(projection, art)
        if collect_cross and ctx.rss_items > 0:
            entry = (art.datetime, seq, art)
            seq += 1
            _push_rss_entry(projection.rss_heap, entry, ctx.rss_items)
    return projection


def _add_cross_projection(projection: StreamProjection, art) -> None:
    projection.sitemap_urls.append(art.url)
    projection.search_items.append({
        "title": art.title,
        "description": art.description,
        "url": art.url,
        "tags": list(art.tags),
    })


def _push_rss_entry(rss_heap: list, entry: tuple, limit: int) -> None:
    if len(rss_heap) < limit:
        heapq.heappush(rss_heap, entry)
    elif entry > rss_heap[0]:
        heapq.heapreplace(rss_heap, entry)


def _rss_sorted_from_heap(rss_heap) -> list:
    """Newest-first list extracted from the min-heap."""
    return [art for _, _, art in sorted(rss_heap, reverse=True)]


def _collect_cross_lang_plan(
    projection: StreamProjection, ctx, cache, want, manifest,
) -> dict:
    """Phase-1 streaming pass: cross-language projections (rss / sitemap / search)."""
    logging.info(f"Discovered {projection.total} article(s) after filters")
    plan: dict = {}
    if want("rss"):
        plan["rss"] = build_rss_section(
            _rss_sorted_from_heap(projection.rss_heap), ctx, cache, manifest,
        )
    if want("sitemap"):
        plan["sitemap"] = build_sitemap_section(
            projection.sitemap_urls, ctx, cache, manifest,
        )
    if want("search"):
        plan["search"] = build_search_section(
            projection.search_items, ctx, cache, manifest,
        )
    return plan


def _sorted_lang_articles(articles_by_lang: dict, lang: str) -> list:
    return sorted(articles_by_lang.get(lang, ()), key=lambda a: a.datetime, reverse=True)


def _add_per_lang_tasks(
    plan: dict, lang_articles, lang, ctx, cache, want, manifest,
) -> None:
    if want("articles"):
        plan.setdefault("articles", []).extend(
            build_articles_section(lang_articles, ctx, cache, manifest)
        )
    if want("index"):
        plan.setdefault("index", []).extend(
            build_index_section(lang_articles, lang, ctx, cache, manifest)
        )
    if want("tags"):
        plan.setdefault("tags", []).extend(
            build_tags_section(lang_articles, lang, ctx, cache, manifest)
        )


def _collect_per_lang_plan(
    articles_by_lang, cli, ctx: BuildCtx, cache, want, manifest,
) -> dict:
    """Phase-2 streaming pass: per-language sections (articles / index / tags)."""
    plan: dict = {}
    for lang in ctx.languages:
        if cli.only_langs and lang not in cli.only_langs:
            continue
        lang_articles = _sorted_lang_articles(articles_by_lang, lang)
        if not lang_articles:
            continue
        _add_per_lang_tasks(
            plan, lang_articles, lang, ctx, cache, want, manifest,
        )
        # lang_articles goes out of scope here → released between languages.
    return plan


def _collect_tasks(stream_factory, cli, ctx: BuildCtx, cache, manifest=None) -> dict:
    """
    Stream the article set and dispatch every requested section.

    Returns a ``{section_name: [task, ...]}`` plan ready for parallel
    execution. Memory peak is bounded to a single language's sorted
    article batch plus the three cross-language projections, instead
    of the entire global article list.
    """
    wanted = set(cli.only_sections) if cli.only_sections else None

    def want(section: str) -> bool:
        return wanted is None or section in wanted

    plan: dict = {}
    need_cross = any(want(s) for s in _CROSS_LANG_SECTIONS)
    need_per_lang = any(want(s) for s in _PER_LANG_SECTIONS)
    projection = _stream_projections(
        stream_factory,
        cli,
        ctx,
        collect_cross=need_cross,
        collect_articles=need_per_lang,
    )
    if need_cross:
        plan.update(
            _collect_cross_lang_plan(projection, ctx, cache, want, manifest)
        )
    if need_per_lang:
        plan.update(
            _collect_per_lang_plan(
                projection.articles_by_lang, cli, ctx, cache, want, manifest,
            )
        )
    return plan


def _cache_path_for(ctx: BuildCtx, project_root: Path) -> Path:
    """Resolve the cache file path. ``ctx.cache_file`` is already a bare
    filename (see :func:`build_ctx_from_config`)."""
    return project_root / ctx.cache_file


def _resolve_parallelism(ctx: BuildCtx) -> WorkerCount:
    """
    Pick a sensible ``max_workers`` for ``run_parallel_tasks``.

    For lxml-only builds, oversubscribing is cheap (each task is a
    short C call that releases the GIL), so we stay with the previous
    ``max(4, cpu_count)`` default.

    SaxonC tasks each launch a JVM subprocess; stacking more of those
    than the machine has cores risks running out of memory long before
    it runs out of CPU. When any section is configured to use
    SaxonCEngine, ``"auto"`` resolves to ``cpu_count`` instead.

    Explicit integer/string values in ``ctx.parallelism`` pass through
    unchanged.
    """
    if ctx.parallelism != "auto":
        return ctx.parallelism
    cpu = os.cpu_count() or 4
    has_saxon = any(isinstance(e, SaxonCEngine) for e in ctx.engines.values())
    return cpu if has_saxon else max(4, cpu)


def _load_output_manifest(cache: dict) -> dict:
    manifest = cache.get(_OUTPUT_MANIFEST_KEY)
    if not isinstance(manifest, dict):
        return {}
    return {
        str(key): value
        for key, value in manifest.items()
        if isinstance(value, str)
    }


def _can_prune_outputs(cli) -> bool:
    return not (cli.only_sections or cli.only_langs or cli.only_slugs)


def _manifest_target(ctx: BuildCtx, relpath: str) -> Path:
    rel = Path(relpath)
    if rel.is_absolute():
        raise ValueError(f"Manifest output path must be relative: {relpath}")
    return _safe_output_path(ctx, ctx.output_dir / rel)


def _remove_empty_parents(path: Path, stop: Path) -> None:
    parent = path.parent
    while parent != stop:
        try:
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent


def _delete_output_file(path: Path, root: Path) -> None:
    if not path.exists():
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    _remove_empty_parents(path, root)


def _prune_stale_outputs(
    ctx: BuildCtx,
    cache: dict,
    old_manifest: dict,
    current_manifest: dict,
) -> None:
    stale_keys = sorted(set(old_manifest) - set(current_manifest))
    root = ctx.output_dir.resolve()
    for key in stale_keys:
        try:
            target = _manifest_target(ctx, old_manifest[key])
        except ValueError as e:
            logging.warning(f"Skipping invalid cached output manifest entry: {e}")
        else:
            _delete_output_file(target, root)
        cache.pop(key, None)


def _store_output_manifest(
    cache: dict,
    old_manifest: dict,
    current_manifest: dict,
    replace: bool,
) -> None:
    manifest = current_manifest if replace else {**old_manifest, **current_manifest}
    cache[_OUTPUT_MANIFEST_KEY] = dict(sorted(manifest.items()))


# ================================================================
# Top-level build pipeline
# ================================================================

def run_build(cli, config, project_root: Path) -> None:
    """Orchestrate the entire build process."""
    logging.info("Starting build...")

    ctx = build_ctx_from_config(config, dry_run=cli.dry_run)
    cache_path = _cache_path_for(ctx, project_root)
    cache = load_cache(cache_path)
    old_manifest = _load_output_manifest(cache)
    # Snapshot for PERF-04: skip the disk write if no worker mutated the
    # cache. json.dumps with sort_keys gives a stable signature without
    # the cost of a deep copy.
    cache_signature = json.dumps(cache, sort_keys=True)

    copy_assets(ctx, cache)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)

    # The stream factory rebuilds the generator on demand. Each
    # generator instance is consumed exactly once; the pipeline runs
    # one factory call for phase 1 (cross-lang projections) and one
    # per language for phase 2 (per-lang sections), bounding peak
    # memory to a single language's article batch.
    url_builder = _article_url_builder(ctx)
    allowed_langs = frozenset(ctx.languages)
    content_dir = ctx.content_dir
    default_lang = ctx.default_language

    def stream_factory():
        return iter_articles(
            content_dir,
            default_lang=default_lang,
            url_builder=url_builder,
            allowed_langs=allowed_langs,
        )

    current_manifest: dict = {}
    plan = _collect_tasks(stream_factory, cli, ctx, cache, current_manifest)
    flat = [t for tasks in plan.values() for t in tasks]
    total = len(flat)

    if total:
        logging.info(
            f"Build plan: {total} task(s) across {len(plan)} section(s)"
        )
        for section, tasks in plan.items():
            logging.info(f"  {section}: {len(tasks)} task(s)")

        t0 = time.perf_counter()
        run_parallel_tasks(flat, _resolve_parallelism(ctx))
        elapsed = time.perf_counter() - t0
        logging.info(
            f"Ran {total} task(s) in {elapsed:.2f}s "
            f"({total / elapsed:.1f} task/s)"
            if elapsed > 0 else f"Ran {total} task(s)"
        )
    else:
        logging.info("Nothing to build — all pages up to date.")

    if not cli.dry_run:
        replace_manifest = _can_prune_outputs(cli)
        if replace_manifest:
            _prune_stale_outputs(ctx, cache, old_manifest, current_manifest)
        _store_output_manifest(
            cache, old_manifest, current_manifest, replace_manifest,
        )
        if json.dumps(cache, sort_keys=True) == cache_signature:
            logging.debug("Cache unchanged — skipping save")
        else:
            save_cache(cache_path, cache)

    logging.info("Build complete.")
