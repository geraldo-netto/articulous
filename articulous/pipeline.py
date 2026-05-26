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
from xml.sax.saxutils import escape as _xml_escape

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
    file_hash,
    load_cache,
    run_parallel_tasks,
    save_cache,
    should_rebuild,
    timed,
    update_cache,
    write_json,
)


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
    parallelism: object = "auto"
    cache_file: str = ".build-cache.json"
    # engine map: section name -> TransformEngine
    engines: dict = field(default_factory=dict)
    # site / URL model
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
    return BuildCtx(
        content_dir=Path(config["paths"]["content_dir"]),
        xsl_dir=Path(config["paths"]["xsl_dir"]),
        output_dir=Path(config["paths"]["output_dir"]),
        assets_dir=Path(config["paths"]["assets_dir"]),
        force=config["build"]["force_full_build"],
        dry_run=dry_run,
        parallelism=config["build"]["parallelism"],
        # Reduce user-controlled value to a bare filename; the path
        # prefix is added in _cache_path_for to prevent traversal.
        cache_file=Path(config["build"]["cache_file"]).name,
        engines=engines,
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

def copy_assets(ctx: BuildCtx) -> None:
    """
    Mirror ``ctx.assets_dir`` into ``<output_dir>/assets``.
    No-op if the source is missing; honours dry-run.
    """
    if not ctx.assets_dir.exists():
        logging.debug(f"Assets directory not present, skipping: {ctx.assets_dir}")
        return

    dest = ctx.output_dir / "assets"

    if ctx.dry_run:
        logging.debug(f"[DRY RUN] Would copy assets: {ctx.assets_dir} -> {dest}")
        return

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ctx.assets_dir, dest)
    logging.info(f"Copied assets: {ctx.assets_dir} -> {dest}")


def _article_url_builder(ctx: BuildCtx):
    """
    Return a ``(lang, slug) -> url`` callable bound to ``ctx``. Used by
    :func:`load_articles` so each :class:`Article` is constructed with
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

def _xml_doc(root_tag: str, children: list) -> str:
    return f"<{root_tag}>{''.join(children)}</{root_tag}>"


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


# ================================================================
# Shared XSLT task plumbing
# ================================================================

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
    if isinstance(xml_input, bytes):
        xml_hash = hashlib.sha256(xml_input).hexdigest()
    else:
        xml_hash = file_hash(xml_input)

    if not should_rebuild(cache_key, cache, (xml_hash, xsl_hash), ctx.force):
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


def build_articles_section(lang_articles, ctx: BuildCtx, cache):
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
        )
        if task is None:
            logging.debug(f"Skipping unchanged article: {art.slug}")
            continue
        tasks.append(task)

    return tasks


def build_index_section(lang_articles, lang: str, ctx: BuildCtx, cache):
    """Build paginated index pages for one language."""
    tasks = []
    xsl_path = ctx.xsl_for("index")
    engine = ctx.engine_for("index")
    xsl_hash = file_hash(xsl_path)

    for page in build_index_models(lang_articles, lang, ctx):
        xml_bytes = _encode_xml(_xml_doc(
            "index", [_article_xml(a) for a in page.articles],
        ))
        task = _make_xslt_task(
            xml_input=xml_bytes,
            xsl_path=xsl_path,
            xsl_hash=xsl_hash,
            output_path=ctx.output_dir / page.output_path,
            cache=cache,
            cache_key=f"index:{page.lang}:{page.page}",
            engine=engine,
            ctx=ctx,
        )
        if task is None:
            logging.debug(f"Skipping unchanged index page {page.page}")
            continue
        tasks.append(task)

    return tasks


def build_tags_section(lang_articles, lang: str, ctx: BuildCtx, cache):
    """Build tag pages for one language."""
    tasks = []
    xsl_path = ctx.xsl_for("tags")
    engine = ctx.engine_for("tags")
    xsl_hash = file_hash(xsl_path)

    for page in build_tags_models(lang_articles, lang, ctx):
        xml_bytes = _encode_xml(_xml_doc(
            "tag", [_article_xml(a) for a in page.articles],
        ))
        task = _make_xslt_task(
            xml_input=xml_bytes,
            xsl_path=xsl_path,
            xsl_hash=xsl_hash,
            output_path=ctx.output_dir / page.output_path,
            cache=cache,
            cache_key=f"tag:{page.lang}:{page.tag_slug}",
            engine=engine,
            ctx=ctx,
        )
        if task is None:
            logging.debug(
                f"Skipping unchanged tag page: {page.lang}/{page.tag_slug}"
            )
            continue
        tasks.append(task)

    return tasks


def build_rss_section(rss_articles, ctx: BuildCtx, cache):
    """
    Build the RSS feed. ``rss_articles`` is the already-selected top-N
    list (newest first) produced by :func:`_stream_projections`.
    """
    feed = build_rss_model(rss_articles, ctx)
    xsl_path = ctx.xsl_for("rss")
    xml_bytes = _encode_xml(
        _xml_doc("rss", [_rss_item_xml(a) for a in feed.articles])
    )
    task = _make_xslt_task(
        xml_input=xml_bytes,
        xsl_path=xsl_path,
        xsl_hash=file_hash(xsl_path),
        output_path=ctx.output_dir / feed.output_path,
        cache=cache,
        cache_key="rss",
        engine=ctx.engine_for("rss"),
        ctx=ctx,
    )
    if task is None:
        logging.debug("Skipping unchanged RSS feed")
        return []
    return [task]


def build_sitemap_section(urls, ctx: BuildCtx, cache):
    """Build sitemap.xml from a streamed list of URL strings."""
    sitemap = build_sitemap_model(urls, ctx)
    xsl_path = ctx.xsl_for("sitemap")
    xml_bytes = _encode_xml(
        _xml_doc("sitemap", [_sitemap_url_xml(u) for u in sitemap.urls])
    )
    task = _make_xslt_task(
        xml_input=xml_bytes,
        xsl_path=xsl_path,
        xsl_hash=file_hash(xsl_path),
        output_path=ctx.output_dir / sitemap.output_path,
        cache=cache,
        cache_key="sitemap",
        engine=ctx.engine_for("sitemap"),
        ctx=ctx,
    )
    if task is None:
        logging.debug("Skipping unchanged sitemap")
        return []
    return [task]


def build_search_section(items, ctx: BuildCtx, cache):
    """Build search.json from a streamed list of pre-projected items."""
    index = build_search_model(items, ctx)
    output_path = ctx.output_dir / index.output_path
    json_hash = hashlib.sha256(
        json.dumps(index.items).encode("utf-8")
    ).hexdigest()

    if not should_rebuild("search", cache, (json_hash, "json"), ctx.force):
        logging.debug("Skipping unchanged search index")
        return []

    def task(output_path=output_path, items=index.items, json_hash=json_hash):
        write_json(output_path, items, dry_run=ctx.dry_run)
        update_cache(cache, "search", (json_hash, "json"))
    return [timed("search", task)]


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


def _passes_cli_filters(art, cli) -> bool:
    if cli.only_langs and art.lang not in cli.only_langs:
        return False
    if cli.only_slugs and art.slug not in cli.only_slugs:
        return False
    return True


def _filter_articles(articles, cli):
    """List-form filter retained for callers/tests that want it."""
    return [a for a in articles if _passes_cli_filters(a, cli)]


def _stream_projections(stream_factory, cli, ctx: BuildCtx):
    """
    Phase-1 streaming pass.

    Iterates the article stream once. Accumulates:

      - ``sitemap_urls`` — list of every article's URL.
      - ``search_items`` — list of search projection dicts.
      - ``rss_heap``     — bounded min-heap of (datetime, sequence, art)
                           keeping the top ``ctx.rss_items`` articles.
      - ``total``        — articles that survived the CLI filters.

    The sequence number breaks ties when two articles share a datetime
    so heapq never tries to order :class:`Article` instances directly.
    """
    rss_heap: list = []
    sitemap_urls: list = []
    search_items: list = []
    total = 0
    seq = 0  # monotonic tie-breaker for the heap
    for art in stream_factory():
        if not _passes_cli_filters(art, cli):
            continue
        total += 1
        sitemap_urls.append(art.url)
        search_items.append({
            "title": art.title,
            "description": art.description,
            "url": art.url,
            "tags": list(art.tags),
        })
        if ctx.rss_items > 0:
            entry = (art.datetime, seq, art)
            seq += 1
            if len(rss_heap) < ctx.rss_items:
                heapq.heappush(rss_heap, entry)
            elif entry > rss_heap[0]:
                heapq.heapreplace(rss_heap, entry)
    return sitemap_urls, search_items, rss_heap, total


def _rss_sorted_from_heap(rss_heap) -> list:
    """Newest-first list extracted from the min-heap."""
    return [art for _, _, art in sorted(rss_heap, reverse=True)]


def _collect_tasks(stream_factory, cli, ctx: BuildCtx, cache) -> dict:
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

    need_cross = any(want(s) for s in _CROSS_LANG_SECTIONS)
    need_per_lang = any(want(s) for s in _PER_LANG_SECTIONS)

    plan: dict = {}

    # Phase 1: cross-lang projections (one stream pass).
    if need_cross:
        sitemap_urls, search_items, rss_heap, total = _stream_projections(
            stream_factory, cli, ctx,
        )
        logging.info(f"Discovered {total} article(s) after filters")
        if want("rss"):
            plan["rss"] = build_rss_section(
                _rss_sorted_from_heap(rss_heap), ctx, cache,
            )
        if want("sitemap"):
            plan["sitemap"] = build_sitemap_section(sitemap_urls, ctx, cache)
        if want("search"):
            plan["search"] = build_search_section(search_items, ctx, cache)

    # Phase 2: per-lang sections (one stream pass per requested language).
    if need_per_lang:
        for lang in ctx.languages:
            if cli.only_langs and lang not in cli.only_langs:
                continue
            lang_articles = sorted(
                (a for a in stream_factory()
                 if a.lang == lang and _passes_cli_filters(a, cli)),
                key=lambda a: a.datetime, reverse=True,
            )
            if not lang_articles:
                continue
            if want("articles"):
                plan.setdefault("articles", []).extend(
                    build_articles_section(lang_articles, ctx, cache)
                )
            if want("index"):
                plan.setdefault("index", []).extend(
                    build_index_section(lang_articles, lang, ctx, cache)
                )
            if want("tags"):
                plan.setdefault("tags", []).extend(
                    build_tags_section(lang_articles, lang, ctx, cache)
                )
            # lang_articles goes out of scope here → released between languages.

    return plan


def _cache_path_for(ctx: BuildCtx, project_root: Path) -> Path:
    """Resolve the cache file path. ``ctx.cache_file`` is already a bare
    filename (see :func:`build_ctx_from_config`)."""
    return project_root / ctx.cache_file


def _resolve_parallelism(ctx: BuildCtx) -> object:
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


# ================================================================
# Top-level build pipeline
# ================================================================

def run_build(cli, config, project_root: Path) -> None:
    """Orchestrate the entire build process."""
    logging.info("Starting build...")

    ctx = build_ctx_from_config(config, dry_run=cli.dry_run)
    cache_path = _cache_path_for(ctx, project_root)
    cache = load_cache(cache_path)
    # Snapshot for PERF-04: skip the disk write if no worker mutated the
    # cache. json.dumps with sort_keys gives a stable signature without
    # the cost of a deep copy.
    cache_signature = json.dumps(cache, sort_keys=True)

    copy_assets(ctx)
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

    plan = _collect_tasks(stream_factory, cli, ctx, cache)
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
        if json.dumps(cache, sort_keys=True) == cache_signature:
            logging.debug("Cache unchanged — skipping save")
        else:
            save_cache(cache_path, cache)

    logging.info("Build complete.")
