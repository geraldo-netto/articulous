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
import pickle
import shutil
import time
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import Any, Callable, Optional
from xml.sax.saxutils import escape as _xml_escape, quoteattr as _xml_attr

from .articles import ArticleStats, iter_articles
from .engines import (
    SaxonCEngine,
    TransformEngine,
    configure_saxonc,
    make_engine,
    stylesheet_hash,
)
from .filesystem import TempWorkspace, lock_file
from .models import (
    build_index_models,
    build_output_path_from_pattern,
    build_rss_model,
    build_search_model,
    build_sitemap_model,
    build_tags_models,
    build_url_from_pattern,
)
from .runtime import (
    WorkerCount,
    cache_changed,
    file_hash,
    load_cache,
    run_parallel_tasks,
    save_cache,
    should_rebuild,
    timed,
    update_cache,
)
from .sections import (
    CROSS_LANG_SECTIONS,
    PER_LANG_SECTIONS,
    SECTION_XSL,
)


_ASSET_CACHE_KEY = "assets"
_ASSET_CACHE_VERSION = 1
_OUTPUT_MANIFEST_KEY = "__outputs__"
_SORT_CHUNK_SIZE = 1024


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


def build_ctx_from_config(config: dict, dry_run: bool) -> BuildCtx:
    """
    Project the raw config dict into a :class:`BuildCtx`.

    Configuration shape and values have already been validated by
    :func:`articulous.config.load_or_create_config`.
    """
    saxonc_bin = configure_saxonc(config)
    engines = {
        section: make_engine(name, saxonc_bin)
        for section, name in config["engines"].items()
    }
    pagination = config["site"]["pagination"]
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
        site_name=config["site"]["site_name"],
        base_url=config["site"]["base_url"],
        languages=list(config["site"]["languages"]),
        default_language=config["site"]["default_language"],
        url_patterns=dict(config["urls"]),
        per_page=pagination["per_page"],
        rss_items=pagination["rss_items"],
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


def _asset_manifest(root: Path) -> dict:
    manifest = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        stat = path.stat()
        if path.is_dir():
            manifest[rel] = ["d", stat.st_mtime_ns]
        else:
            manifest[rel] = ["f", stat.st_size, stat.st_mtime_ns, file_hash(path)]
    return manifest


def _asset_cache_entry(manifest: dict) -> dict:
    return {"version": _ASSET_CACHE_VERSION, "manifest": manifest}


def _validated_asset_cache_entry(cache: Optional[dict]) -> Optional[dict]:
    if cache is None:
        return None
    entry = cache.get(_ASSET_CACHE_KEY)
    if not isinstance(entry, dict):
        return None
    if entry.get("version") != _ASSET_CACHE_VERSION:
        return None
    return entry


def _asset_output_matches(path: Path, metadata: list) -> bool:
    if metadata[0] == "d":
        return path.is_dir()
    if not path.is_file():
        return False
    stat = path.stat()
    return stat.st_size == metadata[1] and file_hash(path) == metadata[3]


def _asset_output_mismatches(dest: Path, manifest: dict) -> set[str]:
    return {
        rel
        for rel, metadata in manifest.items()
        if not _asset_output_matches(dest / rel, metadata)
    }


def _assets_unchanged(
    cache: Optional[dict], manifest: dict, ctx: BuildCtx, mismatches: set[str],
) -> bool:
    if ctx.force:
        return False
    entry = _validated_asset_cache_entry(cache)
    return (
        entry is not None
        and entry.get("manifest") == manifest
        and not mismatches
    )


def _cached_asset_manifest(cache: Optional[dict]) -> dict:
    entry = _validated_asset_cache_entry(cache)
    if entry is None:
        return {}
    manifest = entry.get("manifest")
    return manifest if isinstance(manifest, dict) else {}


def _remove_asset_type_conflicts(
    dest: Path, old: dict, new: dict,
) -> None:
    for rel in sorted(set(old) & set(new), reverse=True):
        if old[rel][0] != new[rel][0]:
            _delete_output_file(dest / rel, dest)


def _copy_asset_delta(
    src: Path, dest: Path, old: dict, new: dict, refresh: set[str],
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for rel in sorted(set(old) - set(new), reverse=True):
        target = dest / rel
        _delete_output_file(target, dest)
    _remove_asset_type_conflicts(dest, old, new)
    for rel, meta in sorted(new.items()):
        target = dest / rel
        if meta[0] == "d":
            target.mkdir(parents=True, exist_ok=True)
        elif old.get(rel) != meta or rel in refresh:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, target)


def _prune_missing_assets(ctx: BuildCtx, dest: Path, cache: Optional[dict]) -> None:
    if ctx.dry_run:
        logging.debug(f"[DRY RUN] Would remove stale assets output: {dest}")
        return
    if dest.exists():
        _delete_output_file(dest, ctx.output_dir.resolve())
        logging.info(f"Removed stale assets output: {dest}")
    if cache is not None:
        cache.pop(_ASSET_CACHE_KEY, None)


def copy_assets(ctx: BuildCtx, cache: Optional[dict] = None) -> None:
    """
    Mirror ``ctx.assets_dir`` into ``<output_dir>/assets``.
    If the source is missing, remove stale copied assets; honours dry-run.
    """
    dest = _safe_output_path(ctx, ctx.output_dir / "assets")
    if not ctx.assets_dir.exists():
        logging.debug(f"Assets directory not present, skipping: {ctx.assets_dir}")
        _prune_missing_assets(ctx, dest, cache)
        return

    _assert_non_overlapping_trees(ctx.assets_dir, dest)
    manifest = _asset_manifest(ctx.assets_dir)

    if ctx.dry_run:
        logging.debug(f"[DRY RUN] Would copy assets: {ctx.assets_dir} -> {dest}")
        return

    old_manifest = _cached_asset_manifest(cache)
    mismatches = _asset_output_mismatches(dest, manifest)
    if dest.exists() and _assets_unchanged(cache, manifest, ctx, mismatches):
        logging.debug("Skipping unchanged assets")
        return

    refresh = set(manifest) if ctx.force else mismatches
    _copy_asset_delta(ctx.assets_dir, dest, old_manifest, manifest, refresh)
    if cache is not None:
        cache[_ASSET_CACHE_KEY] = _asset_cache_entry(manifest)
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


class FragmentSink:
    def __init__(self, workspace: TempWorkspace):
        f = workspace.named_file("w+", encoding="utf-8")
        self.path = Path(f.name)
        self._file = f
        self.count = 0

    def append(self, fragment: str) -> None:
        self._file.write(fragment)
        self.count += 1

    def flush(self) -> None:
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    def __len__(self) -> int:
        return self.count

    def __eq__(self, other) -> bool:
        return self.count == 0 and other == []


class SearchSink:
    def __init__(self, workspace: TempWorkspace):
        self.items = FragmentSink(workspace)
        self.json = FragmentSink(workspace)

    def append_item(self, item: dict) -> None:
        if self.json.count:
            self.json.append(",\n")
        self.json.append(_xml_escape(json.dumps(item)))
        self.items.append(_search_item_xml(item))

    def flush(self) -> None:
        self.items.flush()
        self.json.flush()

    def close(self) -> None:
        self.items.close()
        self.json.close()

    def __len__(self) -> int:
        return self.items.count

    def __eq__(self, other) -> bool:
        return self.items.count == 0 and other == []


class SortedArticleBatch:
    def __init__(self, chunks: list[tuple[Path, int]], count: int):
        self._chunks = chunks
        self._count = count

    def __iter__(self):
        streams = (
            _read_pickled_articles(path, count)
            for path, count in self._chunks
        )
        yield from heapq.merge(
            *streams, key=lambda a: a.datetime, reverse=True,
        )

    def __len__(self) -> int:
        return self._count

    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(islice(iter(self), item.start, item.stop, item.step))
        return next(islice(iter(self), item, item + 1))

    def __eq__(self, other) -> bool:
        return self._count == 0 and other == []


def _write_sorted_article_chunk(workspace: TempWorkspace, articles: list) -> tuple[Path, int]:
    articles.sort(key=lambda a: a.datetime, reverse=True)
    with workspace.named_file("w+b") as f:
        for art in articles:
            pickle.dump(art, f)
        return Path(f.name), len(articles)


class ArticleStore:
    def __init__(self, workspace: TempWorkspace):
        self._workspace = workspace
        self._files: dict[str, Any] = {}
        self.counts: dict[str, int] = {}

    def append(self, lang: str, art) -> None:
        f = self._files.get(lang)
        if f is None:
            f = self._workspace.named_file("w+b")
            self._files[lang] = f
        pickle.dump(art, f)
        self.counts[lang] = self.counts.get(lang, 0) + 1

    def iter_lang(self, lang: str):
        f = self._files.get(lang)
        if f is None:
            return
        f.flush()
        path = Path(f.name)
        yield from _read_pickled_articles(path, self.counts[lang])

    def sorted(self, lang: str) -> SortedArticleBatch:
        chunks: list[tuple[Path, int]] = []
        chunk = []
        for art in self.iter_lang(lang):
            chunk.append(art)
            if len(chunk) == _SORT_CHUNK_SIZE:
                chunks.append(_write_sorted_article_chunk(self._workspace, chunk))
                chunk = []
        if chunk:
            chunks.append(_write_sorted_article_chunk(self._workspace, chunk))
        return SortedArticleBatch(chunks, self.counts.get(lang, 0))

    def close(self) -> None:
        for f in self._files.values():
            f.close()


class OutputManifest(dict):
    def __init__(self):
        super().__init__()
        self._owners: dict[str, str] = {}

    def record(self, cache_key: str, relpath: str) -> None:
        if cache_key in self:
            raise ValueError(f"Duplicate generated cache key: {cache_key}")
        owner = self._owners.get(relpath)
        if owner is not None:
            raise ValueError(
                f"Duplicate generated output path: {relpath} "
                f"for {owner!r} and {cache_key!r}"
            )
        super().__setitem__(cache_key, relpath)
        self._owners[relpath] = cache_key


def _read_pickled_articles(path: Path, count: int):
    with path.open("rb") as f:
        for _ in range(count):
            yield pickle.load(f)


def _write_model_file(
    workspace: TempWorkspace, root_tag: str, attrs: str, body_path: Path,
) -> Path:
    with workspace.named_file("w", encoding="utf-8") as out:
        out.write(f"<{root_tag}{attrs}>")
        with body_path.open(encoding="utf-8") as body:
            shutil.copyfileobj(body, out)
        out.write(f"</{root_tag}>")
        return Path(out.name)


def _write_search_model_file(
    workspace: TempWorkspace, attrs: str, sink: SearchSink,
) -> Path:
    with workspace.named_file("w", encoding="utf-8") as out:
        out.write(f"<search{attrs}><json>[\n")
        with sink.json.path.open(encoding="utf-8") as body:
            shutil.copyfileobj(body, out)
        out.write("\n]</json>")
        with sink.items.path.open(encoding="utf-8") as body:
            shutil.copyfileobj(body, out)
        out.write("</search>")
        return Path(out.name)


# ================================================================
# Shared XSLT task plumbing
# ================================================================

def _record_planned_output(
    manifest: Optional[OutputManifest],
    ctx: BuildCtx,
    cache_key: str,
    output_path: Path,
) -> Path:
    output_path = _safe_output_path(ctx, output_path)
    if manifest is None:
        return output_path
    relpath = _output_relpath(ctx, output_path)
    manifest.record(cache_key, relpath)
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
    manifest: Optional[OutputManifest] = None,
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

    fingerprint = (xml_hash, xsl_hash, engine.cache_identity)
    if not should_rebuild(
        cache_key, cache, fingerprint, ctx.force, output_path=output_path,
    ):
        return None

    def task(xml_input=xml_input, xsl_path=xsl_path, output_path=output_path):
        engine.run(xml_input, xsl_path, output_path, dry_run=ctx.dry_run)
        update_cache(cache, cache_key, fingerprint)

    return timed(cache_key, task)


# ================================================================
# Section builders
# ================================================================

def _encode_xml(content: str) -> bytes:
    return content.encode("utf-8")


def _section_runtime(ctx: BuildCtx, section: str) -> tuple[Path, str, TransformEngine]:
    xsl_path = ctx.xsl_for(section)
    return xsl_path, stylesheet_hash(xsl_path), ctx.engine_for(section)


def _append_task(tasks: list, task: Optional[Callable], skip_message: str) -> None:
    if task is None:
        logging.debug(skip_message)
        return
    tasks.append(task)


def build_articles_section(lang_articles, ctx: BuildCtx, cache, manifest=None):
    """
    Build article pages for one language's article batch.

    Called once per language by :func:`run_build`; the input is a
    per-language sorted list, not the global article set.
    """
    tasks = []
    xsl_path, xsl_hash, engine = _section_runtime(ctx, "articles")
    pattern = ctx.url_patterns["article"]

    for art in lang_articles:
        output_path = ctx.output_dir / build_output_path_from_pattern(
            "articles", pattern, lang=art.lang, slug=art.slug,
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
        _append_task(tasks, task, f"Skipping unchanged article: {art.slug}")

    return tasks


def build_index_section(lang_articles, lang: str, ctx: BuildCtx, cache, manifest=None):
    """Build paginated index pages for one language."""
    tasks = []
    xsl_path, xsl_hash, engine = _section_runtime(ctx, "index")

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
        _append_task(tasks, task, f"Skipping unchanged index page {page.page}")

    return tasks


def build_tags_section(lang_articles, lang: str, ctx: BuildCtx, cache, manifest=None):
    """Build tag pages for one language."""
    tasks = []
    xsl_path, xsl_hash, engine = _section_runtime(ctx, "tags")

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
        _append_task(
            tasks, task,
            f"Skipping unchanged tag page: {page.lang}/{page.tag_slug}",
        )

    return tasks


def build_rss_section(rss_articles, ctx: BuildCtx, cache, manifest=None):
    """
    Build the RSS feed. ``rss_articles`` is the already-selected top-N
    list (newest first) produced by :func:`_stream_projections`.
    """
    feed = build_rss_model(rss_articles, ctx)
    xml_bytes = _encode_xml(_rss_doc(feed, ctx.site_name))
    return _single_xslt_section(
        "rss", xml_bytes, ctx.output_dir / feed.output_path,
        "rss", "Skipping unchanged RSS feed", ctx, cache, manifest,
    )


def _single_xslt_section(
    section: str,
    xml_input,
    output_path: Path,
    cache_key: str,
    skip_message: str,
    ctx: BuildCtx,
    cache,
    manifest,
) -> list:
    xsl_path, xsl_hash, engine = _section_runtime(ctx, section)
    task = _make_xslt_task(
        xml_input=xml_input,
        xsl_path=xsl_path,
        xsl_hash=xsl_hash,
        output_path=output_path,
        cache=cache,
        cache_key=cache_key,
        engine=engine,
        ctx=ctx,
        manifest=manifest,
    )
    if task is None:
        logging.debug(skip_message)
        return []
    return [task]


def build_sitemap_section(urls, ctx: BuildCtx, cache, workspace=None, manifest=None):
    """Build sitemap.xml from a streamed list of URL strings."""
    if isinstance(workspace, dict) and manifest is None:
        manifest = workspace
        workspace = None
    sitemap = build_sitemap_model([], ctx)
    if isinstance(urls, FragmentSink):
        assert isinstance(workspace, TempWorkspace)
        attrs = f" site={_xml_attr(ctx.site_name)} self={_xml_attr(sitemap.url)}"
        urls.flush()
        xml_input = _write_model_file(workspace, "sitemap", attrs, urls.path)
    else:
        sitemap = build_sitemap_model(urls, ctx)
        xml_input = _encode_xml(_sitemap_doc(sitemap, ctx.site_name))
    return _single_xslt_section(
        "sitemap", xml_input, ctx.output_dir / sitemap.output_path,
        "sitemap", "Skipping unchanged sitemap", ctx, cache, manifest,
    )


def build_search_section(items, ctx: BuildCtx, cache, workspace=None, manifest=None):
    """Build search.json through the configured search XSLT engine."""
    if isinstance(workspace, dict) and manifest is None:
        manifest = workspace
        workspace = None
    index = build_search_model([], ctx)
    if isinstance(items, SearchSink):
        assert isinstance(workspace, TempWorkspace)
        attrs = f" site={_xml_attr(ctx.site_name)}"
        items.flush()
        xml_input = _write_search_model_file(workspace, attrs, items)
    else:
        index = build_search_model(items, ctx)
        xml_input = _encode_xml(_search_doc(index, ctx.site_name))
    return _single_xslt_section(
        "search", xml_input, ctx.output_dir / index.output_path,
        "search", "Skipping unchanged search index", ctx, cache, manifest,
    )


# ================================================================
# Streaming dispatch
# ================================================================

@dataclass
class StreamProjection:
    sitemap_urls: FragmentSink
    search_items: SearchSink
    rss_heap: list
    total: int
    skipped_by_publication: dict = field(default_factory=dict)
    articles_by_lang: ArticleStore | None = None
    listings_by_lang: ArticleStore | None = None


class BuildPlan(dict):
    def __init__(self, plan: dict, projection: StreamProjection):
        super().__init__(plan)
        self.projection = projection


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
    workspace: TempWorkspace | None = None,
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
    workspace = workspace or TempWorkspace()
    article_store = ArticleStore(workspace) if collect_articles else None
    listing_store = ArticleStore(workspace) if collect_articles else None
    projection = StreamProjection(
        FragmentSink(workspace), SearchSink(workspace), [], 0,
        articles_by_lang=article_store,
        listings_by_lang=listing_store,
    )
    seq = 0  # monotonic tie-breaker for the heap
    for art in stream_factory():
        if not _passes_cli_filters(art, cli):
            continue
        if not art.policy.page:
            _record_skipped_publication(projection, art)
            continue
        _record_projection_article(projection, art, collect_articles, collect_cross)
        if collect_cross and ctx.rss_items > 0 and art.policy.rss:
            entry = (art.datetime, seq, art)
            seq += 1
            _push_rss_entry(projection.rss_heap, entry, ctx.rss_items)
    return projection


def _record_skipped_publication(projection: StreamProjection, art) -> None:
    name = art.publication_state.name
    projection.skipped_by_publication[name] = (
        projection.skipped_by_publication.get(name, 0) + 1
    )


def _record_projection_article(
    projection: StreamProjection, art, collect_articles: bool, collect_cross: bool,
) -> None:
    projection.total += 1
    if collect_articles:
        assert projection.articles_by_lang is not None
        assert projection.listings_by_lang is not None
        projection.articles_by_lang.append(art.lang, art)
        if art.policy.listing:
            projection.listings_by_lang.append(art.lang, art)
    if collect_cross:
        _add_cross_projection(projection, art)


def _add_cross_projection(projection: StreamProjection, art) -> None:
    if art.policy.sitemap:
        projection.sitemap_urls.append(_sitemap_url_xml(art.url))
    if art.policy.search:
        item = {
            "title": art.title,
            "description": art.description,
            "url": art.url,
            "tags": list(art.tags),
        }
        projection.search_items.append_item(item)


def _push_rss_entry(rss_heap: list, entry: tuple, limit: int) -> None:
    if len(rss_heap) < limit:
        heapq.heappush(rss_heap, entry)
    elif entry > rss_heap[0]:
        heapq.heapreplace(rss_heap, entry)


def _rss_sorted_from_heap(rss_heap) -> list:
    """Newest-first list extracted from the min-heap."""
    return [art for _, _, art in sorted(rss_heap, reverse=True)]


def _collect_cross_lang_plan(
    projection: StreamProjection, ctx, cache, want, workspace, manifest,
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
            projection.sitemap_urls, ctx, cache, workspace, manifest,
        )
    if want("search"):
        plan["search"] = build_search_section(
            projection.search_items, ctx, cache, workspace, manifest,
        )
    return plan


def _sorted_store_articles(store: ArticleStore | None, lang: str):
    if store is None:
        return []
    return store.sorted(lang)


def _add_per_lang_tasks(
    plan: dict, lang_articles, listing_articles, lang, ctx, cache, want, manifest,
) -> None:
    if want("articles"):
        plan.setdefault("articles", []).extend(
            build_articles_section(lang_articles, ctx, cache, manifest)
        )
    if want("index"):
        plan.setdefault("index", []).extend(
            build_index_section(listing_articles, lang, ctx, cache, manifest)
        )
    if want("tags"):
        plan.setdefault("tags", []).extend(
            build_tags_section(listing_articles, lang, ctx, cache, manifest)
        )


def _collect_per_lang_plan(
    projection: StreamProjection, cli, ctx: BuildCtx, cache, want, manifest,
) -> dict:
    """Phase-2 streaming pass: per-language sections (articles / index / tags)."""
    plan: dict = {}
    for lang in ctx.languages:
        if cli.only_langs and lang not in cli.only_langs:
            continue
        lang_articles = _sorted_store_articles(projection.articles_by_lang, lang)
        if not lang_articles:
            continue
        listing_articles = _sorted_store_articles(projection.listings_by_lang, lang)
        _add_per_lang_tasks(
            plan, lang_articles, listing_articles, lang, ctx, cache, want, manifest,
        )
        # lang_articles goes out of scope here → released between languages.
    return plan


def _collect_tasks(
    stream_factory, cli, ctx: BuildCtx, cache, workspace=None, manifest=None,
) -> BuildPlan:
    """
    Stream the article set and dispatch every requested section.

    Returns a dict-like plan ready for parallel execution.
    """
    if isinstance(workspace, dict) and manifest is None:
        manifest = workspace
        workspace = None
    if workspace is None:
        workspace = TempWorkspace()
    assert isinstance(workspace, TempWorkspace)
    wanted = set(cli.only_sections) if cli.only_sections else None

    def want(section: str) -> bool:
        return wanted is None or section in wanted

    plan: dict = {}
    need_cross = any(want(s) for s in CROSS_LANG_SECTIONS)
    need_per_lang = any(want(s) for s in PER_LANG_SECTIONS)
    projection = _stream_projections(
        stream_factory,
        cli,
        ctx,
        workspace,
        collect_cross=need_cross,
        collect_articles=need_per_lang,
    )
    if need_cross:
        plan.update(
            _collect_cross_lang_plan(projection, ctx, cache, want, workspace, manifest)
        )
    if need_per_lang:
        plan.update(
            _collect_per_lang_plan(
                projection, cli, ctx, cache, want, manifest,
            )
        )
    return BuildPlan(plan, projection)


def _article_stream_factory(ctx: BuildCtx, stats: ArticleStats):
    url_builder = _article_url_builder(ctx)
    allowed_langs = frozenset(ctx.languages)

    def stream_factory():
        return iter_articles(
            ctx.content_dir,
            default_lang=ctx.default_language,
            url_builder=url_builder,
            allowed_langs=allowed_langs,
            stats=stats,
        )

    return stream_factory


def _run_plan(plan: dict, ctx: BuildCtx) -> None:
    flat = [t for tasks in plan.values() for t in tasks]
    total = len(flat)
    if not total:
        logging.info("Nothing to build — all pages up to date.")
        return
    logging.info(f"Build plan: {total} task(s) across {len(plan)} section(s)")
    for section, tasks in plan.items():
        logging.info(f"  {section}: {len(tasks)} task(s)")
    t0 = time.perf_counter()
    run_parallel_tasks(flat, _resolve_parallelism(ctx))
    elapsed = time.perf_counter() - t0
    rate = f" ({total / elapsed:.1f} task/s)" if elapsed > 0 else ""
    logging.info(f"Ran {total} task(s) in {elapsed:.2f}s{rate}")


def _log_article_stats(stats: ArticleStats, projection: StreamProjection) -> None:
    logging.info(
        f"Article scan: {stats.scanned} file(s), {stats.parsed} parsed, "
        f"{stats.skipped} invalid"
    )
    for state, count in sorted(projection.skipped_by_publication.items()):
        logging.info(f"Article scan: {count} {state} article(s) skipped")


def _finalize_cache(cli, ctx, cache, old_manifest, current_manifest, cache_path) -> None:
    replace_manifest = _can_prune_outputs(cli)
    if replace_manifest:
        _prune_stale_outputs(ctx, cache, old_manifest, current_manifest)
    _store_output_manifest(cache, old_manifest, current_manifest, replace_manifest)
    if cache_changed(cache):
        save_cache(cache_path, cache)
    else:
        logging.debug("Cache unchanged — skipping save")


def _cache_path_for(ctx: BuildCtx, project_root: Path) -> Path:
    """Resolve the cache file path. ``ctx.cache_file`` is already a bare
    filename (see :func:`build_ctx_from_config`)."""
    return project_root / ctx.cache_file


def _lock_path_for(ctx: BuildCtx, project_root: Path) -> Path:
    return _cache_path_for(ctx, project_root).with_suffix(".lock")


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


def _cleanup_stream_projection(projection: Optional[StreamProjection]) -> None:
    if projection is None:
        return
    for sink in (projection.sitemap_urls, projection.search_items):
        sink.close()
    if projection.articles_by_lang is not None:
        projection.articles_by_lang.close()
    if projection.listings_by_lang is not None:
        projection.listings_by_lang.close()


# ================================================================
# Top-level build pipeline
# ================================================================

def run_build(cli, config, project_root: Path) -> None:
    """Orchestrate the entire build process."""
    logging.info("Starting build...")

    ctx = build_ctx_from_config(config, dry_run=cli.dry_run)
    cache_path = _cache_path_for(ctx, project_root)
    with lock_file(_lock_path_for(ctx, project_root)):
        with TempWorkspace() as workspace:
            projection = None
            try:
                cache = load_cache(cache_path)
                old_manifest = _load_output_manifest(cache)
                copy_assets(ctx, cache)
                ctx.output_dir.mkdir(parents=True, exist_ok=True)
                stats = ArticleStats()
                stream_factory = _article_stream_factory(ctx, stats)
                current_manifest = OutputManifest()
                plan = _collect_tasks(
                    stream_factory, cli, ctx, cache, workspace, current_manifest,
                )
                projection = plan.projection
                _run_plan(plan, ctx)
                _log_article_stats(stats, projection)
                if not cli.dry_run:
                    _finalize_cache(
                        cli, ctx, cache, old_manifest, current_manifest, cache_path,
                    )
            finally:
                _cleanup_stream_projection(projection)

    logging.info("Build complete.")
