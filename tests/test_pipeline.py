"""Unit tests for articulous.pipeline."""
import copy
import dataclasses
import logging
from datetime import datetime
from pathlib import Path

import pytest

from articulous.articles import Article
from articulous.config import DEFAULT_CONFIG
from articulous.engines import LxmlEngine, SaxonCEngine
from articulous.pipeline import (
    BuildCtx,
    SECTION_NAMES,
    _article_url_builder,
    _article_xml,
    _cache_path_for,
    _collect_tasks,
    _encode_xml,
    _filter_articles,
    _make_xslt_task,
    _passes_cli_filters,
    _resolve_parallelism,
    _rss_item_xml,
    _rss_sorted_from_heap,
    _sitemap_url_xml,
    _stream_projections,
    _xml_doc,
    build_articles_section,
    build_ctx_from_config,
    build_index_section,
    build_rss_section,
    build_search_section,
    build_sitemap_section,
    build_tags_section,
    copy_assets,
    run_build,
)


MINIMAL_XSLT = (
    b'<?xml version="1.0"?>'
    b'<xsl:stylesheet version="1.0" '
    b'xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
    b'<xsl:template match="/"><out/></xsl:template>'
    b"</xsl:stylesheet>"
)


def _art(slug, lang="en", url=None, tags=()):
    return Article(
        title=slug, slug=slug, lang=lang, date="2025-01-01",
        datetime=datetime(2025, 1, 1), description="d", tags=tags,
        source_path=Path(f"/c/{slug}.xml"),
        url=url or f"https://e.test/{lang}/articles/{slug}/",
    )


def _ctx_for(tmp_path, engines=None):
    xsl_pages = tmp_path / "xsl" / "pages"
    xsl_pages.mkdir(parents=True, exist_ok=True)
    for name in ("article", "index", "tags", "rss", "sitemap", "search"):
        (xsl_pages / f"{name}.xsl").write_bytes(MINIMAL_XSLT)
    (tmp_path / "content").mkdir(exist_ok=True)
    (tmp_path / "output").mkdir(exist_ok=True)
    (tmp_path / "assets").mkdir(exist_ok=True)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["paths"]["xsl_dir"] = str(tmp_path / "xsl")
    cfg["paths"]["output_dir"] = str(tmp_path / "output")
    cfg["paths"]["assets_dir"] = str(tmp_path / "assets")
    cfg["paths"]["content_dir"] = str(tmp_path / "content")
    cfg["site"]["languages"] = ["en"]
    if engines:
        cfg["engines"].update(engines)
    return build_ctx_from_config(cfg, dry_run=False)


# --- BuildCtx + factory ---

def test_build_ctx_from_config_validates(tmp_path):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["engines"]["rss"] = "frobnicate"
    with pytest.raises(ValueError):
        build_ctx_from_config(cfg, dry_run=False)


def test_buildctx_xsl_for_and_engine_for(tmp_path):
    ctx = _ctx_for(tmp_path)
    assert ctx.xsl_for("articles").name == "article.xsl"
    assert isinstance(ctx.engine_for("articles"), LxmlEngine)


# --- _cache_path_for ---

def test_cache_path_strips_traversal(tmp_path):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["build"]["cache_file"] = "../../etc/passwd"
    ctx = build_ctx_from_config(cfg, dry_run=False)
    assert _cache_path_for(ctx, Path("/x")) == Path("/x/passwd")


# --- _resolve_parallelism ---

def test_resolve_parallelism_lxml_default(tmp_path):
    ctx = _ctx_for(tmp_path)
    import os
    assert _resolve_parallelism(ctx) == max(4, os.cpu_count() or 4)


def test_resolve_parallelism_saxon_caps_at_cpu(tmp_path):
    ctx = _ctx_for(tmp_path)
    ctx = dataclasses.replace(
        ctx,
        engines={
            **ctx.engines,
            "articles": SaxonCEngine(tmp_path / "fake-bin"),
        },
    )
    import os
    assert _resolve_parallelism(ctx) == (os.cpu_count() or 4)


def test_resolve_parallelism_passes_through_explicit_value(tmp_path):
    ctx = _ctx_for(tmp_path)
    ctx = dataclasses.replace(ctx, parallelism=2)
    assert _resolve_parallelism(ctx) == 2


# --- copy_assets ---

def test_copy_assets_missing_src_noop(tmp_path):
    ctx = _ctx_for(tmp_path)
    (tmp_path / "assets").rmdir()
    ctx = dataclasses.replace(ctx, assets_dir=tmp_path / "assets")
    copy_assets(ctx)
    assert not (tmp_path / "output" / "assets").exists()


def test_copy_assets_dry_run(tmp_path):
    ctx = _ctx_for(tmp_path)
    (tmp_path / "assets" / "x.txt").write_text("hi")
    ctx = dataclasses.replace(ctx, dry_run=True)
    copy_assets(ctx)
    assert not (tmp_path / "output" / "assets").exists()


def test_copy_assets_copies_and_replaces(tmp_path):
    ctx = _ctx_for(tmp_path)
    (tmp_path / "assets" / "x.txt").write_text("v1")
    copy_assets(ctx)
    assert (tmp_path / "output" / "assets" / "x.txt").read_text() == "v1"
    # second run replaces
    (tmp_path / "assets" / "x.txt").write_text("v2")
    copy_assets(ctx)
    assert (tmp_path / "output" / "assets" / "x.txt").read_text() == "v2"


# --- URL builder + xml helpers ---

def test_article_url_builder(tmp_path):
    ctx = _ctx_for(tmp_path)
    b = _article_url_builder(ctx)
    assert b("en", "foo").endswith("/en/articles/foo/")


def test_xml_doc():
    assert _xml_doc("root", ["<a/>", "<b/>"]) == "<root><a/><b/></root>"


def test_article_xml_escapes():
    a = _art("a", url="u&v")
    a = dataclasses.replace(a, title="<bad>")
    assert "&lt;bad&gt;" in _article_xml(a)
    assert "u&amp;v" in _article_xml(a)


def test_rss_item_xml_escapes():
    a = _art("a")
    a = dataclasses.replace(a, title="x>y", url="?q=1&p=2")
    out = _rss_item_xml(a)
    assert "x&gt;y" in out
    assert "&amp;p=2" in out


def test_sitemap_url_xml_escapes():
    assert _sitemap_url_xml("a<b") == "<url>a&lt;b</url>"


def test_encode_xml():
    assert _encode_xml("<x/>") == b"<x/>"


# --- _make_xslt_task ---

def test_make_xslt_task_bytes_hashes_in_memory(tmp_path):
    ctx = _ctx_for(tmp_path)
    xsl = tmp_path / "xsl" / "pages" / "rss.xsl"
    cache = {}
    task = _make_xslt_task(
        xml_input=b"<root/>",
        xsl_path=xsl, xsl_hash="abc",
        output_path=tmp_path / "out.html",
        cache=cache, cache_key="k",
        engine=LxmlEngine(), ctx=ctx,
    )
    assert task is not None
    task()
    import hashlib
    expected = hashlib.sha256(b"<root/>").hexdigest()
    assert cache["k"] == [expected, "abc"]


def test_make_xslt_task_path_hashes_file(tmp_path):
    ctx = _ctx_for(tmp_path)
    xml = tmp_path / "in.xml"
    xml.write_bytes(b"<root/>")
    xsl = tmp_path / "xsl" / "pages" / "rss.xsl"
    cache = {}
    task = _make_xslt_task(
        xml_input=xml, xsl_path=xsl, xsl_hash="xsl_h",
        output_path=tmp_path / "out.html",
        cache=cache, cache_key="k",
        engine=LxmlEngine(), ctx=ctx,
    )
    assert task is not None
    task()
    assert cache["k"][1] == "xsl_h"


def test_make_xslt_task_cached_returns_none(tmp_path):
    ctx = _ctx_for(tmp_path)
    xsl = tmp_path / "xsl" / "pages" / "rss.xsl"
    import hashlib
    pre_xml_hash = hashlib.sha256(b"<root/>").hexdigest()
    cache = {"k": [pre_xml_hash, "xsl_h"]}
    task = _make_xslt_task(
        xml_input=b"<root/>", xsl_path=xsl, xsl_hash="xsl_h",
        output_path=tmp_path / "out.html",
        cache=cache, cache_key="k",
        engine=LxmlEngine(), ctx=ctx,
    )
    assert task is None


def test_make_xslt_task_cache_not_committed_on_failure(tmp_path):
    ctx = _ctx_for(tmp_path)
    # broken xsl content → XSLTParseError
    broken = tmp_path / "broken.xsl"
    broken.write_bytes(b"<not-a-stylesheet/>")
    cache = {}
    task = _make_xslt_task(
        xml_input=b"<root/>", xsl_path=broken, xsl_hash="xsl_h",
        output_path=tmp_path / "out.html",
        cache=cache, cache_key="bad",
        engine=LxmlEngine(), ctx=ctx,
    )
    with pytest.raises(Exception):
        task()
    assert "bad" not in cache


# --- section name set ---

def test_section_names_complete():
    assert set(SECTION_NAMES) == {
        "articles", "index", "tags", "rss", "sitemap", "search",
    }


def test_build_articles_section_returns_tasks(tmp_path):
    ctx = _ctx_for(tmp_path)
    art_xml = tmp_path / "content" / "a.xml"
    art_xml.write_text(
        '<article><title>A</title><date>2025-01-01</date>'
        '<description>d</description></article>'
    )
    a = dataclasses.replace(_art("a"), source_path=art_xml)
    tasks = build_articles_section([a], ctx, {})
    assert len(tasks) == 1


def test_build_articles_section_skips_cached(tmp_path):
    ctx = _ctx_for(tmp_path)
    art_xml = tmp_path / "content" / "a.xml"
    art_xml.write_text(
        '<article><title>A</title><date>2025-01-01</date>'
        '<description>d</description></article>'
    )
    a = dataclasses.replace(_art("a"), source_path=art_xml)
    cache = {}
    tasks = build_articles_section([a], ctx, cache)
    for t in tasks: t()
    assert build_articles_section([a], ctx, cache) == []


def test_build_index_section_runs(tmp_path):
    ctx = _ctx_for(tmp_path)
    arts = [_art("a"), _art("b")]
    tasks = build_index_section(arts, "en", ctx, {})
    assert len(tasks) == 1
    tasks[0]()
    assert (tmp_path / "output" / "en" / "page" / "1" / "index.html").exists()


def test_build_index_section_cached(tmp_path):
    ctx = _ctx_for(tmp_path)
    arts = [_art("a")]
    cache = {}
    tasks = build_index_section(arts, "en", ctx, cache)
    for t in tasks: t()
    assert build_index_section(arts, "en", ctx, cache) == []


def test_build_tags_section_runs(tmp_path):
    ctx = _ctx_for(tmp_path)
    arts = [_art("a", tags=("news",))]
    tasks = build_tags_section(arts, "en", ctx, {})
    assert len(tasks) == 1
    tasks[0]()


def test_build_tags_section_cached(tmp_path):
    ctx = _ctx_for(tmp_path)
    arts = [_art("a", tags=("news",))]
    cache = {}
    tasks = build_tags_section(arts, "en", ctx, cache)
    for t in tasks: t()
    assert build_tags_section(arts, "en", ctx, cache) == []


def test_build_rss_section_runs_and_caches(tmp_path):
    ctx = _ctx_for(tmp_path)
    arts = [_art("a")]
    cache = {}
    tasks = build_rss_section(arts, ctx, cache)
    assert len(tasks) == 1
    tasks[0]()
    assert build_rss_section(arts, ctx, cache) == []


def test_build_sitemap_section_runs_and_caches(tmp_path):
    ctx = _ctx_for(tmp_path)
    urls = ["https://e.test/a/"]
    cache = {}
    tasks = build_sitemap_section(urls, ctx, cache)
    assert len(tasks) == 1
    tasks[0]()
    assert build_sitemap_section(urls, ctx, cache) == []


def test_build_search_section_runs_and_caches(tmp_path):
    ctx = _ctx_for(tmp_path)
    items = [{"title": "A", "description": "d",
              "url": "https://e.test/a/", "tags": ["news"]}]
    cache = {}
    tasks = build_search_section(items, ctx, cache)
    assert len(tasks) == 1
    tasks[0]()
    assert (tmp_path / "output" / "search.json").exists()
    assert build_search_section(items, ctx, cache) == []


# --- _filter_articles ---

class _FakeCLI:
    def __init__(self, langs=None, slugs=None, sections=None):
        self.only_langs = langs
        self.only_slugs = slugs
        self.only_sections = sections


def test_filter_articles_no_filters():
    arts = [_art("a"), _art("b")]
    assert _filter_articles(arts, _FakeCLI()) == arts


def test_filter_articles_by_lang():
    arts = [_art("a", lang="en"), _art("b", lang="fr")]
    out = _filter_articles(arts, _FakeCLI(langs=["en"]))
    assert [a.slug for a in out] == ["a"]


def test_filter_articles_by_slug():
    arts = [_art("a"), _art("b")]
    out = _filter_articles(arts, _FakeCLI(slugs=["b"]))
    assert [a.slug for a in out] == ["b"]


# --- _passes_cli_filters ---

def test_passes_cli_filters_no_constraints():
    assert _passes_cli_filters(_art("a"), _FakeCLI()) is True


def test_passes_cli_filters_lang_reject():
    assert _passes_cli_filters(
        _art("a", lang="fr"), _FakeCLI(langs=["en"]),
    ) is False


def test_passes_cli_filters_slug_reject():
    assert _passes_cli_filters(
        _art("a"), _FakeCLI(slugs=["b"]),
    ) is False


# --- _stream_projections ---

def test_stream_projections_collects_all_and_bounds_rss(tmp_path):
    ctx = _ctx_for(tmp_path)
    ctx = dataclasses.replace(ctx, rss_items=2)
    articles = [_art(f"a{i}") for i in range(5)]
    # Datetimes differ so the heap ordering is deterministic
    articles = [
        dataclasses.replace(a, datetime=datetime(2025, 1, i + 1))
        for i, a in enumerate(articles)
    ]
    urls, items, heap, total = _stream_projections(
        lambda: iter(articles), _FakeCLI(), ctx,
    )
    assert total == 5
    assert len(urls) == 5
    assert len(items) == 5
    assert len(heap) == 2  # bounded by rss_items
    # Heap contains the two newest
    dates = sorted(dt for dt, _, _ in heap)
    assert dates == [datetime(2025, 1, 4), datetime(2025, 1, 5)]


def test_stream_projections_respects_cli_filters(tmp_path):
    ctx = _ctx_for(tmp_path)
    articles = [_art("a", lang="en"), _art("b", lang="fr")]
    urls, items, heap, total = _stream_projections(
        lambda: iter(articles), _FakeCLI(langs=["en"]), ctx,
    )
    assert total == 1


def test_rss_sorted_from_heap_newest_first(tmp_path):
    ctx = _ctx_for(tmp_path)
    articles = [
        dataclasses.replace(_art("a"), datetime=datetime(2025, 1, 1)),
        dataclasses.replace(_art("b"), datetime=datetime(2025, 6, 1)),
        dataclasses.replace(_art("c"), datetime=datetime(2025, 3, 1)),
    ]
    _, _, heap, _ = _stream_projections(
        lambda: iter(articles), _FakeCLI(), ctx,
    )
    out = _rss_sorted_from_heap(heap)
    assert [a.slug for a in out] == ["b", "c", "a"]


# --- _collect_tasks ---

def test_collect_tasks_all_sections(tmp_path):
    ctx = _ctx_for(tmp_path)
    # Empty stream keeps the test independent of any on-disk source
    # files; every requested section still runs its builder.
    plan = _collect_tasks(lambda: iter(()), _FakeCLI(), ctx, {})
    # Cross-lang builders always run when included; per-lang ones only
    # run when at least one matching article exists, so empty stream
    # produces only the cross-lang section entries.
    assert set(plan.keys()) == {"rss", "sitemap", "search"}


def test_collect_tasks_only_subset(tmp_path):
    ctx = _ctx_for(tmp_path)
    cli = _FakeCLI()
    cli.only_sections = ["search"]
    plan = _collect_tasks(lambda: iter(()), cli, ctx, {})
    assert list(plan.keys()) == ["search"]


def test_collect_tasks_per_lang_populated(tmp_path):
    ctx = _ctx_for(tmp_path)
    art_xml = tmp_path / "content" / "a.xml"
    art_xml.write_text(
        '<article><title>A</title><date>2025-01-01</date>'
        '<description>d</description></article>'
    )
    a = dataclasses.replace(_art("a"), source_path=art_xml)
    cli = _FakeCLI()
    cli.only_sections = ["articles"]
    plan = _collect_tasks(lambda: iter([a]), cli, ctx, {})
    assert "articles" in plan and len(plan["articles"]) == 1


def test_collect_tasks_only_lang_filter(tmp_path):
    ctx = _ctx_for(tmp_path)
    art_xml = tmp_path / "content" / "a.xml"
    art_xml.write_text(
        '<article><title>A</title><date>2025-01-01</date>'
        '<description>d</description></article>'
    )
    a = dataclasses.replace(_art("a", lang="en"), source_path=art_xml)
    b = dataclasses.replace(_art("b", lang="fr"), source_path=art_xml)
    # Configure two languages so the lang-filter has work to skip.
    ctx_multilang = dataclasses.replace(ctx, languages=["en", "fr"])
    cli = _FakeCLI(langs=["en"], sections=["articles"])
    plan = _collect_tasks(lambda: iter([a, b]), cli, ctx_multilang, {})
    assert len(plan["articles"]) == 1


def test_collect_tasks_only_index_subset(tmp_path):
    """Per-lang sections requested but ``articles`` excluded."""
    ctx = _ctx_for(tmp_path)
    a = _art("a")
    cli = _FakeCLI(sections=["index"])
    plan = _collect_tasks(lambda: iter([a]), cli, ctx, {})
    assert "articles" not in plan
    assert "index" in plan


def test_collect_tasks_only_sitemap_subset(tmp_path):
    """Subset that includes one cross-lang section but skips the others."""
    ctx = _ctx_for(tmp_path)
    cli = _FakeCLI(sections=["sitemap"])
    plan = _collect_tasks(lambda: iter(()), cli, ctx, {})
    assert list(plan.keys()) == ["sitemap"]


def test_stream_projections_replaces_older_top(tmp_path):
    """Older articles arriving after the heap is full are rejected."""
    ctx = _ctx_for(tmp_path)
    ctx = dataclasses.replace(ctx, rss_items=2)
    # First two seed the heap (newer datetimes), third is older and
    # must be rejected by the heapq.heapreplace branch's else.
    arts = [
        dataclasses.replace(_art("a"), datetime=datetime(2025, 6, 1)),
        dataclasses.replace(_art("b"), datetime=datetime(2025, 5, 1)),
        dataclasses.replace(_art("c"), datetime=datetime(2024, 1, 1)),
    ]
    _, _, heap, total = _stream_projections(
        lambda: iter(arts), _FakeCLI(), ctx,
    )
    assert total == 3
    slugs = sorted(art.slug for _, _, art in heap)
    assert slugs == ["a", "b"]  # the old one didn't make it


# --- run_build end-to-end ---

class _CLI:
    def __init__(self, **kw):
        self.dry_run = kw.get("dry_run", False)
        self.force_full_build = kw.get("force_full_build", False)
        self.verbose = kw.get("verbose", False)
        self.only_sections = kw.get("only_sections")
        self.only_langs = kw.get("only_langs")
        self.only_slugs = kw.get("only_slugs")


def test_run_build_end_to_end(site_root):
    """Use the fixture site to exercise run_build via the package."""
    from articulous.config import apply_cli_overrides, load_or_create_config
    cfg = load_or_create_config(site_root / "config.json")
    cli = _CLI(force_full_build=True)
    apply_cli_overrides(cfg, cli, site_root)
    run_build(cli, cfg, site_root)
    assert (site_root / "output" / "rss.xml").exists()


def test_run_build_skips_save_when_cache_unchanged(site_root, caplog):
    """Second run with no changes should not rewrite the cache file."""
    from articulous.config import apply_cli_overrides, load_or_create_config
    cfg = load_or_create_config(site_root / "config.json")
    cli = _CLI(force_full_build=True)
    apply_cli_overrides(cfg, cli, site_root)
    run_build(cli, cfg, site_root)
    cache_path = site_root / ".build-cache.json"
    first_mtime = cache_path.stat().st_mtime_ns

    # Second run, no force: cache should be untouched
    cli2 = _CLI()
    cfg2 = load_or_create_config(site_root / "config.json")
    apply_cli_overrides(cfg2, cli2, site_root)
    with caplog.at_level(logging.DEBUG):
        run_build(cli2, cfg2, site_root)
    assert cache_path.stat().st_mtime_ns == first_mtime
    assert any("Cache unchanged" in r.message for r in caplog.records)


def test_run_build_dry_run_skips_save(site_root):
    from articulous.config import apply_cli_overrides, load_or_create_config
    cfg = load_or_create_config(site_root / "config.json")
    cli = _CLI(dry_run=True, force_full_build=True)
    apply_cli_overrides(cfg, cli, site_root)
    run_build(cli, cfg, site_root)
    assert not (site_root / ".build-cache.json").exists()


def test_run_build_only_one_section(site_root):
    from articulous.config import apply_cli_overrides, load_or_create_config
    cfg = load_or_create_config(site_root / "config.json")
    cli = _CLI(force_full_build=True, only_sections=["search"])
    apply_cli_overrides(cfg, cli, site_root)
    run_build(cli, cfg, site_root)
    assert (site_root / "output" / "search.json").exists()
    assert not (site_root / "output" / "rss.xml").exists()


def test_run_build_nothing_to_build(site_root, caplog):
    """Second consecutive build with no source changes → Nothing to build."""
    from articulous.config import apply_cli_overrides, load_or_create_config
    # First run: prime the cache.
    cfg1 = load_or_create_config(site_root / "config.json")
    cli1 = _CLI(force_full_build=True)
    apply_cli_overrides(cfg1, cli1, site_root)
    run_build(cli1, cfg1, site_root)

    # Second run: nothing changed.
    cfg2 = load_or_create_config(site_root / "config.json")
    cli2 = _CLI()
    apply_cli_overrides(cfg2, cli2, site_root)
    with caplog.at_level(logging.INFO):
        run_build(cli2, cfg2, site_root)
    assert any("Nothing to build" in r.message for r in caplog.records)


def test_run_build_zero_elapsed_branch(site_root, monkeypatch, caplog):
    """Force elapsed time of zero to exercise the no-throughput log branch."""
    import articulous.pipeline as pipeline
    # Pin perf_counter to a constant so elapsed == 0 in the throughput
    # formatter; affects every call (pipeline + runtime's timed wrapper).
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 100.0)
    from articulous.config import apply_cli_overrides, load_or_create_config
    cfg = load_or_create_config(site_root / "config.json")
    cli = _CLI(force_full_build=True)
    apply_cli_overrides(cfg, cli, site_root)
    with caplog.at_level(logging.INFO):
        run_build(cli, cfg, site_root)
    assert any("Ran" in r.message and "task" in r.message for r in caplog.records)
