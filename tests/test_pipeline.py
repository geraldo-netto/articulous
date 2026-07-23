"""Unit tests for articulous.pipeline."""
import copy
import dataclasses
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import lxml.etree as etree
import pytest

from articulous.articles import Article, ArticleStats
from articulous.config import DEFAULT_CONFIG, validate_config
from articulous.engines import LxmlEngine, SaxonCEngine
from articulous.filesystem import TempWorkspace
from articulous.pipeline import (
    ArticleStore,
    BuildCtx,
    FragmentSink,
    SearchSink,
    _article_url_builder,
    _article_xml,
    _cache_path_for,
    _cleanup_stream_projection,
    _collect_tasks,
    _encode_xml,
    _index_doc,
    _log_article_stats,
    _make_xslt_task,
    _passes_cli_filters,
    _prune_stale_outputs,
    _resolve_parallelism,
    _rss_doc,
    _rss_item_xml,
    _rss_sorted_from_heap,
    _search_doc,
    _search_item_xml,
    _sitemap_doc,
    _sitemap_url_xml,
    _sorted_store_articles,
    _stream_projections,
    _tag_doc,
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
from articulous.models import IndexPage, RssFeed, Sitemap, TagPage
from articulous.sections import SECTION_NAMES


MINIMAL_XSLT = (
    b'<?xml version="1.0"?>'
    b'<xsl:stylesheet version="1.0" '
    b'xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
    b'<xsl:template match="/"><out/></xsl:template>'
    b"</xsl:stylesheet>"
)

SEARCH_XSLT = (
    b'<?xml version="1.0"?>'
    b'<xsl:stylesheet version="1.0" '
    b'xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
    b'<xsl:output method="text"/>'
    b'<xsl:template match="/search"><xsl:value-of select="json"/></xsl:template>'
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
        content = SEARCH_XSLT if name == "search" else MINIMAL_XSLT
        (xsl_pages / f"{name}.xsl").write_bytes(content)
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

def test_validate_config_rejects_unknown_engine(tmp_path):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["engines"]["rss"] = "frobnicate"
    with pytest.raises(ValueError):
        validate_config(cfg)


@pytest.mark.parametrize("bad", [0, -1, "ten", True, 1.5])
def test_validate_config_rejects_bad_per_page(bad):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["site"]["pagination"]["per_page"] = bad
    with pytest.raises(ValueError, match="per_page"):
        validate_config(cfg)


@pytest.mark.parametrize("bad", [-1, "twenty", True, 1.5])
def test_validate_config_rejects_bad_rss_items(bad):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["site"]["pagination"]["rss_items"] = bad
    with pytest.raises(ValueError, match="rss_items"):
        validate_config(cfg)


def test_build_ctx_from_config_accepts_rss_items_zero():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["site"]["pagination"]["rss_items"] = 0
    validate_config(cfg)
    ctx = build_ctx_from_config(cfg, dry_run=False)
    assert ctx.rss_items == 0


@pytest.mark.parametrize("bad", [[], "en", ("en",), [""], ["en", 7], [True]])
def test_validate_config_rejects_bad_languages(bad):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["site"]["languages"] = bad
    with pytest.raises(ValueError, match="site.languages"):
        validate_config(cfg)


@pytest.mark.parametrize("bad", ["", None, "fr"])
def test_validate_config_rejects_bad_default_language(bad):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["site"]["default_language"] = bad
    with pytest.raises(ValueError, match="site.default_language"):
        validate_config(cfg)


@pytest.mark.parametrize(
    "key, pattern, message",
    [
        ("article", "/{lang}/articles/{slug}.html", "urls.article"),
        ("rss", "/rss/", "urls.rss"),
        ("article", "/{language}/articles/{slug}/", "placeholders"),
    ],
)
def test_validate_config_rejects_bad_url_shapes(key, pattern, message):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["urls"][key] = pattern
    with pytest.raises(ValueError, match=message):
        validate_config(cfg)


@pytest.mark.parametrize("bad", [0, -1, "many", True, 1.5])
def test_validate_config_rejects_bad_parallelism(bad):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["build"]["parallelism"] = bad
    with pytest.raises(ValueError, match="parallelism"):
        validate_config(cfg)


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
    ctx = cast(BuildCtx, dataclasses.replace(
        ctx,
        engines={
            **ctx.engines,
            "articles": SaxonCEngine(tmp_path / "fake-bin"),
        },
    ))
    import os
    assert _resolve_parallelism(ctx) == (os.cpu_count() or 4)


def test_resolve_parallelism_passes_through_explicit_value(tmp_path):
    ctx = _ctx_for(tmp_path)
    ctx = cast(BuildCtx, dataclasses.replace(ctx, parallelism=2))
    assert _resolve_parallelism(ctx) == 2


# --- copy_assets ---

def test_copy_assets_missing_src_noop(tmp_path):
    ctx = _ctx_for(tmp_path)
    (tmp_path / "assets").rmdir()
    ctx = cast(BuildCtx, dataclasses.replace(ctx, assets_dir=tmp_path / "assets"))
    copy_assets(ctx)
    assert not (tmp_path / "output" / "assets").exists()


def test_copy_assets_missing_src_removes_stale_output_and_cache(tmp_path):
    ctx = _ctx_for(tmp_path)
    cache = {}
    (tmp_path / "assets" / "x.txt").write_text("v1")
    copy_assets(ctx, cache)
    assert (tmp_path / "output" / "assets" / "x.txt").exists()

    shutil.rmtree(tmp_path / "assets")
    copy_assets(ctx, cache)

    assert not (tmp_path / "output" / "assets").exists()
    assert "assets" not in cache


def test_copy_assets_missing_src_dry_run_keeps_stale_output(tmp_path):
    ctx = _ctx_for(tmp_path)
    (tmp_path / "assets" / "x.txt").write_text("v1")
    copy_assets(ctx)
    shutil.rmtree(tmp_path / "assets")

    ctx = cast(
        BuildCtx,
        dataclasses.replace(ctx, assets_dir=tmp_path / "assets", dry_run=True),
    )
    copy_assets(ctx)

    assert (tmp_path / "output" / "assets" / "x.txt").exists()


def test_copy_assets_dry_run(tmp_path):
    ctx = _ctx_for(tmp_path)
    (tmp_path / "assets" / "x.txt").write_text("hi")
    ctx = cast(BuildCtx, dataclasses.replace(ctx, dry_run=True))
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


def test_copy_assets_skips_when_hash_unchanged(tmp_path, caplog):
    ctx = _ctx_for(tmp_path)
    cache = {}
    src = tmp_path / "assets" / "x.txt"
    dest = tmp_path / "output" / "assets" / "x.txt"
    (tmp_path / "assets" / "empty").mkdir()
    src.write_text("v1")
    copy_assets(ctx, cache)
    with caplog.at_level(logging.DEBUG):
        copy_assets(ctx, cache)
    assert dest.read_text() == "v1"
    assert any("Skipping unchanged assets" in r.message for r in caplog.records)


@pytest.mark.parametrize("invalid_entry", ["bad", {}, {"version": 0}])
def test_copy_assets_rebuilds_invalid_cache_version(tmp_path, invalid_entry):
    ctx = _ctx_for(tmp_path)
    cache = {}
    src = tmp_path / "assets" / "x.txt"
    dest = tmp_path / "output" / "assets" / "x.txt"
    src.write_text("source")
    copy_assets(ctx, cache)
    assert cache["assets"]["version"] == 1
    dest.write_text("stale")
    cache["assets"] = invalid_entry
    copy_assets(ctx, cache)
    assert dest.read_text() == "source"


def test_copy_assets_force_rebuilds_matching_manifest(tmp_path):
    ctx = _ctx_for(tmp_path)
    cache = {}
    src = tmp_path / "assets" / "x.txt"
    dest = tmp_path / "output" / "assets" / "x.txt"
    src.write_text("source")
    copy_assets(ctx, cache)
    dest.write_text("stale")
    copy_assets(dataclasses.replace(ctx, force=True), cache)
    assert dest.read_text() == "source"


def test_copy_assets_hashes_unchanged_files(tmp_path, monkeypatch):
    ctx = _ctx_for(tmp_path)
    cache = {}
    src = tmp_path / "assets" / "x.txt"
    src.write_text("v1")
    copy_assets(ctx, cache)

    calls = []

    def fail_hash(path):
        calls.append(path)
        return "same"

    monkeypatch.setattr("articulous.pipeline.file_hash", fail_hash)
    copy_assets(ctx, cache)
    assert calls == [src, tmp_path / "output" / "assets" / "x.txt"]


def test_copy_assets_recopies_when_hash_changes(tmp_path):
    ctx = _ctx_for(tmp_path)
    cache = {}
    src = tmp_path / "assets" / "x.txt"
    dest = tmp_path / "output" / "assets" / "x.txt"
    src.write_text("v1")
    copy_assets(ctx, cache)
    src.write_text("v2")
    copy_assets(ctx, cache)
    assert dest.read_text() == "v2"


def test_copy_assets_recopies_same_size_same_mtime_change(tmp_path):
    ctx = _ctx_for(tmp_path)
    cache = {}
    src = tmp_path / "assets" / "x.txt"
    dest = tmp_path / "output" / "assets" / "x.txt"
    src.write_text("v1")
    copy_assets(ctx, cache)

    stamp = src.stat()
    src.write_text("v2")
    os.utime(src, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    copy_assets(ctx, cache)

    assert dest.read_text() == "v2"


def test_copy_assets_delta_removes_stale_and_restores_changed(tmp_path):
    ctx = _ctx_for(tmp_path)
    cache = {}
    kept = tmp_path / "assets" / "kept.txt"
    removed = tmp_path / "assets" / "removed.txt"
    kept.write_text("v1")
    removed.write_text("bye")
    copy_assets(ctx, cache)
    out_kept = tmp_path / "output" / "assets" / "kept.txt"
    out_kept.write_text("local-edit")

    removed.unlink()
    copy_assets(ctx, cache)

    assert out_kept.read_text() == "v1"
    assert not (tmp_path / "output" / "assets" / "removed.txt").exists()


def test_copy_assets_restores_deleted_destination(tmp_path):
    ctx = _ctx_for(tmp_path)
    cache = {}
    source = tmp_path / "assets" / "x.txt"
    output = tmp_path / "output" / "assets" / "x.txt"
    source.write_text("source")
    copy_assets(ctx, cache)
    output.unlink()
    copy_assets(ctx, cache)
    assert output.read_text() == "source"


def test_copy_assets_restores_same_size_destination_edit(tmp_path):
    ctx = _ctx_for(tmp_path)
    cache = {}
    source = tmp_path / "assets" / "x.txt"
    output = tmp_path / "output" / "assets" / "x.txt"
    source.write_text("source")
    copy_assets(ctx, cache)
    output.write_text("edited")
    copy_assets(ctx, cache)
    assert output.read_text() == "source"


def test_copy_assets_refreshes_only_mismatched_file(tmp_path, monkeypatch):
    ctx = _ctx_for(tmp_path)
    cache = {}
    assets = tmp_path / "assets"
    output = tmp_path / "output" / "assets"
    (assets / "changed.txt").write_text("source")
    (assets / "kept.txt").write_text("kept")
    copy_assets(ctx, cache)
    (output / "changed.txt").write_text("edited")
    copied = []
    real_copy = shutil.copy2

    def track_copy(source, destination):
        copied.append(source)
        return real_copy(source, destination)

    monkeypatch.setattr("articulous.pipeline.shutil.copy2", track_copy)
    copy_assets(ctx, cache)
    assert copied == [assets / "changed.txt"]


def test_copy_assets_replaces_file_with_directory(tmp_path):
    ctx = _ctx_for(tmp_path)
    cache = {}
    source = tmp_path / "assets" / "node"
    source.write_text("file")
    copy_assets(ctx, cache)
    source.unlink()
    source.mkdir()
    (source / "child.txt").write_text("child")
    copy_assets(ctx, cache)
    assert (tmp_path / "output" / "assets" / "node" / "child.txt").is_file()


def test_copy_assets_replaces_directory_with_file(tmp_path):
    ctx = _ctx_for(tmp_path)
    cache = {}
    source = tmp_path / "assets" / "node"
    source.mkdir()
    (source / "child.txt").write_text("child")
    copy_assets(ctx, cache)
    output = tmp_path / "output" / "assets" / "node"
    (output / "untracked.txt").write_text("stale")
    shutil.rmtree(source)
    source.write_text("file")
    copy_assets(ctx, cache)
    assert output.read_text() == "file"


def test_copy_assets_rejects_overlapping_source_and_dest(tmp_path):
    ctx = _ctx_for(tmp_path)
    assets = tmp_path / "output" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    ctx = cast(BuildCtx, dataclasses.replace(ctx, assets_dir=assets))
    with pytest.raises(ValueError, match="overlap"):
        copy_assets(ctx, {})


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


def test_search_item_xml_escapes():
    item = {
        "title": "A&B",
        "description": "<d>",
        "url": "https://e.test/?a=1&b=2",
        "tags": ["x<y"],
    }
    out = _search_item_xml(item)
    assert "A&amp;B" in out
    assert "&lt;d&gt;" in out
    assert "x&lt;y" in out


def test_encode_xml():
    assert _encode_xml("<x/>") == b"<x/>"


# --- Per-section doc synthesisers ---

def test_index_doc_attrs():
    p = IndexPage(
        lang="en", page=2, total_pages=5,
        articles=[_art("a")], output_path=Path("p"),
        url="https://e.test/en/page/2/",
    )
    doc = _index_doc(p, "My Site")
    assert doc.startswith("<index site=\"My Site\" lang=\"en\" page=\"2\" total=\"5\" ")
    assert "self=\"https://e.test/en/page/2/\"" in doc
    assert "<article>" in doc


def test_tag_doc_includes_display_name():
    p = TagPage(
        lang="en", tag="News & Updates", tag_slug="news-updates",
        articles=[_art("a")], output_path=Path("p"),
        url="https://e.test/en/tags/news-updates/",
    )
    doc = _tag_doc(p, "My Site")
    assert "<display-name>News &amp; Updates</display-name>" in doc
    assert "slug=\"news-updates\"" in doc
    assert "site=\"My Site\"" in doc


def test_rss_doc_self_attr():
    feed = RssFeed(
        articles=[_art("a")], output_path=Path("rss.xml"),
        url="https://e.test/rss.xml",
    )
    doc = _rss_doc(feed, "My Site")
    assert doc.startswith("<rss site=\"My Site\" self=\"https://e.test/rss.xml\">")


def test_sitemap_doc_self_attr():
    sm = Sitemap(
        urls=["https://e.test/a/"], output_path=Path("sitemap.xml"),
        url="https://e.test/sitemap.xml",
    )
    doc = _sitemap_doc(sm, "My Site")
    assert doc.startswith(
        "<sitemap site=\"My Site\" self=\"https://e.test/sitemap.xml\">"
    )
    assert "<url>https://e.test/a/</url>" in doc


def test_search_doc_includes_json_and_items():
    index = SimpleNamespace(
        items=[{"title": "A", "description": "d", "url": "u", "tags": ["t"]}],
    )
    doc = _search_doc(index, "My Site")
    assert doc.startswith("<search site=\"My Site\">")
    assert '"title": "A"' in doc
    assert "<item><title>A</title>" in doc


def test_site_name_escaped_in_attrs():
    """Untrusted site_name characters get attribute-escaped + well-formed."""
    p = IndexPage(
        lang="en", page=1, total_pages=1,
        articles=[], output_path=Path("p"),
        url="https://e.test/en/page/1/",
    )
    doc = _index_doc(p, 'Foo & <Bar>')
    # &/</> escaped → result parses as XML
    import lxml.etree as etree
    root = etree.fromstring(doc.encode())
    assert root.get("site") == "Foo & <Bar>"


# --- _make_xslt_task ---

def test_make_xslt_task_bytes_hashes_in_memory(tmp_path):
    ctx = _ctx_for(tmp_path)
    xsl = tmp_path / "xsl" / "pages" / "rss.xsl"
    cache = {}
    task = _make_xslt_task(
        xml_input=b"<root/>",
        xsl_path=xsl, xsl_hash="abc",
        output_path=tmp_path / "output" / "out.html",
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
        output_path=tmp_path / "output" / "out.html",
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
    output = tmp_path / "output" / "out.html"
    output.write_text("cached")
    task = _make_xslt_task(
        xml_input=b"<root/>", xsl_path=xsl, xsl_hash="xsl_h",
        output_path=output,
        cache=cache, cache_key="k",
        engine=LxmlEngine(), ctx=ctx,
    )
    assert task is None


def test_make_xslt_task_rebuilds_when_output_missing(tmp_path):
    ctx = _ctx_for(tmp_path)
    xsl = tmp_path / "xsl" / "pages" / "rss.xsl"
    import hashlib
    pre_xml_hash = hashlib.sha256(b"<root/>").hexdigest()
    cache = {"k": [pre_xml_hash, "xsl_h"]}
    task = _make_xslt_task(
        xml_input=b"<root/>", xsl_path=xsl, xsl_hash="xsl_h",
        output_path=tmp_path / "output" / "missing.html",
        cache=cache, cache_key="k",
        engine=LxmlEngine(), ctx=ctx,
    )
    assert task is not None


def test_make_xslt_task_cache_not_committed_on_failure(tmp_path):
    ctx = _ctx_for(tmp_path)
    # broken xsl content → XSLTParseError
    broken = tmp_path / "broken.xsl"
    broken.write_bytes(b"<not-a-stylesheet/>")
    cache = {}
    task = _make_xslt_task(
        xml_input=b"<root/>", xsl_path=broken, xsl_hash="xsl_h",
        output_path=tmp_path / "output" / "out.html",
        cache=cache, cache_key="bad",
        engine=LxmlEngine(), ctx=ctx,
    )
    assert task is not None
    with pytest.raises(etree.XSLTParseError):
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
    for t in tasks:
        t()
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
    for t in tasks:
        t()
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
    for t in tasks:
        t()
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
    out = tmp_path / "output" / "search.json"
    assert json.loads(out.read_text())[0]["title"] == "A"
    assert build_search_section(items, ctx, cache) == []


def test_build_streamed_sitemap_and_search_sections(tmp_path):
    ctx = _ctx_for(tmp_path)
    cache = {}
    with TempWorkspace() as workspace:
        urls = FragmentSink(workspace)
        urls.append(_sitemap_url_xml("https://e.test/a/"))
        tasks = build_sitemap_section(urls, ctx, cache, workspace)
        assert len(tasks) == 1
        tasks[0]()

        items = SearchSink(workspace)
        items.append_item({
            "title": "A", "description": "d",
            "url": "https://e.test/a/", "tags": ["t"],
        })
        tasks = build_search_section(items, ctx, cache, workspace)
        assert len(tasks) == 1
        tasks[0]()


def test_cross_builders_accept_manifest_as_fifth_arg(tmp_path):
    ctx = _ctx_for(tmp_path)
    manifest = {}
    assert build_sitemap_section([], ctx, {}, manifest) != []
    assert build_search_section([], ctx, {}, manifest) != []
    assert "sitemap" in manifest
    assert "search" in manifest


def test_sorted_store_articles_none_returns_empty():
    assert _sorted_store_articles(None, "en") == []


def test_sorted_store_articles_uses_sorted_chunk_batch(tmp_path, monkeypatch):
    monkeypatch.setattr("articulous.pipeline._SORT_CHUNK_SIZE", 2)
    with TempWorkspace() as workspace:
        store = ArticleStore(workspace)
        store.append("en", dataclasses.replace(
            _art("old"), datetime=datetime(2024, 1, 1),
        ))
        store.append("en", dataclasses.replace(
            _art("new"), datetime=datetime(2026, 1, 1),
        ))
        store.append("en", dataclasses.replace(
            _art("mid"), datetime=datetime(2025, 1, 1),
        ))

        batch = _sorted_store_articles(store, "en")

        assert len(batch) == 3
        assert [a.slug for a in batch] == ["new", "mid", "old"]
        assert getattr(batch[0], "slug") == "new"
        assert [a.slug for a in batch[1:]] == ["mid", "old"]
        assert batch != []
        assert _sorted_store_articles(store, "fr") == []


# --- _passes_cli_filters ---

class _FakeCLI:
    def __init__(self, langs=None, slugs=None, sections=None):
        self.only_langs = langs
        self.only_slugs = slugs
        self.only_sections = sections

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
    ctx = cast(BuildCtx, dataclasses.replace(ctx, rss_items=2))
    articles = [_art(f"a{i}") for i in range(5)]
    # Datetimes differ so the heap ordering is deterministic
    articles = [
        dataclasses.replace(a, datetime=datetime(2025, 1, i + 1))
        for i, a in enumerate(articles)
    ]
    projection = _stream_projections(
        lambda: iter(articles), _FakeCLI(), ctx,
    )
    assert projection.total == 5
    assert len(projection.sitemap_urls) == 5
    assert len(projection.search_items) == 5
    assert len(projection.rss_heap) == 2  # bounded by rss_items
    # Heap contains the two newest
    dates = sorted(dt for dt, _, _ in projection.rss_heap)
    assert dates == [datetime(2025, 1, 4), datetime(2025, 1, 5)]


def test_stream_projections_respects_cli_filters(tmp_path):
    ctx = _ctx_for(tmp_path)
    articles = [_art("a", lang="en"), _art("b", lang="fr")]
    projection = _stream_projections(
        lambda: iter(articles), _FakeCLI(langs=["en"]), ctx,
    )
    assert projection.total == 1
    projection.sitemap_urls.flush()
    assert articles[0].url in projection.sitemap_urls.path.read_text()


def test_stream_projections_can_partition_without_cross_work(tmp_path):
    ctx = _ctx_for(tmp_path)
    articles = [_art("a", lang="en"), _art("b", lang="fr")]
    projection = _stream_projections(
        lambda: iter(articles),
        _FakeCLI(),
        ctx,
        collect_cross=False,
        collect_articles=True,
    )
    assert projection.sitemap_urls == []
    assert projection.search_items == []
    assert projection.rss_heap == []
    assert projection.articles_by_lang is not None
    assert [a.slug for a in projection.articles_by_lang.iter_lang("en")] == ["a"]
    assert [a.slug for a in projection.articles_by_lang.iter_lang("fr")] == ["b"]


def test_stream_projections_respects_publication_policy(tmp_path):
    ctx = _ctx_for(tmp_path)
    articles = [
        dataclasses.replace(_art("published"), publication="published"),
        dataclasses.replace(_art("unlisted"), publication="unlisted"),
        dataclasses.replace(_art("draft"), publication="draft"),
    ]
    projection = _stream_projections(
        lambda: iter(articles), _FakeCLI(), ctx, collect_articles=True,
    )
    assert projection.total == 2
    assert projection.skipped_by_publication == {"draft": 1}
    assert len(projection.sitemap_urls) == 1
    assert len(projection.search_items) == 1
    assert projection.articles_by_lang is not None
    assert projection.listings_by_lang is not None
    assert [a.slug for a in projection.articles_by_lang.iter_lang("en")] == [
        "published", "unlisted",
    ]
    assert [a.slug for a in projection.listings_by_lang.iter_lang("en")] == [
        "published",
    ]


def test_log_article_stats_includes_unpublished(tmp_path, caplog):
    ctx = _ctx_for(tmp_path)
    article = dataclasses.replace(_art("draft"), publication="draft")
    projection = _stream_projections(lambda: iter([article]), _FakeCLI(), ctx)
    stats = ArticleStats(scanned=1, parsed=1)
    with caplog.at_level(logging.INFO):
        _log_article_stats(stats, projection)
    assert any("draft article(s) skipped" in r.message for r in caplog.records)


def test_cleanup_stream_projection_accepts_none():
    _cleanup_stream_projection(None)


def test_rss_sorted_from_heap_newest_first(tmp_path):
    ctx = _ctx_for(tmp_path)
    articles = [
        dataclasses.replace(_art("a"), datetime=datetime(2025, 1, 1)),
        dataclasses.replace(_art("b"), datetime=datetime(2025, 6, 1)),
        dataclasses.replace(_art("c"), datetime=datetime(2025, 3, 1)),
    ]
    projection = _stream_projections(
        lambda: iter(articles), _FakeCLI(), ctx,
    )
    out = _rss_sorted_from_heap(projection.rss_heap)
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
    ctx_multilang = cast(
        BuildCtx,
        dataclasses.replace(ctx, languages=["en", "fr"]),
    )
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


def test_collect_tasks_reads_stream_once_for_all_sections(tmp_path):
    ctx = _ctx_for(tmp_path)
    ctx = cast(BuildCtx, dataclasses.replace(ctx, languages=["en", "fr"]))
    art_xml = tmp_path / "content" / "a.xml"
    art_xml.write_text(
        '<article><title>A</title><date>2025-01-01</date>'
        '<description>d</description></article>'
    )
    articles = [
        dataclasses.replace(_art("a", lang="en"), source_path=art_xml),
        dataclasses.replace(_art("b", lang="fr"), source_path=art_xml),
    ]
    calls = 0

    def stream_factory():
        nonlocal calls
        calls += 1
        return iter(articles)

    plan = _collect_tasks(stream_factory, _FakeCLI(), ctx, {})
    assert calls == 1
    assert {"articles", "index", "rss", "sitemap", "search"}.issubset(plan)


def test_collect_tasks_rejects_duplicate_cache_key(tmp_path):
    ctx = _ctx_for(tmp_path)
    art_xml = tmp_path / "content" / "a.xml"
    art_xml.write_text(
        '<article><title>A</title><date>2025-01-01</date>'
        '<description>d</description></article>'
    )
    a = dataclasses.replace(_art("same"), source_path=art_xml)
    b = dataclasses.replace(_art("same"), source_path=art_xml)
    cli = _FakeCLI(sections=["articles"])

    def stream_factory():
        return iter([a, b])

    with pytest.raises(ValueError, match="Duplicate generated cache key"):
        _collect_tasks(stream_factory, cli, ctx, {}, {})


def test_collect_tasks_rejects_duplicate_output_path(tmp_path):
    ctx = _ctx_for(tmp_path)
    ctx = cast(BuildCtx, dataclasses.replace(
        ctx,
        url_patterns={**ctx.url_patterns, "rss": "/feed.xml", "sitemap": "/feed.xml"},
    ))
    cli = _FakeCLI()

    def stream_factory():
        return iter(())

    with pytest.raises(ValueError, match="Duplicate generated output path"):
        _collect_tasks(stream_factory, cli, ctx, {}, {})


def test_collect_tasks_rejects_output_escape(tmp_path):
    ctx = _ctx_for(tmp_path)
    ctx = cast(BuildCtx, dataclasses.replace(
        ctx,
        url_patterns={**ctx.url_patterns, "rss": "/../rss.xml"},
    ))
    cli = _FakeCLI(sections=["rss"])

    def stream_factory():
        return iter(())

    with pytest.raises(ValueError, match="escapes output_dir"):
        _collect_tasks(stream_factory, cli, ctx, {}, {})


def test_prune_stale_outputs_handles_manifest_edges(tmp_path, caplog):
    ctx = _ctx_for(tmp_path)
    root_file = tmp_path / "output" / "root.txt"
    root_file.write_text("old")
    old_dir = tmp_path / "output" / "old-dir"
    old_dir.mkdir()
    missing = tmp_path / "output" / "missing.txt"
    assert not missing.exists()
    cache = {"root": ["h"], "dir": ["h"], "missing": ["h"], "bad": ["h"]}
    old = {
        "root": "root.txt",
        "dir": "old-dir",
        "missing": "missing.txt",
        "bad": str(tmp_path.parent / "outside.txt"),
    }
    with caplog.at_level(logging.WARNING):
        _prune_stale_outputs(ctx, cache, old, {})
    assert not root_file.exists()
    assert not old_dir.exists()
    assert cache == {}
    assert any("invalid cached output manifest" in r.message for r in caplog.records)


def test_stream_projections_replaces_older_top(tmp_path):
    """Older articles arriving after the heap is full are rejected."""
    ctx = _ctx_for(tmp_path)
    ctx = cast(BuildCtx, dataclasses.replace(ctx, rss_items=2))
    # First two seed the heap (newer datetimes), third is older and
    # must be rejected by the heapq.heapreplace branch's else.
    arts = [
        dataclasses.replace(_art("a"), datetime=datetime(2025, 6, 1)),
        dataclasses.replace(_art("b"), datetime=datetime(2025, 5, 1)),
        dataclasses.replace(_art("c"), datetime=datetime(2024, 1, 1)),
    ]
    projection = _stream_projections(
        lambda: iter(arts), _FakeCLI(), ctx,
    )
    assert projection.total == 3
    slugs = sorted(art.slug for _, _, art in projection.rss_heap)
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


def test_run_build_rebuilds_missing_cached_output(site_root):
    from articulous.config import apply_cli_overrides, load_or_create_config
    cfg = load_or_create_config(site_root / "config.json")
    cli = _CLI(force_full_build=True)
    apply_cli_overrides(cfg, cli, site_root)
    run_build(cli, cfg, site_root)
    rss = site_root / "output" / "rss.xml"
    rss.unlink()

    cfg2 = load_or_create_config(site_root / "config.json")
    cli2 = _CLI()
    apply_cli_overrides(cfg2, cli2, site_root)
    run_build(cli2, cfg2, site_root)
    assert rss.exists()


def test_run_build_prunes_deleted_article_output(site_root):
    from articulous.config import apply_cli_overrides, load_or_create_config
    cfg = load_or_create_config(site_root / "config.json")
    cli = _CLI(force_full_build=True)
    apply_cli_overrides(cfg, cli, site_root)
    run_build(cli, cfg, site_root)
    output = site_root / "output" / "en" / "articles" / "first-post" / "index.html"
    assert output.exists()
    (site_root / "content" / "en" / "first-post.xml").unlink()

    cfg2 = load_or_create_config(site_root / "config.json")
    cli2 = _CLI()
    apply_cli_overrides(cfg2, cli2, site_root)
    run_build(cli2, cfg2, site_root)
    cache = json.loads((site_root / ".build-cache.json").read_text())
    assert not output.exists()
    assert "article:en:first-post" not in cache


def test_run_build_partial_build_does_not_prune(site_root):
    from articulous.config import apply_cli_overrides, load_or_create_config
    cfg = load_or_create_config(site_root / "config.json")
    cli = _CLI(force_full_build=True)
    apply_cli_overrides(cfg, cli, site_root)
    run_build(cli, cfg, site_root)
    output = site_root / "output" / "en" / "articles" / "first-post" / "index.html"
    (site_root / "content" / "en" / "first-post.xml").unlink()

    cfg2 = load_or_create_config(site_root / "config.json")
    cli2 = _CLI(only_sections=["search"])
    apply_cli_overrides(cfg2, cli2, site_root)
    run_build(cli2, cfg2, site_root)
    assert output.exists()


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
    search = site_root / "output" / "search.json"
    assert json.loads(search.read_text())
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
