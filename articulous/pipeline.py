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
import json
import logging
import shutil
import tempfile
import time
from dataclasses import dataclass, field, replace as _dc_replace
from pathlib import Path
from typing import Callable, Optional
from xml.sax.saxutils import escape as _xml_escape

from .articles import load_articles
from .engines import (
    SECTION_XSL,
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
    temp_dir: Optional[Path] = None
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


def build_ctx_from_config(config: dict, dry_run: bool) -> BuildCtx:
    """
    Project the raw config dict into a :class:`BuildCtx`.

    This is the only function in the package that reads the raw config
    dict's deep shape. It also validates the configured engine names
    and resolves the SaxonC binary, so callers downstream see only a
    typed ctx — no config dict, no string-compared engine names.
    """
    validate_engines(config)
    saxonc_bin = configure_saxonc(config)
    engines = {
        section: make_engine(name, saxonc_bin)
        for section, name in config["engines"].items()
    }
    return BuildCtx(
        content_dir=Path(config["paths"]["content_dir"]),
        xsl_dir=Path(config["paths"]["xsl_dir"]),
        output_dir=Path(config["paths"]["output_dir"]),
        assets_dir=Path(config["paths"]["assets_dir"]),
        temp_dir=None,
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
        per_page=config["site"]["pagination"]["per_page"],
        rss_items=config["site"]["pagination"]["rss_items"],
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
    xml_path: Path,
    xsl_path: Path,
    output_path: Path,
    cache: dict,
    cache_key: str,
    engine: TransformEngine,
    ctx: BuildCtx,
) -> Optional[Callable]:
    """
    Return a transform task for an XSLT-driven section, or ``None`` if
    the cache says the output is up to date. The cache entry is
    committed *inside* the returned task, after a successful transform
    — failed transforms leave the prior cache entry intact.
    """
    xml_hash = file_hash(xml_path)
    xsl_hash = file_hash(xsl_path)
    if not should_rebuild(cache_key, cache, (xml_hash, xsl_hash), ctx.force):
        return None
    hashes = (xml_hash, xsl_hash)

    def task(xml_path=xml_path, xsl_path=xsl_path, output_path=output_path):
        engine.run(xml_path, xsl_path, output_path, dry_run=ctx.dry_run)
        update_cache(cache, cache_key, hashes)

    return timed(cache_key, task)


def _make_xslt_task_with_temp(
    *,
    xml_temp: Path,
    xml_content: str,
    ctx: BuildCtx,
    **kwargs,
) -> Optional[Callable]:
    """
    Variant of :func:`_make_xslt_task` for sections that synthesise a
    model XML file first. Always writes the temp file (even in dry-run)
    because hashing is part of the cache decision.
    """
    xml_temp.parent.mkdir(parents=True, exist_ok=True)
    xml_temp.write_text(xml_content, encoding="utf-8")
    return _make_xslt_task(xml_path=xml_temp, ctx=ctx, **kwargs)


# ================================================================
# Section builders
# ================================================================

def build_articles_section(articles, ctx: BuildCtx, cache):
    """
    Build all article pages.

    Articles arrive with their ``url`` already set by
    :func:`articulous.articles.load_articles` (using the URL builder
    returned by :func:`_article_url_builder`).
    """
    tasks = []
    xsl_path = ctx.xsl_for("articles")
    engine = ctx.engine_for("articles")
    pattern = ctx.url_patterns["article"]

    for art in articles:
        output_path = ctx.output_dir / build_rel_path_from_pattern(
            pattern, lang=art.lang, slug=art.slug,
        )
        task = _make_xslt_task(
            xml_path=art.source_path,
            xsl_path=xsl_path,
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


def build_index_section(articles, ctx: BuildCtx, cache):
    """Build paginated index pages."""
    tasks = []
    xsl_path = ctx.xsl_for("index")
    engine = ctx.engine_for("index")

    for page in build_index_models(articles, ctx):
        xml_content = _xml_doc(
            "index", [_article_xml(a) for a in page.articles],
        )
        task = _make_xslt_task_with_temp(
            xml_temp=ctx.temp_dir / f"index-{page.lang}-{page.page}.xml",
            xml_content=xml_content,
            xsl_path=xsl_path,
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


def build_tags_section(articles, ctx: BuildCtx, cache):
    """Build tag pages."""
    tasks = []
    xsl_path = ctx.xsl_for("tags")
    engine = ctx.engine_for("tags")

    for page in build_tags_models(articles, ctx):
        xml_content = _xml_doc(
            "tag", [_article_xml(a) for a in page.articles],
        )
        task = _make_xslt_task_with_temp(
            xml_temp=ctx.temp_dir / f"tag-{page.lang}-{page.tag_slug}.xml",
            xml_content=xml_content,
            xsl_path=xsl_path,
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


def build_rss_section(articles, ctx: BuildCtx, cache):
    """Build RSS feed."""
    feed = build_rss_model(articles, ctx)
    xml_content = _xml_doc("rss", [_rss_item_xml(a) for a in feed.articles])
    task = _make_xslt_task_with_temp(
        xml_temp=ctx.temp_dir / "rss.xml",
        xml_content=xml_content,
        xsl_path=ctx.xsl_for("rss"),
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


def build_sitemap_section(articles, ctx: BuildCtx, cache):
    """Build sitemap.xml."""
    sitemap = build_sitemap_model(articles, ctx)
    xml_content = _xml_doc(
        "sitemap", [_sitemap_url_xml(u) for u in sitemap.urls],
    )
    task = _make_xslt_task_with_temp(
        xml_temp=ctx.temp_dir / "sitemap.xml",
        xml_content=xml_content,
        xsl_path=ctx.xsl_for("sitemap"),
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


def build_search_section(articles, ctx: BuildCtx, cache):
    """Build search.json. No XSLT needed; pure JSON write."""
    index = build_search_model(articles, ctx)
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
# Section dispatch
# ================================================================

SECTION_BUILDERS = {
    "articles": build_articles_section,
    "index": build_index_section,
    "tags": build_tags_section,
    "rss": build_rss_section,
    "sitemap": build_sitemap_section,
    "search": build_search_section,
}


def _filter_articles(articles, cli):
    if cli.only_langs:
        wanted = set(cli.only_langs)
        articles = [a for a in articles if a.lang in wanted]
    if cli.only_slugs:
        wanted = set(cli.only_slugs)
        articles = [a for a in articles if a.slug in wanted]
    return articles


def _collect_tasks(articles, ctx: BuildCtx, cache, only_sections) -> dict:
    """
    Dispatch each requested section to its builder and return a
    ``{section_name: [task, ...]}`` plan. The caller flattens it for
    parallel execution and uses the per-section counts for logging.

    Section order is no longer load-bearing: every section reads
    ``article.url`` from the field that :func:`load_articles` populated
    during parse, so any subset of sections (``--only ...``) is safe to
    run.
    """
    wanted = set(only_sections) if only_sections else None
    plan: dict = {}
    for name, builder in SECTION_BUILDERS.items():
        if wanted is not None and name not in wanted:
            continue
        plan[name] = builder(articles, ctx, cache)
    return plan


def _cache_path_for(ctx: BuildCtx, project_root: Path) -> Path:
    """Resolve the cache file path. ``ctx.cache_file`` is already a bare
    filename (see :func:`build_ctx_from_config`)."""
    return project_root / ctx.cache_file


# ================================================================
# Top-level build pipeline
# ================================================================

def run_build(cli, config, project_root: Path) -> None:
    """Orchestrate the entire build process."""
    logging.info("Starting build...")

    ctx = build_ctx_from_config(config, dry_run=cli.dry_run)
    cache_path = _cache_path_for(ctx, project_root)
    cache = load_cache(cache_path)

    copy_assets(ctx)

    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=".sitegen-", dir=ctx.output_dir))
    ctx = _dc_replace(ctx, temp_dir=temp_dir)

    try:
        articles = load_articles(
            ctx.content_dir,
            default_lang=ctx.default_language,
            url_builder=_article_url_builder(ctx),
            allowed_langs=ctx.languages,
        )
        articles = _filter_articles(articles, cli)

        plan = _collect_tasks(articles, ctx, cache, cli.only_sections)
        flat = [t for tasks in plan.values() for t in tasks]
        total = len(flat)

        if total:
            logging.info(
                f"Build plan: {total} task(s) across {len(plan)} section(s)"
            )
            for section, tasks in plan.items():
                logging.info(f"  {section}: {len(tasks)} task(s)")

            t0 = time.perf_counter()
            run_parallel_tasks(flat, ctx.parallelism)
            elapsed = time.perf_counter() - t0
            logging.info(
                f"Ran {total} task(s) in {elapsed:.2f}s "
                f"({total / elapsed:.1f} task/s)"
                if elapsed > 0 else f"Ran {total} task(s)"
            )
        else:
            logging.info("Nothing to build — all pages up to date.")

        if not cli.dry_run:
            save_cache(cache_path, cache)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    logging.info("Build complete.")
