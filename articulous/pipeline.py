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
from operator import attrgetter

import hashlib
import heapq
import json
import logging
import os
import pickle
import shutil
import stat
import tempfile
from struct import Struct
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from contextlib import closing, contextmanager
from functools import partial
from itertools import chain
from pathlib import Path

from types import MappingProxyType
from typing import Any, Callable, NamedTuple, Optional, Protocol
from urllib.parse import quote, urlsplit
from uuid import uuid4
from xml.sax.saxutils import escape as _xml_escape, quoteattr as _xml_attr

from .articles import ArticleSnapshot, ArticleStats, iter_articles
from .cache_store import cache_payload, finish_cache_update, lock_selected_cache, selected_roots
from .config import admit_configuration, normalize_configuration, validate_output_layout
from .configuration_contracts import BuildOptions, ConfigurationInput, DEFAULT_CACHE_RETENTION_DAYS
from .composition import route_cache_data, route_from_output, validate_page_url
from .composition_contracts import ExtraArtifact, ExtraPage, Route, RouteWriter, artifact_values
from .engines import (
    NativeEngine,
    StylesheetCapture,
    configure_saxonc,
    make_engine,
)
from .transform_contracts import TransformEngine, require_transform
from .extensions import ModelInput, ModelProjection
from .filesystem import (
    StagedOutput, TempWorkspace, assert_disjoint_trees, atomic_output, cache_lock_path, copy_asset_file,
    lock_file, open_regular_file,
    validate_output_path, validate_path_length,
)
from .models import (
    IndexOptions,
    Sitemap,
    build_index_models,
    build_output_path_from_pattern,
    build_rss_model,
    build_search_model,
    build_sitemap_model,
    _iter_tag_pages,
    build_url_from_pattern,
    section_pattern,
)
from .migrations import OutputMigrations
from .output_cache import last_used, refresh_output_cache
from .runtime import (
    TrackedCache,
    WeightedTask,
    WorkerCount,
    file_hash,
    load_cache,
    run_parallel_tasks,
    save_cache,
    _admitted_rebuild,
    _worker_count,
    timed,
    update_cache,
)
from .publication_paths import transaction_path
from .ownership import Ownership, journal_ownership, load_ownership, ownership_path, save_ownership
from .sections import (
    CROSS_LANG_SECTIONS,
    PER_LANG_SECTIONS,
    SECTION_NAMES,
    SECTION_XSL,
    section_is_per_lang,
    url_origin,
    validate_sitemap_location,
)
from .sitemaps import (
    SitemapSlice, native_entry as _native_sitemap_entry, partition_sitemap,
    sitemap_entry as _sitemap_entry, write_document, write_index,
)
from .tree_entries import tree_entries
from .source_files import SOURCE_STAGE_PREFIX
from .projection_routes import projection_route_check
from .slugs import normalize_slug
from .translations import TranslationStore, translation_history
from .structured_data import article_jsonld


_ASSET_CACHE_KEY = "assets"
_ASSET_CACHE_VERSION = 1
_OUTPUT_MANIFEST_KEY = "__outputs__"
_SORT_CHUNK_SIZE = 1024
_SORT_MERGE_FAN_IN = 32
_SITEMAP_MAX_URLS = 50_000
_SITEMAP_MAX_BYTES = 52_428_800
_RENDER_INPUT_BUDGET = 64 * 1024 * 1024
_TASK_FRAME = Struct(">QQ")


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
    saxonc_bin: Path | None = None
    # site / URL model
    site_name: str = ""
    base_url: str = ""
    languages: list = field(default_factory=list)
    default_language: str = "en"
    bare_default_language: tuple = ()
    url_patterns: dict = field(default_factory=dict)
    per_page: int = 10
    index_options: IndexOptions = field(default_factory=IndexOptions)
    rss_items: int = 20
    paginate_tags: bool = False
    sitemap_listings: bool = False
    robots_enabled: bool = False
    output_migrations: Optional[OutputMigrations] = None
    previous_translations: dict = field(default_factory=dict)
    translations: Optional[TranslationStore] = None
    extra_pages: tuple[ExtraPage, ...] = ()
    extra_artifacts: tuple[ExtraArtifact, ...] = ()
    retained_page_routes: tuple[Route, ...] = ()
    stylesheet_capture: StylesheetCapture | None = None
    model_projection: ModelProjection | None = None
    cache_retention_days: int = DEFAULT_CACHE_RETENTION_DAYS
    partition_cache: bool = False

    def xsl_for(self, section: str) -> Path:
        return self.xsl_dir / "pages" / SECTION_XSL[section]

    def engine_for(self, section: str) -> TransformEngine | NativeEngine:
        return self.engines[section]


def build_ctx_from_config(config: ConfigurationInput, dry_run: bool) -> BuildCtx:
    """
    Project the raw config dict into a :class:`BuildCtx`.

    Configuration shape and values have already been validated by
    :func:`articulous.config.load_or_create_config`.
    """
    config = admit_configuration(config)
    validate_output_layout(config["paths"])
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
        cache_retention_days=config["build"]["cache_retention_days"],
        partition_cache=config["build"]["partition_cache"],
        engines=engines,
        saxonc_bin=saxonc_bin,
        site_name=config["site"]["site_name"],
        base_url=config["site"]["base_url"],
        languages=list(config["site"]["languages"]),
        default_language=config["site"]["default_language"],
        bare_default_language=tuple(config["site"]["bare_default_language"]),
        url_patterns=dict(config["urls"]),
        per_page=pagination["per_page"],
        index_options=IndexOptions(config['urls'].get('index_first'), pagination.get('empty_index', False)),
        rss_items=pagination["rss_items"],
        paginate_tags=pagination["paginate_tags"],
        sitemap_listings=config["sitemap"]["include_listings"],
        robots_enabled=config["robots"]["enabled"],
    )


# ================================================================
# Asset + URL helpers
# ================================================================

class _AdmittedOutput(NamedTuple):
    path: Path
    relative: str


def _admit_output(ctx: BuildCtx, output_path: Path) -> _AdmittedOutput:
    root = ctx.output_migrations.root if ctx.output_migrations is not None else ctx.output_dir.resolve()
    candidate = output_path if output_path.is_absolute() else ctx.output_dir / output_path
    candidate = Path(os.path.abspath(candidate))
    if not candidate.is_relative_to(root):
        raise ValueError(
            f"Generated output path escapes output_dir: {output_path} "
            f"(output_dir={ctx.output_dir})"
        )
    validate_path_length(candidate)
    if ctx.output_migrations is None:
        validate_output_path(candidate)
    else:
        ctx.output_migrations.admit_path(candidate)
    return _AdmittedOutput(candidate, candidate.relative_to(root).as_posix())


def _asset_manifest(root: Path) -> dict:
    if not root.is_dir():
        raise ValueError(f"Asset source must be a directory: {root}")
    manifest = {}
    for path in sorted(tree_entries(root, skip_directory_prefix=SOURCE_STAGE_PREFIX)):
        rel = path.relative_to(root).as_posix()
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            manifest[rel] = ["d", metadata.st_mtime_ns]
        elif stat.S_ISREG(metadata.st_mode):
            if path.name.startswith(".") and path.name[1:].endswith(".articulous.lock"):
                continue
            manifest[rel] = ["f", metadata.st_size, metadata.st_mtime_ns, file_hash(path), stat.S_IMODE(metadata.st_mode)]
        else:
            raise ValueError(f"Asset symlinks and special files are not supported: {path}")
    return manifest


def _asset_cache_entry(manifest: dict) -> dict:
    return {"version": _ASSET_CACHE_VERSION, "manifest": manifest}


def _asset_target(root: Path, rel: str) -> Path:
    relative = Path(rel)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"Invalid asset output path: {rel}")
    target = root / relative
    for part in (relative, *relative.parents):
        component = root / part
        if component.is_symlink():
            raise ValueError(f"Asset destination contains a symlink: {component}")
        if component.is_file() and component.stat().st_nlink > 1:
            raise ValueError(f"Asset destination contains a hardlink: {component}")
    return target


def _valid_asset_metadata(value) -> bool:
    if not isinstance(value, list) or not value or not isinstance(value[0], str):
        return False
    expected = {"d": (str, int), "f": (str, int, int, str, int)}.get(value[0], ())
    return len(value) == len(expected) and all(
        type(item) is kind for item, kind in zip(value, expected)
    )


def _validated_asset_cache_entry(cache: Optional[dict]) -> Optional[dict]:
    if cache is None:
        return None
    entry = cache.get(_ASSET_CACHE_KEY)
    if not isinstance(entry, dict):
        return None
    if entry.get("version") != _ASSET_CACHE_VERSION:
        return None
    manifest = entry.get("manifest")
    if not isinstance(manifest, dict):
        return None
    if not all(isinstance(key, str) and _valid_asset_metadata(meta) for key, meta in manifest.items()):
        return None
    return entry


def _asset_output_matches(path: Path, metadata: list) -> bool:
    if metadata[0] == "d":
        return path.is_dir()
    if not path.is_file():
        return False
    state = path.stat()
    return (state.st_size == metadata[1] and stat.S_IMODE(state.st_mode) == metadata[4]
            and file_hash(path) == metadata[3])


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
    return entry["manifest"]


def _asset_destination_paths(dest: Path) -> set[str]:
    paths = set()
    for path in tree_entries(dest) if dest.is_dir() else ():
        rel = path.relative_to(dest).as_posix()
        _asset_target(dest, rel)
        paths.add(rel)
    return paths


def _prepare_asset_type(path: Path, directory: bool, root: Path) -> None:
    if path.exists() and path.is_dir() != directory:
        _delete_asset_entry(path, root)


def _remove_asset_type_conflicts(dest: Path, new: dict) -> None:
    for rel, metadata in sorted(new.items()):
        _prepare_asset_type(_asset_target(dest, rel), metadata[0] == "d", dest)


def _copy_asset_delta(
    src: Path, dest: Path, old: dict, new: dict, refresh: set[str], stale: set[str],
) -> None:
    _prepare_asset_type(dest, True, dest.parent)
    dest.mkdir(parents=True, exist_ok=True)
    for rel in sorted(stale, reverse=True):
        target = _asset_target(dest, rel)
        _delete_asset_entry(target, dest)
    _remove_asset_type_conflicts(dest, new)
    for rel, meta in sorted(new.items()):
        target = _asset_target(dest, rel)
        if meta[0] == "d":
            target.mkdir(parents=True, exist_ok=True)
        elif old.get(rel) != meta or rel in refresh:
            copy_asset_file(src / rel, target)


def _prune_missing_assets(ctx: BuildCtx, dest: Path, cache: Optional[dict], before_mutation) -> None:
    if ctx.dry_run:
        logging.debug(f"[DRY RUN] Would remove stale assets output: {dest}")
        return
    if dest.exists():
        if before_mutation is not None:
            before_mutation()
        _delete_asset_entry(dest, ctx.output_dir.resolve())
        logging.info(f"Removed stale assets output: {dest}")
    if cache is not None:
        cache.pop(_ASSET_CACHE_KEY, None)


def copy_assets(ctx: BuildCtx, cache: Optional[dict] = None, *, before_mutation=None) -> None:
    """
    Mirror ``ctx.assets_dir`` into ``<output_dir>/assets``.
    If the source is missing, remove stale copied assets; honours dry-run.
    """
    dest = _admit_output(ctx, _asset_target(ctx.output_dir, "assets")).path
    destination_paths = _asset_destination_paths(dest)
    if not ctx.assets_dir.exists():
        logging.debug(f"Assets directory not present, skipping: {ctx.assets_dir}")
        _prune_missing_assets(ctx, dest, cache, before_mutation)
        return
    _mirror_existing_assets(ctx, cache, dest, destination_paths, before_mutation)


def _mirror_existing_assets(ctx, cache, dest, destination_paths, before_mutation):
    assert_disjoint_trees(ctx.assets_dir, dest)
    manifest = _asset_manifest(ctx.assets_dir)
    old_manifest = _cached_asset_manifest(cache)
    for rel in old_manifest.keys() | manifest.keys():
        _asset_target(dest, rel)
    stale = destination_paths - manifest.keys()

    if ctx.dry_run:
        logging.debug(f"[DRY RUN] Would copy assets: {ctx.assets_dir} -> {dest}")
        return

    mismatches = set(manifest) if ctx.force else _asset_output_mismatches(dest, manifest)
    if not stale and dest.is_dir() and _assets_unchanged(cache, manifest, ctx, mismatches):
        logging.debug("Skipping unchanged assets")
        return

    if before_mutation is not None:
        before_mutation()
    _copy_asset_delta(ctx.assets_dir, dest, old_manifest, manifest, mismatches, stale)
    if cache is not None:
        cache[_ASSET_CACHE_KEY] = _asset_cache_entry(manifest)
    logging.info(f"Copied assets: {ctx.assets_dir} -> {dest}")


def _article_url_builder(ctx: BuildCtx):
    """
    Return a ``(lang, slug) -> url`` callable bound to ``ctx``. Used by
    :func:`iter_articles` so each :class:`Article` is constructed with
    its public URL already attached.
    """
    base_url = ctx.base_url

    def build(lang: str, slug: str) -> str:
        pattern = section_pattern(ctx, "articles", lang)
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


def _sitemap_url_xml(value) -> str:
    url, modified = _sitemap_entry(value)
    attrs = f" lastmod={_xml_attr(modified)}" if modified else ""
    return f"<url{attrs}>{_xml_escape(url)}</url>"


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
        f"self={_xml_attr(page.url)} "
        f"previous={_xml_attr(page.previous_url)} next={_xml_attr(page.next_url)}"
    )
    return _xml_doc(
        "index", [_article_xml(a) for a in page.articles], attrs,
    )


def _tag_doc(page, site_name: str) -> str:
    attrs = (
        f" site={_xml_attr(site_name)} "
        f"lang={_xml_attr(page.lang)} "
        f"slug={_xml_attr(page.tag_slug)} "
        f'page="{page.page}" total="{page.total_pages}" '
        f"self={_xml_attr(page.url)} "
        f"previous={_xml_attr(page.previous_url)} next={_xml_attr(page.next_url)}"
    )
    children = [f"<display-name>{_xml_escape(page.tag)}</display-name>"]
    children.extend(_article_xml(a) for a in page.articles)
    return _xml_doc("tag", children, attrs)


def _rss_doc(feed, site_name: str, lang: str | None = None) -> str:
    attrs = f" site={_xml_attr(site_name)} self={_xml_attr(feed.url)}"
    if lang:
        attrs += f" lang={_xml_attr(lang)}"
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


class _JsonLinesSink:
    def __init__(self, workspace: TempWorkspace):
        self._workspace = workspace
        self._file: Any = None
        self.count = 0

    def _open_file(self):
        if self._file is None:
            self._file = self._workspace.named_file("w+", encoding="utf-8")
        return self._file

    @property
    def path(self) -> Path:
        return Path(self._open_file().name)

    def append(self, value) -> None:
        self._open_file().write(json.dumps(value, ensure_ascii=False) + "\n")
        self.count += 1

    def values(self):
        self.flush()
        with self.path.open(encoding="utf-8") as source:
            for line in source:
                yield json.loads(line)

    def flush(self) -> None:
        if self._file is not None:
            self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()

    def __len__(self) -> int:
        return self.count

    def __eq__(self, other) -> bool:
        return self.count == 0 and other == []


class SitemapSink(_JsonLinesSink):
    def append_url(self, url: str, modified: str = "") -> None:
        self.append({"url": url, "modified": modified} if modified else url)


class SearchSink(_JsonLinesSink):
    def append_item(self, item: dict) -> None:
        self.append(item)


class SortedArticleBatch:
    def __init__(self, chunks: list[tuple[Path, int]], count: int):
        self._chunks = chunks
        self._count = count

    def __iter__(self):
        yield from _merge_sorted_chunks(self._chunks)

    def __len__(self) -> int:
        return self._count

    def __eq__(self, other) -> bool:
        return self._count == 0 and other == []

    def discard_chunks(self) -> None:
        for path, _ in self._chunks:
            path.unlink()


@dataclass
class _ListedArticles:
    articles: SortedArticleBatch
    count: int

    def __iter__(self):
        with closing(iter(self.articles)) as articles:
            yield from filter(attrgetter("policy.listing"), articles)

    def __len__(self):
        return self.count


def _write_sorted_article_chunk(workspace: TempWorkspace, articles: list) -> tuple[Path, int]:
    articles.sort(key=attrgetter("datetime"), reverse=True)
    with workspace.named_file("w+b") as f:
        for art in articles:
            pickle.dump(art, f)
        return Path(f.name), len(articles)


def _merge_sorted_chunks(chunks):
    streams = [_read_pickled_articles(path, count) for path, count in chunks]
    try:
        yield from heapq.merge(*streams, key=attrgetter("datetime"), reverse=True)
    finally:
        for stream in streams:
            stream.close()


def _merge_chunk_group(workspace: TempWorkspace, chunks) -> tuple[Path, int]:
    with workspace.named_file("w+b") as output:
        for article in _merge_sorted_chunks(chunks):
            pickle.dump(article, output)
        return Path(output.name), sum(count for _, count in chunks)


def _consolidate_sorted_chunks(workspace: TempWorkspace, chunks):
    while len(chunks) > _SORT_MERGE_FAN_IN:
        merged = [
            _merge_chunk_group(workspace, chunks[start:start + _SORT_MERGE_FAN_IN])
            for start in range(0, len(chunks), _SORT_MERGE_FAN_IN)
        ]
        for path, _ in chunks:
            path.unlink()
        chunks = merged
    return chunks


class ArticleStore:
    def __init__(self, workspace: TempWorkspace, cache=None):
        self._cache = cache
        self._workspace = workspace
        self._files: dict[str, Any] = {}
        self._sources: Any = None
        self.counts: dict[str, int] = {}

    def _snapshot_article(self, art):
        if not isinstance(art.source_xml, bytes):
            return art
        content = art.source_xml
        fingerprint = hashlib.sha256(content).hexdigest()
        key = f"article:{art.lang}:{art.slug}"
        record = self._cache.get(key) if self._cache is not None else None
        if isinstance(record, list) and record[:1] == [fingerprint]:
            snapshot = ArticleSnapshot(art.source_path, 0, len(content), fingerprint, whole_file=True)
            return replace(art, source_xml=snapshot)
        if self._sources is None:
            self._sources = self._workspace.named_file("w+b")
        snapshot = ArticleSnapshot(
            Path(self._sources.name), self._sources.tell(), len(content),
            fingerprint,
        )
        self._sources.write(content)
        return replace(art, source_xml=snapshot)

    def append(self, lang: str, art) -> None:
        f = self._files.get(lang)
        if f is None:
            f = self._workspace.named_file("w+b")
            self._files[lang] = f
        pickle.dump(self._snapshot_article(art), f)
        self.counts[lang] = self.counts.get(lang, 0) + 1

    def iter_lang(self, lang: str):
        f = self._files.get(lang)
        if f is None:
            return
        if self._sources is not None:
            self._sources.flush()
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
        return SortedArticleBatch(
            _consolidate_sorted_chunks(self._workspace, chunks), self.counts.get(lang, 0),
        )

    def close(self) -> None:
        for f in self._files.values():
            f.close()
        if self._sources is not None:
            self._sources.close()


class _OutputRecorder(Protocol):
    def record(self, cache_key: str, relpath: str, route: Route | None = None) -> None:
        ...


class _ListingRecords:
    def __init__(self):
        self.records: list[tuple[str, str, Route | None]] = []

    def record(self, cache_key: str, relpath: str, route: Route | None = None) -> None:
        self.records.append((cache_key, relpath, route))

    def replay(self, manifest: _OutputRecorder | None) -> None:
        if manifest is not None:
            for record in self.records:
                manifest.record(*record)


def _record_output_path(owners: dict, relpath: str) -> None:
    *parents, leaf = Path(relpath).parts
    for part in parents:
        child = owners.setdefault(part, {})
        if child is None:
            raise ValueError(f"Duplicate generated output path: {relpath}")
        owners = child
    if leaf in owners:
        raise ValueError(f"Duplicate generated output path: {relpath}")
    owners[leaf] = None


class OutputManifest(dict):
    def __init__(self, ctx=None, catalog: RouteWriter | None = None, *, route_store: RouteWriter | None = None):
        super().__init__()
        self._owners: dict = {}
        self.ctx = ctx
        self.catalog = catalog
        self._route_store = route_store
        self._routes: dict[str, Route] = {}

    def reserve_path(self, relpath: str) -> None:
        _record_output_path(self._owners, relpath)

    def record(self, cache_key: str, relpath: str, route: Route | None = None) -> None:
        if cache_key in self:
            raise ValueError(f"Duplicate generated cache key: {cache_key}")
        self.reserve_path(relpath)
        super().__setitem__(cache_key, relpath)
        if self.ctx is not None:
            self.record_route(route or route_from_output(self.ctx.base_url, cache_key, relpath))

    def record_route(self, route: Route) -> None:
        if self._route_store is None:
            self._routes[route.key] = route
        else:
            self._route_store.record(route)
        if self.catalog is not None:
            self.catalog.record(route)

    def route_values(self):
        if self._route_store is None:
            return MappingProxyType(self._routes)
        return MappingProxyType({route.key: route for route in self._route_store})


def _read_pickled_articles(path: Path, count: int):
    with path.open("rb") as f:
        for _ in range(count):
            yield pickle.load(f)


def _write_sitemap_model_file(
    workspace: TempWorkspace, attrs: str, sink: SitemapSink,
) -> Path:
    with workspace.named_file("w", encoding="utf-8") as out:
        out.write(f"<sitemap{attrs}>")
        for url in sink.values():
            out.write(_sitemap_url_xml(url))
        out.write("</sitemap>")
        return Path(out.name)


def _write_search_json_xml(out, sink: SearchSink) -> None:
    out.write("[\n")
    for index, item in enumerate(sink.values()):
        if index:
            out.write(",\n")
        out.write(_xml_escape(json.dumps(item, ensure_ascii=False)))
    out.write("\n]")


def _write_search_model_file(
    workspace: TempWorkspace, attrs: str, sink: SearchSink,
) -> Path:
    with workspace.named_file("w", encoding="utf-8") as out:
        out.write(f"<search{attrs}><json>")
        _write_search_json_xml(out, sink)
        out.write("</json>")
        for item in sink.values():
            out.write(_search_item_xml(item))
        out.write("</search>")
        return Path(out.name)


def _source_values(source):
    if isinstance(source, _JsonLinesSink):
        return source.values()
    return iter(source)


def _source_hash(source) -> str:
    if isinstance(source, bytes):
        return hashlib.sha256(source).hexdigest()
    if isinstance(source, SitemapSlice):
        return source.fingerprint
    if isinstance(source, _JsonLinesSink):
        source.flush()
        return file_hash(source.path)
    digest = hashlib.sha256()
    for value in source:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()
        digest.update(encoded)
        digest.update(b"\n")
    return digest.hexdigest()


def _write_native_sitemap(output_path: Path | StagedOutput, source) -> None:
    if isinstance(source, SitemapSlice):
        source.write(output_path)
        return
    write_document(
        output_path, _source_values(source), "urlset", _native_sitemap_entry,
        _SITEMAP_MAX_URLS, _SITEMAP_MAX_BYTES,
    )


def _write_native_search(output_path: Path | StagedOutput, source) -> None:
    with output_path.open("w", encoding="utf-8") as out:
        out.write("[\n")
        for index, item in enumerate(_source_values(source)):
            if index:
                out.write(",\n")
            out.write(json.dumps(item, ensure_ascii=False))
        out.write("\n]")


def _write_robots(output_path: Path | StagedOutput, source) -> None:
    output_path.write_text(f"User-agent: *\nAllow: /\nSitemap: {source[0]}\n", encoding="utf-8")


def _build_robots(ctx: BuildCtx, cache, manifest) -> list:
    if not ctx.robots_enabled:
        return []
    url = build_url_from_pattern(ctx.base_url, ctx.url_patterns["sitemap"])
    validate_sitemap_location(url)
    task = _make_native_task(
        source=[url], output_path=ctx.output_dir / "robots.txt", cache=cache,
        cache_key="sitemap:robots", engine=NativeEngine(), writer=_write_robots,
        ctx=ctx, manifest=manifest,
    )
    return [task] if task is not None else []


# ================================================================
# Shared XSLT task plumbing
# ================================================================

@dataclass(frozen=True)
class _TransformSpec:
    xml_input: Path | bytes | ArticleSnapshot
    xsl_path: Path
    output_path: Path
    cache_key: str
    fingerprint: tuple
    xml_base_uri: Optional[str] = None
    parameters: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _XsltTask:
    spec: _TransformSpec
    engine: TransformEngine
    ctx: BuildCtx
    cache: dict

    def __call__(self) -> None:
        timed(self.spec.cache_key, self._run)()

    def _run(self) -> None:
        revision = self.engine.resolve_stylesheet_fingerprint(self.spec.xsl_path, self.spec.fingerprint[1])
        source, source_hash = self._model()
        fingerprint = (source_hash, revision, *self.spec.fingerprint[2:])
        self.engine.run(
            source,
            self.spec.xsl_path,
            self.spec.output_path,
            dry_run=self.ctx.dry_run,
            stylesheet_fingerprint=revision,
            xml_base_uri=self.spec.xml_base_uri,
            parameters=self.spec.parameters,
        )
        update_cache(self.cache, self.spec.cache_key, fingerprint)

    def _model(self):
        source = self.spec.xml_input
        if isinstance(source, ArticleSnapshot):
            source = source.read_bytes()
        if self.ctx.model_projection is None or not isinstance(source, bytes):
            return source, self.spec.fingerprint[0]
        model = ModelInput(source, _admit_output(self.ctx, self.spec.output_path).relative,
                           self.spec.parameters)
        source = self.ctx.model_projection(model)
        if not isinstance(source, bytes):
            raise ValueError('Model projection must return XML bytes')
        return source, hashlib.sha256(source).hexdigest()


def _input_bytes(source):
    if isinstance(source, ArticleSnapshot):
        return source.size
    if isinstance(source, bytes):
        return len(source)
    return source.stat().st_size


class _TaskQueue:
    def __init__(self, ctx: BuildCtx, cache: dict):
        self._ctx = ctx
        self._cache = cache
        self._engines: dict[int, TransformEngine] = {}
        self._file = tempfile.TemporaryFile(mode="w+b")
        self._count = 0

    def append(self, task: _XsltTask) -> None:
        key = id(task.engine)
        self._engines[key] = task.engine
        start = self._file.tell()
        self._file.write(_TASK_FRAME.pack(0, 0))
        pickle.dump((key, task.spec), self._file)
        end = self._file.tell()
        length = end - start - _TASK_FRAME.size
        self._file.seek(start)
        self._file.write(_TASK_FRAME.pack(length, length + _input_bytes(task.spec.xml_input)))
        self._file.seek(end)
        self._count += 1

    def extend(self, tasks) -> None:
        for task in tasks:
            self.append(task)

    def __len__(self) -> int:
        return self._count

    def _entry(self, stored):
        key, spec = stored
        return _XsltTask(spec, self._engines[key], self._ctx, self._cache)

    def __iter__(self):
        try:
            self._file.seek(0)
            for _ in range(self._count):
                self._file.read(_TASK_FRAME.size)
                yield self._entry(pickle.load(self._file))
        finally:
            self.close()

    def _run_at(self, offset, length):
        descriptor = self._file.fileno()
        payload = os.pread(descriptor, length, offset)
        if len(payload) != length:
            payload = _complete_task_payload(descriptor, payload, offset, length)
        self._entry(pickle.loads(payload))()

    def admitted(self):
        self._file.seek(0)
        for _ in range(self._count):
            length, weight = _TASK_FRAME.unpack(self._file.read(_TASK_FRAME.size))
            offset = self._file.tell()
            self._file.seek(length, os.SEEK_CUR)
            yield WeightedTask(weight, partial(self._run_at, offset, length))

    def close(self) -> None:
        self._file.close()


def _complete_task_payload(descriptor, initial, offset, length):
    result = bytearray(initial)
    while len(result) < length:
        chunk = os.pread(descriptor, length - len(result), offset + len(result))
        if not chunk:
            raise ValueError("Task spool truncated")
        result.extend(chunk)
    return result


def _admitted_tasks(plan):
    for tasks in plan.values():
        if isinstance(tasks, _TaskQueue):
            yield from tasks.admitted()
        else:
            yield from _weighted_direct_tasks(tasks)


def _weighted_direct_tasks(tasks):
    for task in tasks:
        if isinstance(task, _XsltTask):
            yield WeightedTask(_input_bytes(task.spec.xml_input), task)
        else:
            yield task


def _record_planned_output(
    manifest: Optional[_OutputRecorder],
    ctx: BuildCtx,
    cache_key: str,
    output_path: Path | _AdmittedOutput,
    route: Route | None = None,
) -> _AdmittedOutput:
    output = output_path if isinstance(output_path, _AdmittedOutput) else _admit_output(ctx, output_path)
    if Path(output.relative).parts[:1] == ("assets",):
        raise ValueError(f"Generated output uses the reserved assets directory: {output.relative}")
    if route is not None and (route.key, route.output_path) != (cache_key, output.relative):
        raise ValueError(f"Route does not match planned output: {output.relative}")
    if manifest is not None:
        manifest.record(cache_key, output.relative, route)
    return output


def _needs_output_rebuild(ctx: BuildCtx, cache_key, cache, fingerprint, output_path: Path) -> bool:
    if ctx.output_migrations is not None and ctx.output_migrations.admitted_requires_rebuild(output_path):
        return True
    return _admitted_rebuild(cache_key, cache, fingerprint, ctx.force, output_path)


def _transform_input_hash(source: Path | bytes | ArticleSnapshot) -> str:
    if isinstance(source, ArticleSnapshot):
        return source.fingerprint
    if isinstance(source, bytes):
        return hashlib.sha256(source).hexdigest()
    return file_hash(source)


def _make_xslt_task(
    *,
    xml_input: Path | bytes | ArticleSnapshot,
    xsl_path: Path,
    xsl_hash: str,        # PERF-01: caller hashes the section's XSL once
    output_path: Path | _AdmittedOutput,
    cache: dict,
    cache_key: str,
    engine: TransformEngine,
    ctx: BuildCtx,
    manifest: Optional[_OutputRecorder] = None,
    xml_base_uri: Optional[str] = None,
    parameters: Optional[dict[str, str]] = None,
    route: Route | None = None,
) -> Optional[_XsltTask]:
    """
    Return a transform task for an XSLT-driven section, or ``None`` if
    the cache says the output is up to date.

    Captured articles already have a digest and are read only for a queued
    transform. Bytes are hashed directly and file-backed models are hashed
    through their path.

    ``xsl_hash`` is precomputed by the caller so per-section XSL hashing
    is amortised across every page in that section.

    The returned task updates its in-memory cache entry after a successful
    transform. The pipeline saves the cache after the build succeeds;
    a failed transform leaves its prior in-memory entry intact.
    """
    output_path, relpath = _record_planned_output(manifest, ctx, cache_key, output_path, route)
    xml_hash = _transform_input_hash(xml_input)

    fingerprint = (xml_hash, xsl_hash, engine.cache_identity, relpath)
    if parameters:
        fingerprint += (json.dumps(parameters, sort_keys=True),)
    if xml_base_uri is not None:
        fingerprint += (xml_base_uri,)
    projected = ctx.model_projection is not None and isinstance(xml_input, (bytes, ArticleSnapshot))
    if not projected and not _needs_output_rebuild(ctx, cache_key, cache, fingerprint, output_path):
        return None

    spec = _TransformSpec(xml_input, xsl_path, output_path, cache_key, fingerprint, xml_base_uri, parameters or {})
    return _XsltTask(spec, engine, ctx, cache)


def _make_native_task(
    *,
    source,
    output_path: Path,
    cache: dict,
    cache_key: str,
    engine: NativeEngine,
    writer: Callable,
    ctx: BuildCtx,
    manifest: Optional[_OutputRecorder] = None,
    route: Route | None = None,
) -> Optional[Callable]:
    output_path, relpath = _record_planned_output(
        manifest, ctx, cache_key, output_path, route,
    )
    fingerprint = (_source_hash(source), engine.cache_identity, relpath)
    if not _needs_output_rebuild(ctx, cache_key, cache, fingerprint, output_path):
        return None

    def task(output_path=output_path):
        if not ctx.dry_run:
            with atomic_output(output_path, generated=True) as staged:
                writer(staged, source)
        update_cache(cache, cache_key, fingerprint)

    invoke = timed(cache_key, task)
    return WeightedTask(len(source), invoke) if isinstance(source, bytes) else invoke


# ================================================================
# Section builders
# ================================================================

def _encode_xml(content: str) -> bytes:
    return content.encode("utf-8")


def _section_runtime(ctx: BuildCtx, section: str) -> tuple[Path, str, TransformEngine]:
    xsl_path = ctx.xsl_for(section)
    engine = require_transform(ctx.engine_for(section))
    return xsl_path, engine.prepare_stylesheet(xsl_path), engine


def _append_task(tasks: _TaskQueue, task: Optional[_XsltTask], skip_message: str) -> None:
    if task is None:
        logging.debug(skip_message)
        return
    tasks.append(task)


def _article_input(art) -> bytes:
    if art.source_xml is None:
        with open_regular_file(art.source_path) as source:
            return source.read()
    if isinstance(art.source_xml, bytes):
        return art.source_xml
    return art.source_xml.read_bytes()


def _article_parameters(art, ctx: BuildCtx) -> dict[str, str]:
    return {
        "articulous-url": art.url,
        "articulous-lang": art.lang,
        "articulous-site": ctx.site_name,
        "articulous-indexing": art.indexing,
        "articulous-translation": art.translation,
        "articulous-alternates": _article_alternates(art, ctx),
        "articulous-jsonld": article_jsonld(art),
        "articulous-title": art.title,
        "articulous-description": art.description,
        "articulous-author": art.author,
        "articulous-image": art.image,
        "articulous-published": art.datetime.isoformat(),
        "articulous-modified": art.modified,
    }


def _article_alternates(art, ctx: BuildCtx) -> str:
    if ctx.translations is None or not art.indexable:
        return ""
    return ctx.translations.markup(art.translation)


def build_articles_section(lang_articles, ctx: BuildCtx, cache, manifest=None, tasks=None):
    """
    Build article pages for one language's article batch.

    The planner supplies a sorted, filtered article batch for one
    language. The returned task queue is spooled to a temporary file.
    """
    xsl_path, xsl_hash, engine = _section_runtime(ctx, "articles")
    if tasks is None:
        tasks = _TaskQueue(ctx, cache)

    for art in lang_articles:
        relative_path = build_output_path_from_pattern(
            "articles", section_pattern(ctx, "articles", art.lang), lang=art.lang, slug=art.slug,
        )
        output = _admit_output(ctx, ctx.output_dir / relative_path)
        source = art.source_xml
        task = _make_xslt_task(
            xml_input=source if isinstance(source, ArticleSnapshot) else _article_input(art),
            parameters=_article_parameters(art, ctx),
            xml_base_uri=art.source_base_uri or art.source_path.resolve().as_uri(),
            xsl_path=xsl_path,
            xsl_hash=xsl_hash,
            output_path=output,
            cache=cache,
            cache_key=f"article:{art.lang}:{art.slug}",
            route=Route(f'article:{art.lang}:{art.slug}', 'articles', art.url,
                        output.relative, art.lang, 'article', art.policy.sitemap),
            engine=engine,
            ctx=ctx,
            manifest=manifest,
        )
        _append_task(tasks, task, f"Skipping unchanged article: {art.slug}")

    return tasks


def build_index_section(lang_articles, lang: str, ctx: BuildCtx, cache, manifest=None, tasks=None, *, pages=None):
    """Build paginated index pages for one language."""
    xsl_path, xsl_hash, engine = _section_runtime(ctx, "index")
    if tasks is None:
        tasks = _TaskQueue(ctx, cache)

    if pages is None:
        pages = build_index_models(lang_articles, lang, ctx)
    for page in pages:
        xml_bytes = _encode_xml(_index_doc(page, ctx.site_name))
        output = _admit_output(ctx, ctx.output_dir / page.output_path)
        cache_key = f"index:{page.lang}:{page.page}"
        task = _make_xslt_task(
            xml_input=xml_bytes,
            xsl_path=xsl_path,
            xsl_hash=xsl_hash,
            output_path=output,
            cache=cache,
            cache_key=cache_key,
            route=Route(cache_key, 'index', page.url, output.relative, page.lang, 'listing'),
            engine=engine,
            ctx=ctx,
            manifest=manifest,
        )
        _append_task(tasks, task, f"Skipping unchanged index page {page.page}")

    return tasks


def _tag_cache_key(page) -> str:
    key = f"tag:{page.lang}:{page.tag_slug}"
    return key if page.page == 1 else f"{key}/page/{page.page}"


def build_tags_section(lang_articles, lang: str, ctx: BuildCtx, cache, manifest=None, tasks=None, *, pages=None):
    """Build tag pages for one language."""
    xsl_path, xsl_hash, engine = _section_runtime(ctx, "tags")
    if tasks is None:
        tasks = _TaskQueue(ctx, cache)

    if pages is None:
        pages = _iter_tag_pages(lang_articles, lang, ctx, paginate=ctx.paginate_tags)
    for page in pages:
        xml_bytes = _encode_xml(_tag_doc(page, ctx.site_name))
        output = _admit_output(ctx, ctx.output_dir / page.output_path)
        cache_key = _tag_cache_key(page)
        task = _make_xslt_task(
            xml_input=xml_bytes,
            xsl_path=xsl_path,
            xsl_hash=xsl_hash,
            output_path=output,
            cache=cache,
            cache_key=cache_key,
            route=Route(cache_key, 'tags', page.url, output.relative, page.lang, 'listing'),
            engine=engine,
            ctx=ctx,
            manifest=manifest,
        )
        _append_task(
            tasks, task,
            f"Skipping unchanged tag page: {page.lang}/{page.tag_slug}",
        )

    return tasks


def rss_is_per_lang(ctx: BuildCtx) -> bool:
    """A site opts into one feed per language by naming {lang} in urls.rss."""
    return section_is_per_lang("rss", ctx.url_patterns["rss"])


def build_rss_section(rss_articles, ctx: BuildCtx, cache, manifest=None, tasks=None):
    """
    Build the RSS feed. ``rss_articles`` is the already-selected top-N
    list (newest first) produced by :func:`_stream_projections`, or a
    mapping of language to such a list when the site publishes one feed
    per language.
    """
    if tasks is None:
        tasks = []
    if not rss_is_per_lang(ctx):
        tasks.extend(_build_rss_feed(rss_articles, ctx, cache, manifest))
        return tasks
    # Every enabled language gets a feed, so a reader can subscribe before the
    # first article in that language exists.
    for lang in ctx.languages:
        tasks.extend(_build_rss_feed(
            rss_articles.get(lang, ()), ctx, cache, manifest, lang,
        ))
    return tasks


def _build_rss_feed(articles, ctx: BuildCtx, cache, manifest, lang=None) -> list:
    feed = build_rss_model(articles, ctx, lang)
    xml_bytes = _encode_xml(_rss_doc(feed, ctx.site_name, lang))
    return _single_xslt_section(
        "rss", xml_bytes, ctx.output_dir / feed.output_path,
        "rss" if lang is None else f"rss:{lang}",
        "Skipping unchanged RSS feed", ctx, cache, manifest,
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


def _single_native_section(
    section: str,
    source,
    output_path: Path,
    writer: Callable,
    ctx: BuildCtx,
    cache,
    manifest,
) -> list:
    engine = ctx.engine_for(section)
    assert isinstance(engine, NativeEngine)
    task = _make_native_task(
        source=source,
        output_path=output_path,
        cache=cache,
        cache_key=section,
        engine=engine,
        writer=writer,
        ctx=ctx,
        manifest=manifest,
    )
    if task is None:
        logging.debug(f"Skipping unchanged {section}")
        return []
    return [task]


def _validated_sitemap_source(base_url: str, sitemap_url: str, source):
    validate_sitemap_location(base_url)
    validate_sitemap_location(sitemap_url)
    sitemap = urlsplit(sitemap_url)
    origin = url_origin(sitemap)
    prefix = sitemap.path.rsplit("/", 1)[0] + "/"
    for value in _source_values(source):
        url, _ = _sitemap_entry(value)
        validate_sitemap_location(url)
        location = urlsplit(url)
        if url_origin(location) != origin or not (location.path or "/").startswith(prefix):
            raise ValueError(f"Sitemap URL is outside its host or directory scope: {url}")
        yield value


def _require_workspace(workspace):
    if not isinstance(workspace, TempWorkspace):
        raise TypeError("workspace must be a TempWorkspace")


def build_sitemap_section(urls, ctx: BuildCtx, cache, workspace=None, manifest=None):
    """Build sitemap.xml from a streamed list of URL strings."""
    if workspace is not None:
        _require_workspace(workspace)
    sitemap = build_sitemap_model([], ctx)
    if isinstance(ctx.engine_for("sitemap"), NativeEngine):
        with closing(_validated_sitemap_source(ctx.base_url, sitemap.url, urls)) as validated:
            if isinstance(workspace, TempWorkspace):
                return _build_partitioned_sitemap(validated, sitemap, ctx, cache, workspace, manifest)
            source = [value.copy() if isinstance(value, dict) else value for value in validated]
        return _single_native_section(
            "sitemap", source, ctx.output_dir / sitemap.output_path,
            _write_native_sitemap, ctx, cache, manifest,
        )
    if isinstance(urls, SitemapSink):
        assert isinstance(workspace, TempWorkspace)
        attrs = f" site={_xml_attr(ctx.site_name)} self={_xml_attr(sitemap.url)}"
        xml_input = _write_sitemap_model_file(workspace, attrs, urls)
    else:
        sitemap = build_sitemap_model(urls, ctx)
        xml_input = _encode_xml(_sitemap_doc(sitemap, ctx.site_name))
    return _single_xslt_section(
        "sitemap", xml_input, ctx.output_dir / sitemap.output_path,
        "sitemap", "Skipping unchanged sitemap", ctx, cache, manifest,
    )


@dataclass(frozen=True)
class _SitemapIndex:
    sitemap: Sitemap
    shards: tuple[SitemapSlice, ...]

    def entry(self, index, shard):
        stem = self.sitemap.output_path.stem[:40]
        filename = f"{stem}-{index:05d}-{shard.fingerprint}.xml"
        prefix = self.sitemap.url.rsplit("/", 1)[0] + "/"
        return filename, prefix + quote(filename, safe="")

    def __iter__(self):
        for index, shard in enumerate(self.shards, 1):
            yield self.entry(index, shard)[1]


def _build_partitioned_sitemap(source, sitemap, ctx, cache, workspace, manifest):
    shards = partition_sitemap(workspace, source, _SITEMAP_MAX_URLS, _SITEMAP_MAX_BYTES)
    if len(shards) == 1:
        return _single_native_section(
            "sitemap", shards[0], ctx.output_dir / sitemap.output_path,
            _write_native_sitemap, ctx, cache, manifest,
        )
    tasks = []
    index_source = _SitemapIndex(sitemap, tuple(shards))
    for index, shard in enumerate(shards, start=1):
        filename, url = index_source.entry(index, shard)
        validate_sitemap_location(url)
        task = _make_native_task(
            source=shard, output_path=ctx.output_dir / sitemap.output_path.parent / filename,
            cache=cache, cache_key=f"sitemap:shard:{index}", engine=ctx.engine_for("sitemap"),
            writer=_write_native_sitemap, ctx=ctx, manifest=manifest,
        )
        if task is not None:
            tasks.append(task)
    tasks.extend(_single_native_section(
        "sitemap", index_source, ctx.output_dir / sitemap.output_path, write_index, ctx, cache, manifest,
    ))
    return [_sequential_tasks(tasks)] if tasks else []


def _sequential_tasks(tasks):
    def run():
        for task in tasks:
            task()
    return run


def build_search_section(items, ctx: BuildCtx, cache, workspace=None, manifest=None):
    """Build the search output with the configured native or XSLT engine."""
    if workspace is not None:
        _require_workspace(workspace)
    index = build_search_model([], ctx)
    if isinstance(ctx.engine_for("search"), NativeEngine):
        source = items if isinstance(items, SearchSink) else list(items)
        return _single_native_section(
            "search", source, ctx.output_dir / index.output_path,
            _write_native_search, ctx, cache, manifest,
        )
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

def _default_sections():
    return frozenset(SECTION_NAMES)


@dataclass
class StreamProjection:
    sitemap_urls: SitemapSink
    search_items: SearchSink
    rss_heap: list
    total: int
    # Filled instead of rss_heap when the site publishes one feed per language.
    rss_by_lang: dict = field(default_factory=dict)
    skipped_by_publication: dict = field(default_factory=dict)
    articles_by_lang: ArticleStore | None = None
    listings_by_lang: ArticleStore | None = None
    sections: frozenset[str] = field(default_factory=_default_sections)
    sitemap_listings: bool = False
    translations: Optional[TranslationStore] = None
    shared_listing_counts: dict[str, int] | None = None

    def listing_batch(self, lang, articles):
        if self.shared_listing_counts is None:
            return _sorted_store_articles(self.listings_by_lang, lang)
        count = self.shared_listing_counts.get(lang, 0)
        if not count:
            return []
        return articles if len(articles) == count else _ListedArticles(articles, count)


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


def _projection_sections(cli, collect_cross: bool, collect_articles: bool) -> frozenset[str]:
    enabled = set()
    if collect_cross:
        enabled.update(CROSS_LANG_SECTIONS)
    if collect_articles:
        enabled.update(PER_LANG_SECTIONS)
    return frozenset(enabled.intersection(cli.only_sections or SECTION_NAMES))


def _listing_storage(workspace, sections, sitemap_listings, article_store, cli):
    if not (sitemap_listings or sections.intersection({"index", "tags"})):
        return None, None
    if article_store is not None and not (cli.only_langs or cli.only_slugs):
        return None, {}
    return ArticleStore(workspace), None


def _stream_projections(
    stream_factory,
    cli,
    ctx: BuildCtx,
    workspace: TempWorkspace | None = None,
    *,
    cache=None,
    check_route=None,
    collect_cross: bool = True,
    collect_articles: bool = False,
) -> StreamProjection:
    """
    Single article pass with complete shared projections.

    Sitemap/search use disk-backed sinks and RSS uses a bounded heap.
    Unfiltered listings borrow the sorted article batch. Filtered builds
    spool complete listings separately from selected article snapshots.
    """
    workspace = workspace or TempWorkspace()
    sections = _projection_sections(cli, collect_cross, collect_articles)
    article_store = ArticleStore(workspace, cache) if "articles" in sections else None
    sitemap_listings = ctx.sitemap_listings and "sitemap" in sections
    listing_store, listing_counts = _listing_storage(workspace, sections, sitemap_listings, article_store, cli)
    projection = StreamProjection(
        SitemapSink(workspace), SearchSink(workspace), [], 0,
        articles_by_lang=article_store,
        listings_by_lang=listing_store,
        shared_listing_counts=listing_counts,
        sections=sections,
        sitemap_listings=sitemap_listings,
        translations=TranslationStore() if "articles" in sections else None,
    )
    try:
        _fill_projection(projection, stream_factory, cli, ctx, check_route)
    except BaseException:
        _cleanup_stream_projection(projection)
        raise
    return projection


def _declared_page_routes(ctx):
    for page in ctx.extra_pages:
        validate_page_url(page, ctx.base_url)
        yield page.route


def _append_extra_sitemap(projection, ctx):
    for route in chain(_declared_page_routes(ctx), ctx.retained_page_routes):
        if 'sitemap' in projection.sections and route.included(ctx.sitemap_listings):
            projection.sitemap_urls.append_url(route.url)


def _collect_extra_plan(ctx, cache, manifest, tasks):
    engines: dict[str, TransformEngine] = {}
    fingerprints: dict[tuple[str, Path], str] = {}
    for page in ctx.extra_pages:
        if page.engine not in engines:
            engines[page.engine] = _extra_page_engine(ctx, page.engine)
        engine = engines[page.engine]
        xsl_path = Path(os.path.abspath(page.stylesheet))
        key = (page.engine, xsl_path)
        if key not in fingerprints:
            fingerprints[key] = engine.prepare_stylesheet(xsl_path)
        task = _make_xslt_task(
            xml_input=page.model, xsl_path=xsl_path, xsl_hash=fingerprints[key],
            output_path=ctx.output_dir / page.route.output_path, cache=cache,
            cache_key=page.route.key, engine=engine, ctx=ctx, manifest=manifest, route=page.route,
        )
        if task is not None:
            tasks.append(task)
    return tasks


def _extra_page_engine(ctx, name):
    engine = make_engine(name, ctx.saxonc_bin)
    if ctx.stylesheet_capture is not None:
        engine = ctx.stylesheet_capture.wrap(engine)
    return require_transform(engine)


def _write_extra_artifact(output, content):
    with output.open('wb') as destination:
        destination.write(content)


def build_artifacts_section(artifacts, ctx, cache, manifest):
    tasks = []
    for artifact in artifact_values(artifacts):
        path = artifact.output_path
        route = Route('artifact:' + path, 'artifacts', ctx.base_url.rstrip('/') + '/' + quote(path, safe='/'),
                      path, category='excluded', sitemap=False)
        task = _make_native_task(source=artifact.content, output_path=ctx.output_dir / path,
                                 cache=cache, cache_key=route.key, engine=NativeEngine(),
                                 writer=_write_extra_artifact, ctx=ctx, manifest=manifest, route=route)
        if task is not None:
            tasks.append(task)
    return tasks


def _observed_listings(pages, projection, check_route):
    for page in pages:
        if check_route is not None:
            check_route(page.url)
        projection.sitemap_urls.append_url(page.url)
        yield page


def _has_language_work(projection, lang, listings, ctx):
    articles = projection.articles_by_lang
    count = articles.counts.get(lang, 0) if articles is not None else 0
    return bool(count or listings or ctx.index_options.include_empty)


def _shared_listings_for_language(plan, ctx, cache, projection, lang, listings, selected, want, check_route):
    records = _ListingRecords()
    indexes = _observed_listings(build_index_models(listings, lang, ctx), projection, check_route)
    if selected and want("index"):
        build_index_section(listings, lang, ctx, cache, records,
                            _tasks_for(plan, "index", ctx, cache), pages=indexes)
    else:
        for _ in indexes:
            pass
    tags = _observed_listings(_iter_tag_pages(listings, lang, ctx, paginate=ctx.paginate_tags), projection, check_route)
    if selected and want("tags"):
        build_tags_section(listings, lang, ctx, cache, records,
                           _tasks_for(plan, "tags", ctx, cache), pages=tags)
    else:
        for _ in tags:
            pass
    return records


def _prepare_shared_listings(plan, projection, cli, ctx, cache, want, check_route):
    if not projection.sitemap_listings:
        return None
    pending = {}
    for lang in ctx.languages:
        articles = None
        if projection.shared_listing_counts is not None:
            articles = _sorted_store_articles(projection.articles_by_lang, lang)
        listings = projection.listing_batch(lang, articles)
        selected = not cli.only_langs or lang in cli.only_langs
        selected = selected and _has_language_work(projection, lang, listings, ctx)
        records = _shared_listings_for_language(plan, ctx, cache, projection, lang, listings, selected, want, check_route)
        if selected:
            pending[lang] = (records, articles)
        if projection.listings_by_lang is not None:
            listings.discard_chunks()
    return pending


def _fill_projection(projection: StreamProjection, stream_factory, cli, ctx, check_route) -> None:
    for seq, art in enumerate(stream_factory()):
        if projection.translations is not None:
            projection.translations.add(art, _passes_cli_filters(art, cli))
        if not art.policy.page:
            if _passes_cli_filters(art, cli):
                _record_skipped_publication(projection, art)
            continue
        if check_route is not None:
            _check_projected_article(projection, art, cli, ctx, check_route)
        art = _record_projection_article(projection, art, cli)
        if "rss" in projection.sections and ctx.rss_items > 0 and art.policy.rss:
            _add_rss_article(projection, ctx, (art.datetime, -seq, art))


def _add_rss_article(projection, ctx, entry):
    if rss_is_per_lang(ctx):
        heap = projection.rss_by_lang.setdefault(entry[2].lang, [])
    else:
        heap = projection.rss_heap
    _push_rss_entry(heap, entry, ctx.rss_items)


def _cross_uses_article(sections, policy, rss_items):
    return (("sitemap" in sections and policy.sitemap)
            or ("search" in sections and policy.search)
            or ("rss" in sections and rss_items > 0 and policy.rss))


def _check_projected_article(projection, art, cli, ctx, check_route):
    if _cross_uses_article(projection.sections, art.policy, ctx.rss_items):
        check_route(art.url)
    elif projection.articles_by_lang is not None and _passes_cli_filters(art, cli):
        check_route(art.url)
    elif _listing_uses_article(projection, art, cli):
        check_route(art.url)


def _listing_uses_article(projection, art, cli):
    if not art.policy.listing or (cli.only_langs and art.lang not in cli.only_langs):
        return False
    if "index" in projection.sections:
        return True
    return "tags" in projection.sections and any(map(normalize_slug, art.tags))


def _record_skipped_publication(projection: StreamProjection, art) -> None:
    name = art.publication_state.name
    projection.skipped_by_publication[name] = (
        projection.skipped_by_publication.get(name, 0) + 1
    )


def _record_projection_article(projection: StreamProjection, art, cli):
    if _passes_cli_filters(art, cli):
        projection.total += 1
        if projection.articles_by_lang is not None:
            projection.articles_by_lang.append(art.lang, art)
    art = replace(art, source_xml=None)
    _add_cross_projection(projection, art)
    if cli.only_langs and art.lang not in cli.only_langs and not projection.sitemap_listings:
        return art
    if projection.shared_listing_counts is not None or projection.listings_by_lang is not None:
        _record_listing(projection, art)
    return art


def _record_listing(projection, art):
    if not art.policy.listing:
        return
    if projection.shared_listing_counts is not None:
        counts = projection.shared_listing_counts
        counts[art.lang] = counts.get(art.lang, 0) + 1
    else:
        projection.listings_by_lang.append(art.lang, art)


def _add_cross_projection(projection: StreamProjection, art) -> None:
    if "sitemap" in projection.sections and art.policy.sitemap:
        projection.sitemap_urls.append_url(art.url, art.modified)
    if "search" in projection.sections and art.policy.search:
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


def _rss_selection(projection: StreamProjection, ctx: BuildCtx):
    """One newest-first list, or one per language when the site asks for that."""
    if not rss_is_per_lang(ctx):
        return _rss_sorted_from_heap(projection.rss_heap)
    return {lang: _rss_sorted_from_heap(heap)
            for lang, heap in projection.rss_by_lang.items()}


def _collect_cross_lang_plan(
    plan, projection: StreamProjection, ctx, cache, want, workspace, manifest,
) -> None:
    """Plan cross-language sections from the completed projections."""
    logging.info(f"Discovered {projection.total} article(s) after filters")
    if want("rss"):
        queue = _tasks_for(plan, "rss", ctx, cache)
        build_rss_section(_rss_selection(projection, ctx), ctx, cache, manifest, tasks=queue)
    if want("sitemap"):
        plan["sitemap"] = build_sitemap_section(
            projection.sitemap_urls, ctx, cache, workspace, manifest,
        )
        plan["sitemap"].extend(_build_robots(ctx, cache, manifest))
    if want("search"):
        plan["search"] = build_search_section(
            projection.search_items, ctx, cache, workspace, manifest,
        )


def _sorted_store_articles(store: ArticleStore | None, lang: str):
    if store is None:
        return []
    return store.sorted(lang)


def _tasks_for(plan: dict, section: str, ctx: BuildCtx, cache) -> _TaskQueue:
    if section not in plan:
        plan[section] = _TaskQueue(ctx, cache)
    return plan[section]


def _add_per_lang_tasks(
    plan: dict, lang_articles, listing_articles, lang, ctx, cache, want, manifest, prepared=None,
) -> None:
    if want("articles"):
        build_articles_section(
            lang_articles, ctx, cache, manifest, _tasks_for(plan, "articles", ctx, cache),
        )
    if prepared is not None:
        prepared.replay(manifest)
        return
    if want("index"):
        build_index_section(
            listing_articles, lang, ctx, cache, manifest, _tasks_for(plan, "index", ctx, cache),
        )
    if want("tags"):
        build_tags_section(
            listing_articles, lang, ctx, cache, manifest, _tasks_for(plan, "tags", ctx, cache),
        )


def _collect_per_lang_plan(
    plan: dict, projection: StreamProjection, cli, ctx: BuildCtx, cache, want, manifest, prepared,
) -> None:
    """Plan per-language sections from the spooled article/listing stores."""
    for lang in ctx.languages:
        if cli.only_langs and lang not in cli.only_langs:
            continue
        if prepared is not None and lang not in prepared:
            continue
        records, articles = prepared.pop(lang) if prepared is not None else (None, None)
        if articles is None:
            articles = _sorted_store_articles(projection.articles_by_lang, lang)
        listings = [] if records is not None else projection.listing_batch(lang, articles)
        _plan_language(plan, articles, listings, lang, ctx, cache, want, manifest, records)


def _plan_language(plan, articles, listings, lang, ctx, cache, want, manifest, records):
    if articles or listings or records is not None or ctx.index_options.include_empty:
        _add_per_lang_tasks(plan, articles, listings, lang, ctx, cache, want, manifest, records)
    if isinstance(articles, SortedArticleBatch):
        articles.discard_chunks()
    if listings is not articles and isinstance(listings, SortedArticleBatch):
        listings.discard_chunks()


def _translation_context(projection, cli, ctx):
    if projection.translations is None:
        return ctx
    ctx = replace(ctx, translations=projection.translations)
    if cli.only_langs or cli.only_slugs:
        def selected(key):
            return _selected_output_key(key, cli)
        projection.translations.validate_filters(ctx.previous_translations, selected)
    return ctx


def _collect_explicit_outputs(plan, ctx, cache, manifest):
    if ctx.extra_pages:
        _collect_extra_plan(ctx, cache, manifest, _tasks_for(plan, 'pages', ctx, cache))
    if ctx.extra_artifacts:
        plan['artifacts'] = build_artifacts_section(ctx.extra_artifacts, ctx, cache, manifest)


def _collect_tasks(
    stream_factory, cli, ctx: BuildCtx, cache, workspace: TempWorkspace, manifest=None,
) -> BuildPlan:
    """
    Stream the article set and dispatch every requested section.

    Returns a dict-like plan ready for parallel execution.
    """
    _require_workspace(workspace)
    sections = frozenset(cli.only_sections or SECTION_NAMES)
    with projection_route_check(cli, sections, ctx.sitemap_listings) as check_route:
        return _plan_sections(stream_factory, cli, ctx, cache, workspace, manifest, sections, check_route)


def _plan_sections(stream_factory, cli, ctx, cache, workspace, manifest, sections, check_route):
    want = sections.__contains__
    plan: dict = {}
    need_cross = any(want(s) for s in CROSS_LANG_SECTIONS)
    need_per_lang = any(want(s) for s in PER_LANG_SECTIONS)
    projection = _stream_projections(
        stream_factory,
        cli,
        ctx,
        workspace,
        cache=cache, check_route=check_route, collect_cross=need_cross,
        collect_articles=need_per_lang,
    )
    try:
        ctx = _translation_context(projection, cli, ctx)
        prepared = _prepare_shared_listings(plan, projection, cli, ctx, cache, want, check_route)
        _append_extra_sitemap(projection, ctx)
        if need_cross:
            _collect_cross_lang_plan(plan, projection, ctx, cache, want, workspace, manifest)
        if need_per_lang:
            _collect_per_lang_plan(
                plan, projection, cli, ctx, cache, want, manifest, prepared,
            )
        _collect_explicit_outputs(plan, ctx, cache, manifest)
    except BaseException:
        _close_task_queues(plan)
        _cleanup_stream_projection(projection)
        raise
    sections = (*CROSS_LANG_SECTIONS, *PER_LANG_SECTIONS, "pages", "artifacts")
    return BuildPlan({section: plan[section] for section in sections if section in plan}, projection)


def _article_stream_factory(ctx: BuildCtx, stats: ArticleStats, evaluated_at=None):
    url_builder = _article_url_builder(ctx)
    allowed_langs = frozenset(ctx.languages)
    evaluated_at = evaluated_at or datetime.now(timezone.utc)

    def stream_factory():
        with closing(iter_articles(
            ctx.content_dir,
            default_lang=ctx.default_language,
            url_builder=url_builder,
            allowed_langs=allowed_langs,
            stats=stats,
        )) as source:
            for article in source:
                state = replace(article.publication_state, evaluated_at=evaluated_at)
                yield replace(article, publication=state)

    return stream_factory


def _run_plan(plan: dict, ctx: BuildCtx) -> None:
    try:
        _execute_plan(plan, ctx)
    finally:
        _close_task_queues(plan)


def _close_task_queues(plan: dict) -> None:
    for tasks in plan.values():
        if isinstance(tasks, _TaskQueue):
            tasks.close()


def _execute_plan(plan: dict, ctx: BuildCtx) -> None:
    total = sum(len(tasks) for tasks in plan.values())
    if not total:
        logging.info("Nothing to build — all pages up to date.")
        return
    logging.info(f"Build plan: {total} task(s) across {len(plan)} section(s)")
    for section, tasks in plan.items():
        logging.info(f"  {section}: {len(tasks)} task(s)")
    t0 = time.perf_counter()
    run_parallel_tasks(
        _admitted_tasks(plan), _resolve_parallelism(ctx), collect_results=False,
        max_inflight_bytes=_RENDER_INPUT_BUDGET,
    )
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


def _load_build_cache(cache_path: Path, output_dir: Path, partitioned=False) -> tuple[TrackedCache, dict]:
    stored = load_cache(cache_path)
    root = str(output_dir.resolve())
    roots = selected_roots(stored, root, partitioned)
    data = roots.get(root)
    cache = TrackedCache(data if last_used(data) is not None else {})
    return cache, roots


def _extra_output_keys(ctx):
    return {page.route.key for page in ctx.extra_pages} | {
        'artifact:' + artifact.output_path for artifact in ctx.extra_artifacts
    }


def _retained_outputs(cli, old_manifest: dict, extra_keys=()) -> dict:
    return {} if _can_prune_outputs(cli) else {
        path: key for path, key in old_manifest.items()
        if key not in extra_keys and not _selected_output_key(key, cli)
    }


def _validate_retained_outputs(cli, ctx: BuildCtx, old_manifest, current_manifest) -> set[Path] | None:
    retained = _retained_outputs(cli, old_manifest, _extra_output_keys(ctx))
    if not retained:
        return None
    root = ctx.output_dir.resolve()
    checked: set[Path] = set()
    for relpath in retained:
        current_manifest.reserve_path(relpath)
    for relpath in chain(retained, current_manifest.values()):
        _manifest_target(root, relpath, checked)
    return checked


def _next_output_paths(cli, ctx, old_manifest, current_manifest):
    retained = _retained_outputs(cli, old_manifest, _extra_output_keys(ctx))
    return {**retained, **{path: key for key, path in current_manifest.items()}}


def _published_translations(ownership, cache, planned):
    if cache['__generation__'] == ownership.generation:
        return ownership.translations
    history = {key: pair for key, pair in ownership.translations.items()
               if key not in planned and key in cache[_OUTPUT_MANIFEST_KEY]}
    history.update(translation_history(cache, planned))
    return history


def _finalize_cache(ctx, cache, roots, ownership, next_manifest, current_manifest, selected, checked_parents) -> None:
    _prune_stale_outputs(ctx, cache, ownership.paths, next_manifest, checked_parents)
    cache[_OUTPUT_MANIFEST_KEY] = dict(sorted((key, path) for path, key in next_manifest.items()))
    routes = current_manifest.route_values()
    cache['__routes__'] = route_cache_data(routes)
    if refresh_output_cache(roots, str(ctx.output_dir.resolve()), cache, ctx.cache_retention_days):
        if not save_cache(selected.path, cache_payload(selected, roots)):
            logging.warning("Cache save failed; retry without --only, --lang or --slug for recovery")
            return
    else:
        logging.debug("Cache unchanged — skipping save")
    save_ownership(ctx.output_dir, next_manifest, routes=routes, generation=cache['__generation__'],
                   translations=_published_translations(ownership, cache, current_manifest))
    finish_cache_update(selected, ctx.cache_retention_days, ctx.partition_cache)


def _cache_path_for(ctx: BuildCtx, project_root: Path) -> Path:
    """Resolve the cache file path. ``ctx.cache_file`` is already a bare
    filename (see :func:`build_ctx_from_config`)."""
    return (project_root / ctx.cache_file).resolve()


def _lock_path_for(ctx: BuildCtx, project_root: Path) -> Path:
    output = ctx.output_dir.resolve()
    lock = output.parent / f".{output.name}.articulous.lock"
    if _cache_path_for(ctx, project_root).resolve() == lock:
        raise ValueError("Cache file must not alias the output build lock")
    return lock


@contextmanager
def _cache_build_lock(cache, output_lock):
    with lock_file(cache_lock_path(cache)), lock_file(output_lock):
        yield


def _resolve_parallelism(ctx: BuildCtx) -> WorkerCount:
    return _worker_count(ctx.parallelism)


def _can_prune_outputs(cli) -> bool:
    return not (cli.only_sections or cli.only_langs or cli.only_slugs)


def _selected_output_key(key: str, cli) -> bool:
    prefix, _, tail = key.partition(":")
    section = {"article": "articles", "tag": "tags"}.get(prefix, prefix)
    if section not in (cli.only_sections or SECTION_NAMES):
        return False
    if prefix in ("article", "index", "tag"):
        lang, _, slug = tail.rpartition(":")
        if cli.only_langs and lang not in cli.only_langs:
            return False
        return prefix != "article" or not cli.only_slugs or slug in cli.only_slugs
    return True


def _require_manifest_parent(path: Path) -> None:
    if path.is_symlink():
        raise OSError(f"Manifest output ancestor is a symlink: {path}")


def _manifest_target(root: Path, relpath: str, checked: set[Path] | None = None) -> Path:
    rel = Path(relpath)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"Manifest output path must be relative without traversal: {relpath}")
    for parent in rel.parents:
        if checked is not None and parent in checked:
            break
        _require_manifest_parent(root / parent)
        if checked is not None:
            checked.add(parent)
    return root / rel


def _remove_empty_parents(path: Path, stop: Path) -> None:
    parent = path.parent
    while parent != stop:
        try:
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent


def _delete_asset_entry(path: Path, root: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    _remove_empty_parents(path, root)


def _delete_output_file(path: Path, root: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        raise ValueError(f"Owned output file became a directory; refusing deletion: {path}")
    try:
        path.unlink(missing_ok=True)
    except NotADirectoryError:
        return
    _remove_empty_parents(path, root)


def _prune_stale_outputs(
    ctx: BuildCtx,
    cache: dict,
    old_manifest: dict,
    current_manifest: dict,
    checked_parents: set[Path] | None = None,
) -> None:
    stale_paths = sorted(old_manifest.keys() - current_manifest.keys())
    root = ctx.output_dir.resolve()
    paths = _current_output_paths(root, current_manifest, checked_parents, collect=bool(stale_paths))
    if stale_paths:
        _remove_stale_paths(root, stale_paths, paths)
    for key in set(old_manifest.values()) - set(current_manifest.values()):
        cache.pop(key, None)


def _current_output_paths(root: Path, manifest: dict, checked_parents, *, collect: bool) -> set[Path]:
    if checked_parents is not None:
        for parent in checked_parents:
            _require_manifest_parent(root / parent)
        return {root / relpath for relpath in manifest} if collect else set()
    checked: set[Path] = set()
    paths: set[Path] = set()
    for relpath in manifest:
        target = _manifest_target(root, relpath, checked)
        if collect:
            paths.add(target)
    return paths


def _remove_stale_paths(root: Path, stale_paths: list[str], current_paths: set[Path]) -> None:
    protected = {
        ancestor
        for path in current_paths
        for ancestor in (path, *path.parents)
    }
    protected.add(root)
    for relpath in stale_paths:
        try:
            target = _manifest_target(root, relpath)
        except ValueError as e:
            logging.warning(f"Skipping invalid output ownership entry: {e}")
        else:
            if _can_delete_stale_target(target, root, protected, current_paths):
                _delete_output_file(target, root)


def _can_delete_stale_target(target: Path, root: Path, protected: set, current_paths: set) -> bool:
    return (
        target not in protected and not target.is_relative_to(root / "assets")
        and not any(parent in current_paths for parent in target.parents)
    )


def _cleanup_stream_projection(projection: Optional[StreamProjection]) -> None:
    if projection is None:
        return
    for sink in (projection.sitemap_urls, projection.search_items):
        sink.close()
    if projection.articles_by_lang is not None:
        projection.articles_by_lang.close()
    if projection.listings_by_lang is not None:
        projection.listings_by_lang.close()
    if projection.translations is not None:
        projection.translations.close()


# ================================================================
# Top-level build pipeline
# ================================================================

def _remove_output_obstructions(ctx: BuildCtx, before_mutation) -> None:
    assert ctx.output_migrations is not None
    for path in ctx.output_migrations.removals():
        logging.info(f"{'Would remove' if ctx.dry_run else 'Removing'} obsolete route obstruction: {path}")
        if not ctx.dry_run:
            before_mutation()
            _delete_output_file(path, ctx.output_dir.resolve())


def _ownership_will_change(ctx, ownership: Ownership, next_paths, routes, plan) -> bool:
    return (
        ownership.pending or any(plan.values()) or ownership.paths != next_paths
        or ownership.routes != routes or not ownership_path(ctx.output_dir).is_file()
        or not ctx.output_dir.is_dir()
    )


def _prepare_outputs(ctx, cache, ownership, current_manifest, next_paths, plan) -> None:
    pending = False
    routes = current_manifest.route_values()

    def start_journal():
        nonlocal pending
        if not pending:
            planned_paths = {path: key for key, path in current_manifest.items()}
            journal_ownership(ctx.output_dir, ownership.paths, planned_paths, routes=routes)
            pending = True

    if not ctx.dry_run and _ownership_will_change(ctx, ownership, next_paths, routes, plan):
        start_journal()
        cache['__generation__'] = uuid4().hex
    _remove_output_obstructions(ctx, start_journal)
    copy_assets(ctx, cache, before_mutation=start_journal)
    if not ctx.dry_run:
        ctx.output_dir.mkdir(parents=True, exist_ok=True)


def _retained_page_routes(cli, ctx, ownership):
    if 'sitemap' not in (cli.only_sections or SECTION_NAMES):
        return ()
    retained = _retained_outputs(cli, ownership.paths, _extra_output_keys(ctx))
    return tuple(ownership.routes[key] for key in retained.values() if key.startswith('page:'))


def _record_retained_routes(cli, ctx, ownership, manifest):
    for key in _retained_outputs(cli, ownership.paths, _extra_output_keys(ctx)).values():
        manifest.record_route(ownership.routes[key])


def _incremental_state(cli, ctx, selected):
    cache, roots = _load_build_cache(selected.path, ctx.output_dir, selected.partitioned)
    ownership = load_ownership(ctx.output_dir, allow_pending=_can_prune_outputs(cli))
    if not ownership.generation or cache.get('__generation__') != ownership.generation:
        for key in list(cache):
            if not key.startswith('__'):
                cache.pop(key)
        cache['__generation__'] = uuid4().hex
    return cache, roots, ownership


def run_build(cli: BuildOptions, config: ConfigurationInput, project_root: Path, *, extra_pages=(), extra_artifacts=(), route_catalog=None) -> None:
    """Orchestrate the entire build process."""
    logging.info("Starting build...")

    config = normalize_configuration(config, cli, project_root)
    ctx = replace(build_ctx_from_config(config, dry_run=cli.dry_run), extra_pages=tuple(extra_pages),
                  extra_artifacts=artifact_values(extra_artifacts))
    cache_path = _cache_path_for(ctx, project_root)
    locked = partial(_cache_build_lock, output_lock=_lock_path_for(ctx, project_root))
    with lock_selected_cache(cache_path, ctx.output_dir, locked, project=project_root.resolve()) as selected:
        if os.path.lexists(transaction_path(ctx.output_dir)):
            raise ValueError("Whole-site publication requires recovery before an incremental build")
        with TempWorkspace() as workspace:
            projection = None
            plan: dict = {}
            try:
                cache, roots, ownership = _incremental_state(cli, ctx, selected)
                old_manifest = ownership.paths
                ctx = replace(ctx, force=ctx.force or ownership.pending, previous_translations=ownership.translations)
                ctx = replace(ctx, output_migrations=OutputMigrations(
                    ctx.output_dir, old_manifest, _retained_outputs(cli, old_manifest, _extra_output_keys(ctx)),
                ), retained_page_routes=_retained_page_routes(cli, ctx, ownership))
                stats = ArticleStats()
                stream_factory = _article_stream_factory(ctx, stats)
                current_manifest = OutputManifest(ctx, route_catalog)
                plan = _collect_tasks(
                    stream_factory, cli, ctx, cache, workspace, current_manifest,
                )
                projection = plan.projection
                checked_parents = _validate_retained_outputs(cli, ctx, old_manifest, current_manifest)
                _record_retained_routes(cli, ctx, ownership, current_manifest)
                next_paths = _next_output_paths(cli, ctx, old_manifest, current_manifest)
                _prepare_outputs(ctx, cache, ownership, current_manifest, next_paths, plan)
                _run_plan(plan, ctx)
                _log_article_stats(stats, projection)
                if not cli.dry_run:
                    _finalize_cache(
                        ctx, cache, roots, ownership, next_paths, current_manifest, selected, checked_parents,
                    )
            finally:
                _close_task_queues(plan)
                _cleanup_stream_projection(projection)

    logging.info("Build complete.")
