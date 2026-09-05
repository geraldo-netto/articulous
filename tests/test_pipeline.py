"""Unit tests for articulous.pipeline."""
import copy
import dataclasses
import json
import logging
import os
import shutil
import tracemalloc
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import lxml.etree as etree
import pytest

from articulous.articles import Article, ArticleStats
from articulous.config import DEFAULT_CONFIG, validate_config
from articulous.engines import LxmlEngine, SaxonCEngine, stylesheet_hash
from articulous.filesystem import TempWorkspace, cache_lock_path, lock_file
from articulous.pipeline import (
    ArticleStore,
    BuildCtx,
    OutputManifest,
    SearchSink,
    SitemapSink,
    _article_url_builder,
    _article_xml,
    _cache_path_for,
    _cleanup_stream_projection,
    _collect_tasks,
    _encode_xml,
    _index_doc,
    _load_build_cache,
    _log_article_stats,
    _lock_path_for,
    _make_xslt_task,
    _passes_cli_filters,
    _prune_stale_outputs,
    _resolve_parallelism,
    _run_plan,
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
from articulous.ownership import load_ownership, ownership_path
from articulous.sections import SECTION_NAMES


pytestmark = pytest.mark.usefixtures("projection_workspace_cleanup")


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


@pytest.mark.parametrize("kind", ["file", "directory", "missing"])
def test_copy_assets_rejects_source_symlinks(tmp_path, kind):
    ctx = _ctx_for(tmp_path)
    target = tmp_path / "outside"
    makers = {
        "file": lambda: target.write_text("secret"),
        "directory": target.mkdir,
        "missing": lambda: None,
    }
    makers[kind]()
    (ctx.assets_dir / "linked").symlink_to(target)
    with pytest.raises(ValueError, match="symlinks"):
        copy_assets(ctx, {})
    assert not (ctx.output_dir / "assets").exists()


def test_copy_assets_rejects_special_sources(tmp_path):
    ctx = _ctx_for(tmp_path)
    os.mkfifo(ctx.assets_dir / "pipe")
    with pytest.raises(ValueError, match="special files"):
        copy_assets(ctx, {})


def test_invalid_asset_source_preserves_published_mirror(tmp_path):
    ctx = _ctx_for(tmp_path)
    (ctx.assets_dir / "style.css").write_text("published")
    cache = {}
    copy_assets(ctx, cache)
    previous_cache = copy.deepcopy(cache)
    shutil.rmtree(ctx.assets_dir)
    ctx.assets_dir.write_text("invalid source")
    with pytest.raises(ValueError, match="must be a directory"):
        copy_assets(ctx, cache)
    assert (ctx.output_dir / "assets/style.css").read_text() == "published"
    assert cache == previous_cache


@pytest.mark.parametrize("component", ["assets", "assets/nested", "assets/nested/file.txt"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_copy_assets_rejects_destination_symlinks(tmp_path, component, dry_run):
    ctx = dataclasses.replace(_ctx_for(tmp_path), dry_run=dry_run)
    source = ctx.assets_dir / "nested/file.txt"
    source.parent.mkdir()
    source.write_text("replacement")
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "file.txt"
    marker.write_text("keep")
    link = ctx.output_dir / component
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        copy_assets(ctx, {})
    assert marker.read_text() == "keep"


@pytest.mark.parametrize("rel", ["../outside", "/outside", "."])
@pytest.mark.parametrize("dry_run", [False, True])
def test_asset_cache_paths_cannot_escape_destination(tmp_path, rel, dry_run):
    ctx = dataclasses.replace(_ctx_for(tmp_path), dry_run=dry_run)
    cache = {"assets": {"version": 1, "manifest": {rel: ["d", 0]}}}
    with pytest.raises(ValueError, match="Invalid asset output path"):
        copy_assets(ctx, cache)
    assert not (ctx.output_dir / "assets").exists()


@pytest.mark.parametrize("dry_run", [False, True])
def test_asset_destination_hardlink_preserves_external_file(tmp_path, dry_run):
    ctx = dataclasses.replace(_ctx_for(tmp_path), dry_run=dry_run)
    (ctx.assets_dir / "style.css").write_text("replacement")
    victim = tmp_path / "outside.txt"
    victim.write_text("private")
    destination = ctx.output_dir / "assets/style.css"
    destination.parent.mkdir()
    os.link(victim, destination)
    with pytest.raises(ValueError, match="hardlink"):
        copy_assets(ctx, {})
    assert victim.read_text() == "private"
    assert destination.read_text() == "private"


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


@pytest.mark.parametrize("manifest", [
    None, [], {"style.css": None}, {"style.css": []},
    {"style.css": [{}]}, {"style.css": ["unknown"]},
    {"style.css": ["f", 1]}, {"style.css": ["f", True, 0, "hash"]},
    {"style.css": ["f", 1, "bad time", "hash"]}, {1: ["d", 0]},
])
def test_asset_cache_invalid_metadata_is_rebuilt(tmp_path, manifest):
    ctx = _ctx_for(tmp_path)
    (ctx.assets_dir / "style.css").write_text("source")
    cache = {"assets": {"version": 1, "manifest": manifest}}
    copy_assets(ctx, cache)
    assert (ctx.output_dir / "assets/style.css").read_text() == "source"
    assert cache["assets"]["manifest"]["style.css"][0] == "f"


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


@pytest.mark.parametrize("changed", ["assets", "assets/folder", "assets/folder/style.css"])
def test_asset_mirror_repairs_destination_type_drift(tmp_path, changed):
    ctx = _ctx_for(tmp_path)
    source = ctx.assets_dir / "folder/style.css"
    source.parent.mkdir()
    source.write_text("source")
    cache = {}
    copy_assets(ctx, cache)
    target = ctx.output_dir / changed
    if target.is_dir():
        shutil.rmtree(target)
        target.write_text("wrong type")
    else:
        target.unlink()
        target.mkdir()
    copy_assets(ctx, cache)
    assert (ctx.output_dir / "assets/folder/style.css").read_text() == "source"


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
        xsl_path=xsl, xsl_hash=stylesheet_hash(xsl),
        output_path=tmp_path / "output" / "out.html",
        cache=cache, cache_key="k",
        engine=LxmlEngine(), ctx=ctx,
    )
    assert task is not None
    task()
    import hashlib
    expected = hashlib.sha256(b"<root/>").hexdigest()
    assert cache["k"] == [expected, stylesheet_hash(xsl), LxmlEngine().cache_identity, "out.html"]


def test_make_xslt_task_path_hashes_file(tmp_path):
    ctx = _ctx_for(tmp_path)
    xml = tmp_path / "in.xml"
    xml.write_bytes(b"<root/>")
    xsl = tmp_path / "xsl" / "pages" / "rss.xsl"
    cache = {}
    task = _make_xslt_task(
        xml_input=xml, xsl_path=xsl, xsl_hash=stylesheet_hash(xsl),
        output_path=tmp_path / "output" / "out.html",
        cache=cache, cache_key="k",
        engine=LxmlEngine(), ctx=ctx,
    )
    assert task is not None
    task()
    assert cache["k"][1] == stylesheet_hash(xsl)


def test_make_xslt_task_cached_returns_none(tmp_path):
    ctx = _ctx_for(tmp_path)
    xsl = tmp_path / "xsl" / "pages" / "rss.xsl"
    import hashlib
    pre_xml_hash = hashlib.sha256(b"<root/>").hexdigest()
    cache = {"k": [pre_xml_hash, "xsl_h", LxmlEngine().cache_identity, "out.html"]}
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
    cache = {"k": [pre_xml_hash, "xsl_h", LxmlEngine().cache_identity, "missing.html"]}
    task = _make_xslt_task(
        xml_input=b"<root/>", xsl_path=xsl, xsl_hash="xsl_h",
        output_path=tmp_path / "output" / "missing.html",
        cache=cache, cache_key="k",
        engine=LxmlEngine(), ctx=ctx,
    )
    assert task is not None


def test_make_xslt_task_rebuilds_when_engine_changes(tmp_path):
    ctx = _ctx_for(tmp_path)
    xsl = tmp_path / "xsl" / "pages" / "rss.xsl"
    import hashlib
    pre_xml_hash = hashlib.sha256(b"<root/>").hexdigest()
    cache = {"k": [pre_xml_hash, "xsl_h", LxmlEngine().cache_identity, "out.html"]}
    output = tmp_path / "output" / "out.html"
    output.write_text("cached")
    task = _make_xslt_task(
        xml_input=b"<root/>", xsl_path=xsl, xsl_hash="xsl_h",
        output_path=output,
        cache=cache, cache_key="k",
        engine=SaxonCEngine(tmp_path / "Transform"), ctx=ctx,
    )
    assert task is not None


def test_make_xslt_task_cache_not_committed_on_failure(tmp_path):
    ctx = _ctx_for(tmp_path)
    # broken xsl content → XSLTParseError
    broken = tmp_path / "broken.xsl"
    broken.write_bytes(b"<not-a-stylesheet/>")
    cache = {}
    task = _make_xslt_task(
        xml_input=b"<root/>", xsl_path=broken, xsl_hash=stylesheet_hash(broken),
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
    tasks = list(build_articles_section([a], ctx, {}))
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
    tasks = list(build_articles_section([a], ctx, cache))
    for t in tasks:
        t()
    assert list(build_articles_section([a], ctx, cache)) == []


def test_build_index_section_runs(tmp_path):
    ctx = _ctx_for(tmp_path)
    arts = [_art("a"), _art("b")]
    tasks = list(build_index_section(arts, "en", ctx, {}))
    assert len(tasks) == 1
    tasks[0]()
    assert (tmp_path / "output" / "en" / "page" / "1" / "index.html").exists()


def test_build_index_section_cached(tmp_path):
    ctx = _ctx_for(tmp_path)
    arts = [_art("a")]
    cache = {}
    tasks = list(build_index_section(arts, "en", ctx, cache))
    for t in tasks:
        t()
    assert list(build_index_section(arts, "en", ctx, cache)) == []


def test_index_planning_does_not_retain_page_payloads(tmp_path):
    ctx = dataclasses.replace(_ctx_for(tmp_path), per_page=1)
    articles = [dataclasses.replace(_art(str(i)), title="x" * 65_536) for i in range(200)]
    tracemalloc.start()
    try:
        tasks = build_index_section(articles, "en", ctx, {})
        _, peak = tracemalloc.get_traced_memory()
        tasks.close()
    finally:
        tracemalloc.stop()
    assert len(tasks) == 200
    assert peak < 2_000_000


def test_run_plan_closes_queues_after_failure(tmp_path, monkeypatch):
    ctx = dataclasses.replace(_ctx_for(tmp_path), per_page=1, parallelism=1)
    tasks = build_index_section([_art(str(i)) for i in range(10)], "en", ctx, {})
    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise ValueError("transform failed")

    monkeypatch.setattr(LxmlEngine, "run", fail)
    with pytest.raises(ValueError, match="transform failed"):
        _run_plan({"index": tasks}, ctx)
    assert tasks._file.closed
    assert len(calls) <= 2


def test_build_tags_section_runs(tmp_path):
    ctx = _ctx_for(tmp_path)
    arts = [_art("a", tags=("news",))]
    tasks = list(build_tags_section(arts, "en", ctx, {}))
    assert len(tasks) == 1
    tasks[0]()


def test_build_tags_section_cached(tmp_path):
    ctx = _ctx_for(tmp_path)
    arts = [_art("a", tags=("news",))]
    cache = {}
    tasks = list(build_tags_section(arts, "en", ctx, cache))
    for t in tasks:
        t()
    assert list(build_tags_section(arts, "en", ctx, cache)) == []


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


def test_native_sitemap_enforces_url_limit(tmp_path):
    ctx = _ctx_for(tmp_path)
    urls = ["https://e.test/page/"] * 50_000
    build_sitemap_section(urls, ctx, {})[0]()
    output = ctx.output_dir / "sitemap.xml"
    previous = output.read_bytes()
    with pytest.raises(ValueError, match="50,000 URL"):
        build_sitemap_section([*urls, "https://e.test/extra/"], ctx, {})[0]()
    assert output.read_bytes() == previous


def test_native_sitemap_counts_utf8_bytes(tmp_path, monkeypatch):
    ctx = _ctx_for(tmp_path)
    urls = ["https://e.test/é/"]
    build_sitemap_section(urls, ctx, {})[0]()
    output = ctx.output_dir / "sitemap.xml"
    previous = output.read_bytes()
    monkeypatch.setattr("articulous.pipeline._SITEMAP_MAX_BYTES", len(previous))
    build_sitemap_section(urls, ctx, {})[0]()
    with pytest.raises(ValueError, match="50 MiB"):
        build_sitemap_section(["https://e.test/éé/"], ctx, {})[0]()
    assert output.read_bytes() == previous


@pytest.mark.parametrize("section,source", [
    ("search", [{"title": "new"}]), ("sitemap", ["https://e.test/new/"]),
])
def test_native_failure_preserves_published_output(tmp_path, monkeypatch, section, source):
    ctx = _ctx_for(tmp_path)
    output = ctx.output_dir / ctx.url_patterns[section].lstrip("/")
    output.write_text("published")
    cache = {}
    builder = {"search": build_search_section, "sitemap": build_sitemap_section}[section]
    tasks = builder(source, ctx, cache)

    def broken_stream(values):
        yield values[0]
        raise OSError("source read failed")

    monkeypatch.setattr("articulous.pipeline._source_values", broken_stream)
    with pytest.raises(OSError, match="source read failed"):
        tasks[0]()
    assert output.read_text() == "published"
    assert cache == {}


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
        urls = SitemapSink(workspace)
        urls.append_url("https://e.test/a/")
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
    sitemap = tmp_path / "output" / "sitemap.xml"
    root = etree.parse(str(sitemap)).getroot()
    assert root.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset"
    assert root.findtext("{*}url/{*}loc") == "https://e.test/a/"
    search = tmp_path / "output" / "search.json"
    assert json.loads(search.read_text())[0]["title"] == "A"


def test_build_streamed_cross_sections_with_xslt(tmp_path):
    ctx = _ctx_for(tmp_path, engines={"sitemap": "lxml", "search": "lxml"})
    with TempWorkspace() as workspace:
        urls = SitemapSink(workspace)
        urls.append_url("https://e.test/a/")
        sitemap_tasks = build_sitemap_section(urls, ctx, {}, workspace)

        items = SearchSink(workspace)
        for title in ("A", "B"):
            items.append_item({
                "title": title, "description": "d",
                "url": f"https://e.test/{title.lower()}/", "tags": ["t"],
            })
        search_tasks = build_search_section(items, ctx, {}, workspace)
        sitemap_tasks[0]()
        search_tasks[0]()
    search = tmp_path / "output" / "search.json"
    assert [item["title"] for item in json.loads(search.read_text())] == ["A", "B"]


def test_build_in_memory_cross_sections_with_xslt(tmp_path):
    ctx = _ctx_for(tmp_path, engines={"sitemap": "lxml", "search": "lxml"})
    sitemap_tasks = build_sitemap_section(["https://e.test/a/"], ctx, {})
    search_tasks = build_search_section([{
        "title": "A", "description": "d",
        "url": "https://e.test/a/", "tags": ["t"],
    }], ctx, {})
    sitemap_tasks[0]()
    search_tasks[0]()
    search = tmp_path / "output" / "search.json"
    assert json.loads(search.read_text())[0]["title"] == "A"


def test_cross_builders_accept_manifest_as_fifth_arg(tmp_path):
    ctx = _ctx_for(tmp_path)
    manifest = OutputManifest()
    assert build_sitemap_section([], ctx, {}, manifest) != []
    assert build_search_section([], ctx, {}, manifest) != []
    assert "sitemap" in manifest
    assert "search" in manifest


def test_sorted_store_articles_none_returns_empty():
    assert _sorted_store_articles(None, "en") == []


def test_article_sort_bounds_open_chunks_and_closes_early(tmp_path, monkeypatch):
    import articulous.pipeline as pipeline
    monkeypatch.setattr(pipeline, "_SORT_CHUNK_SIZE", 2)
    monkeypatch.setattr(pipeline, "_SORT_MERGE_FAN_IN", 3)
    actual_read = pipeline._read_pickled_articles
    opened = {"current": 0, "peak": 0}

    def tracked_read(path, count):
        opened["current"] += 1
        opened["peak"] = max(opened.values())
        try:
            yield from actual_read(path, count)
        finally:
            opened["current"] -= 1

    monkeypatch.setattr(pipeline, "_read_pickled_articles", tracked_read)
    with TempWorkspace() as workspace:
        store = ArticleStore(workspace)
        articles = [_art(str(index)) for index in range(50)]
        for article in articles:
            store.append("en", article)
        batch = store.sorted("en")
        assert list(batch) == articles
        stream = iter(batch)
        next(stream)
        stream.close()
        store.close()
    assert opened["current"] == 0
    assert opened["peak"] <= 3


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
    assert articles[1].url in projection.sitemap_urls.path.read_text()


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


def test_failed_stream_closes_all_projection_handles(tmp_path, monkeypatch):
    ctx = _ctx_for(tmp_path)
    handles = []
    original = TempWorkspace.named_file
    def track(workspace, *args, **kwargs):
        file = original(workspace, *args, **kwargs)
        handles.append(file)
        return file
    def fail_stream():
        yield _art("a")
        raise OSError("article stream failed")
    monkeypatch.setattr(TempWorkspace, "named_file", track)
    with TempWorkspace() as workspace:
        with pytest.raises(OSError, match="article stream failed") as error:
            _collect_tasks(fail_stream, _FakeCLI(), ctx, {}, workspace)
        assert error.value.__traceback__ is not None
        assert len(handles) == 4
        assert all(file.closed for file in handles)
    assert all(not Path(file.name).exists() for file in handles)


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

@pytest.mark.parametrize("section,expected", [
    ("articles", (True, False, 0, 0, 0)),
    ("index", (False, True, 0, 0, 0)),
    ("tags", (False, True, 0, 0, 0)),
    ("rss", (False, False, 0, 0, 1)),
    ("sitemap", (False, False, 1, 0, 0)),
    ("search", (False, False, 0, 1, 0)),
])
def test_section_build_collects_only_consumed_projections(tmp_path, section, expected):
    ctx = _ctx_for(tmp_path)
    source = ctx.content_dir / "a.xml"
    source.write_text("<article><title>a</title><date>2024-01-01</date></article>")
    article = dataclasses.replace(_art("a", tags=("tag",)), source_path=source)
    with TempWorkspace() as workspace:
        plan = _collect_tasks(lambda: iter([article]), _FakeCLI(sections=[section]), ctx, {}, workspace)
        projection = plan.projection
        observed = (
            projection.articles_by_lang is not None,
            projection.listings_by_lang is not None,
            len(projection.sitemap_urls), len(projection.search_items), len(projection.rss_heap),
        )
        assert observed == expected
        assert len(plan[section]) == 1
        _cleanup_stream_projection(projection)


def test_rss_only_build_does_not_spool_unused_projections(tmp_path, monkeypatch):
    ctx = _ctx_for(tmp_path)
    with TempWorkspace() as workspace:
        def unexpected_spool(*args, **kwargs):
            pytest.fail("RSS-only planning must not create projection files")
        monkeypatch.setattr(workspace, "named_file", unexpected_spool)
        plan = _collect_tasks(lambda: iter([_art("a")]), _FakeCLI(sections=["rss"]), ctx, {}, workspace)
        assert len(plan["rss"]) == 1
        _cleanup_stream_projection(plan.projection)


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
    assert "articles" in plan
    assert len(plan["articles"]) == 1


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

    manifest = OutputManifest()
    with pytest.raises(ValueError, match="Duplicate generated cache key"):
        _collect_tasks(stream_factory, cli, ctx, {}, manifest)


def test_collect_tasks_rejects_duplicate_output_path(tmp_path):
    ctx = _ctx_for(tmp_path)
    ctx = cast(BuildCtx, dataclasses.replace(
        ctx,
        url_patterns={**ctx.url_patterns, "rss": "/feed.xml", "sitemap": "/feed.xml"},
    ))
    cli = _FakeCLI()

    def stream_factory():
        return iter(())

    manifest = OutputManifest()
    with pytest.raises(ValueError, match="Duplicate generated output path"):
        _collect_tasks(stream_factory, cli, ctx, {}, manifest)


@pytest.mark.parametrize("paths", [
    ("page.html", "page.html/feed.xml"), ("page.html/feed.xml", "page.html"),
])
def test_output_manifest_rejects_ancestor_conflicts(paths):
    manifest = OutputManifest()
    manifest.record("first", paths[0])
    with pytest.raises(ValueError, match="Duplicate generated output path"):
        manifest.record("second", paths[1])


def test_asset_page_conflict_fails_before_writes(site_root):
    from articulous.config import apply_cli_overrides, load_or_create_config
    config = load_or_create_config(site_root / "config.json")
    config["urls"]["article"] = "/assets/{lang}/{slug}/"
    apply_cli_overrides(config, _CLI(), site_root)
    with pytest.raises(ValueError, match="reserved assets"):
        run_build(_CLI(), config, site_root)
    assert not (site_root / "output").exists()
    assert not (site_root / ".build-cache.json").exists()


@pytest.mark.parametrize("rss_path", [
    "/en/articles/first-post/index.html",
    "/en/articles/first-post",
    "/en/articles/first-post/index.html/feed.xml",
])
def test_partial_build_rejects_retained_owner_collisions(site_root, rss_path):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    output = site_root / "output"
    before = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
    cache_path = site_root / ".build-cache.json"
    cache_before = cache_path.read_bytes()
    (site_root / "assets/new.txt").write_text("must not publish")
    config["urls"]["rss"] = rss_path
    with pytest.raises(ValueError, match="Duplicate generated output path"):
        run_build(_CLI(only_sections=["rss"]), config, site_root)
    assert {path: path.read_bytes() for path in output.rglob("*") if path.is_file()} == before
    assert cache_path.read_bytes() == cache_before


def test_partial_build_can_transfer_selected_output_ownership(site_root):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    config["urls"]["rss"] = "/sitemap.xml"
    config["urls"]["sitemap"] = "/new-sitemap.xml"
    run_build(_CLI(only_sections=["rss", "sitemap"]), config, site_root)
    root = site_root / "output"
    assert etree.parse(str(root / "sitemap.xml")).getroot().tag == "rss"
    assert (root / "new-sitemap.xml").exists()
    assert not (root / "rss.xml").exists()
    cache, _ = _load_build_cache(site_root / ".build-cache.json", root)
    assert cache["__outputs__"]["rss"] == "sitemap.xml"
    assert cache["__outputs__"]["sitemap"] == "new-sitemap.xml"


def test_collect_tasks_rejects_output_escape(tmp_path):
    ctx = _ctx_for(tmp_path)
    ctx = cast(BuildCtx, dataclasses.replace(
        ctx,
        url_patterns={**ctx.url_patterns, "rss": "/../rss.xml"},
    ))
    cli = _FakeCLI(sections=["rss"])

    def stream_factory():
        return iter(())

    manifest = OutputManifest()
    with pytest.raises(ValueError, match="escapes output_dir"):
        _collect_tasks(stream_factory, cli, ctx, {}, manifest)


@pytest.mark.parametrize("old_path", ["en/1/index.html", "en/1", "en"])
def test_prune_preserves_reassigned_paths_and_parents(tmp_path, old_path):
    ctx = _ctx_for(tmp_path)
    page = ctx.output_dir / "en/1/index.html"
    page.parent.mkdir(parents=True)
    page.write_text("new index")
    cache = {"old": ["old hash"], "new": ["new hash"]}
    _prune_stale_outputs(ctx, cache, {old_path: "old"}, {"en/1/index.html": "new"})
    assert page.read_text() == "new index"
    assert cache == {"new": ["new hash"]}


def test_prune_stale_outputs_handles_manifest_edges(tmp_path, caplog):
    ctx = _ctx_for(tmp_path)
    root_file = tmp_path / "output" / "root.txt"
    root_file.write_text("old")
    missing = tmp_path / "output" / "missing.txt"
    assert not missing.exists()
    cache = {"root": ["h"], "missing": ["h"], "bad": ["h"]}
    old = {
        "root": "root.txt",
        "missing": "missing.txt",
        "bad": str(tmp_path.parent / "outside.txt"),
    }
    with caplog.at_level(logging.WARNING):
        _prune_stale_outputs(ctx, cache, {path: key for key, path in old.items()}, {})
    assert not root_file.exists()
    assert cache == {}
    assert any("invalid cached output manifest" in r.message for r in caplog.records)


@pytest.mark.parametrize("nonempty", [False, True])
def test_unpublishing_rejects_owned_file_replaced_by_directory(site_root, nonempty):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    page = site_root / "output/en/articles/first-post/index.html"
    page.unlink()
    page.mkdir()
    unowned = page / "manual.txt"
    if nonempty:
        unowned.write_text("keep")
    _set_publication(site_root / "content/en/first-post.xml", "private")
    with pytest.raises(ValueError, match="Owned output file became a directory"):
        run_build(_CLI(), config, site_root)
    assert page.is_dir()
    if nonempty:
        assert unowned.read_text() == "keep"


@pytest.mark.parametrize("old_path", ["assets/style.css", "assets", "."])
def test_prune_never_deletes_reserved_assets(tmp_path, old_path):
    ctx = _ctx_for(tmp_path)
    asset = ctx.output_dir / "assets/style.css"
    asset.parent.mkdir()
    asset.write_text("current asset")
    cache = {"rss": ["old"]}
    _prune_stale_outputs(ctx, cache, {old_path: "rss"}, {})
    assert asset.read_text() == "current asset"
    assert cache == {}


@pytest.mark.parametrize("target_kind", ["file", "directory", "missing", "outside"])
def test_unpublishing_removes_stale_link_without_following_target(site_root, target_kind):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    root = site_root / "output"
    target = root / "manual.txt"
    if target_kind == "directory":
        target.mkdir()
        (target / "notes.txt").write_text("keep")
    elif target_kind != "missing":
        target = site_root / "manual.txt" if target_kind == "outside" else target
        target.write_text("keep")
    before = target.stat().st_ino if target.exists() else None
    page = root / "en/articles/first-post/index.html"
    page.unlink()
    page.symlink_to(target)
    _set_publication(site_root / "content/en/first-post.xml", "private")
    run_build(_CLI(), config, site_root)
    assert not page.is_symlink()
    assert (target.stat().st_ino if target.exists() else None) == before


@pytest.mark.parametrize("outside", [False, True])
def test_pruning_rejects_symlink_ancestors(tmp_path, outside):
    ctx = _ctx_for(tmp_path)
    manual = (tmp_path if outside else ctx.output_dir) / "manual"
    manual.mkdir()
    victim = manual / "index.html"
    victim.write_text("unowned")
    (ctx.output_dir / "stale").symlink_to(manual, target_is_directory=True)
    cache = {"old": ["fingerprint"]}
    with pytest.raises(OSError, match="ancestor is a symlink"):
        _prune_stale_outputs(ctx, cache, {"stale/index.html": "old"}, {})
    assert victim.read_text() == "unowned"
    assert cache == {"old": ["fingerprint"]}


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


def _site_config(site_root):
    from articulous.config import apply_cli_overrides, load_or_create_config
    config = load_or_create_config(site_root / "config.json")
    apply_cli_overrides(config, _CLI(), site_root)
    return config


def test_empty_asset_mirror_repairs_root_after_dry_run(site_root):
    (site_root / "assets" / "style.css").unlink()
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    cache = site_root / ".build-cache.json"
    old_cache = cache.read_bytes()
    destination = site_root / "output" / "assets"
    destination.rmdir()
    destination.write_text("wrong type")
    run_build(_CLI(dry_run=True), config, site_root)
    assert destination.read_text() == "wrong type"
    assert cache.read_bytes() == old_cache
    run_build(_CLI(), config, site_root)
    assert destination.is_dir()
    assert list(destination.iterdir()) == []
    assert cache.read_bytes() == old_cache


@pytest.mark.parametrize("key,pattern", [
    ("article", "/{lang}/" + "a" * 256 + "/{slug}/"),
    ("tag", "/{lang}/" + "é" * 128 + "/{tag}/"),
    ("search", "/" + "s" * 256 + ".json"),
    ("rss", "/" + "nested/" * 600 + "rss.xml"),
])
@pytest.mark.parametrize("dry_run", [False, True])
def test_oversize_output_preserves_published_site(site_root, key, pattern, dry_run):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    output = site_root / "output"
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    cache = site_root / ".build-cache.json"
    old_cache = cache.read_bytes()
    (site_root / "assets" / "style.css").write_text("changed asset")
    config["urls"][key] = pattern
    with pytest.raises(ValueError, match="exceeds filesystem limit"):
        run_build(_CLI(dry_run=dry_run), config, site_root)
    assert {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()} == before
    assert cache.read_bytes() == old_cache


def _set_publication(path, status):
    tree = etree.parse(str(path))
    etree.SubElement(tree.getroot(), "status").text = status
    etree.SubElement(tree.getroot(), "publish-at").text = "9999-01-01T00:00:00Z"
    tree.write(str(path), encoding="utf-8")


@pytest.mark.parametrize("status", ["private", "draft", "scheduled"])
@pytest.mark.parametrize("options", [
    {"only_sections": ["articles"]},
    {"only_sections": ["articles"], "only_slugs": ["first-post"]},
    {"only_langs": ["en"]},
    {"only_slugs": ["first-post"]},
])
def test_targeted_build_unpublishes_selected_articles(site_root, status, options):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    _set_publication(site_root / "content/en/first-post.xml", status)
    run_build(_CLI(**options), config, site_root)
    assert not (site_root / "output/en/articles/first-post/index.html").exists()
    assert (site_root / "output/en/articles/second-post/index.html").exists()


def test_targeted_unpublishing_preserves_unselected_retired_page(site_root):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    _set_publication(site_root / "content/en/first-post.xml", "private")
    _set_publication(site_root / "content/en/second-post.xml", "private")
    run_build(_CLI(only_sections=["articles"], only_slugs=["first-post"]), config, site_root)
    assert not (site_root / "output/en/articles/first-post/index.html").exists()
    assert (site_root / "output/en/articles/second-post/index.html").exists()


@pytest.mark.parametrize("options", [
    {"only_langs": ["en"]},
    {"only_slugs": ["first-post"]},
    {"only_langs": ["en"], "only_slugs": ["first-post"]},
])
def test_filtered_rebuild_preserves_complete_shared_outputs(site_root, options):
    config = _site_config(site_root)
    config["site"]["pagination"]["per_page"] = 1
    run_build(_CLI(), config, site_root)
    root = site_root / "output"
    cache, _ = _load_build_cache(site_root / ".build-cache.json", root)
    shared = {path: (root / path).read_bytes()
              for key, path in cache["__outputs__"].items()
              if not key.startswith("article:")}
    french = next(root.glob("fr/articles/*/index.html"))
    modified = french.stat().st_mtime_ns
    config["build"]["force_full_build"] = True
    run_build(_CLI(**options), config, site_root)
    assert {path: (root / path).read_bytes() for path in shared} == shared
    assert len(json.loads((root / "search.json").read_text())) == 3
    assert french.stat().st_mtime_ns == modified


@pytest.mark.parametrize("options", [
    {"only_langs": ["en"]}, {"only_slugs": ["first-post"]},
])
def test_filtered_unpublishing_refreshes_and_prunes_shared_outputs(site_root, options):
    config = _site_config(site_root)
    config["site"]["pagination"]["per_page"] = 1
    run_build(_CLI(), config, site_root)
    _set_publication(site_root / "content/en/first-post.xml", "private")
    run_build(_CLI(**options), config, site_root)
    root = site_root / "output"
    assert not (root / "en/page/2/index.html").exists()
    assert not (root / "en/tags/intro/index.html").exists()
    assert "Second Post" in (root / "en/page/1/index.html").read_text()
    assert "Second Post" in (root / "en/tags/news/index.html").read_text()
    search = json.loads((root / "search.json").read_text())
    assert len(search) == 2
    assert all("first-post" not in item["url"] for item in search)


@pytest.mark.parametrize("sections", [None, ["articles"]])
def test_url_move_prunes_old_path_and_rebuilds_existing_target(site_root, sections):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    old = site_root / "output/en/articles/first-post/index.html"
    new = site_root / "output/en/posts/first-post/index.html"
    new.parent.mkdir(parents=True)
    new.write_text("stale page")
    config["urls"]["article"] = "/{lang}/posts/{slug}/"
    run_build(_CLI(only_sections=sections), config, site_root)
    assert not old.exists()
    assert new.read_text() != "stale page"
    modified = new.stat().st_mtime_ns
    run_build(_CLI(), config, site_root)
    assert new.stat().st_mtime_ns == modified


def test_run_build_end_to_end(site_root):
    """Use the fixture site to exercise run_build via the package."""
    from articulous.config import apply_cli_overrides, load_or_create_config
    cfg = load_or_create_config(site_root / "config.json")
    cli = _CLI(force_full_build=True)
    apply_cli_overrides(cfg, cli, site_root)
    run_build(cli, cfg, site_root)
    assert (site_root / "output" / "rss.xml").exists()


def test_output_lock_excludes_builds_with_other_cache_names(site_root):
    from articulous.config import apply_cli_overrides, load_or_create_config
    config = load_or_create_config(site_root / "config.json")
    apply_cli_overrides(config, _CLI(), site_root)
    ctx = build_ctx_from_config(config, dry_run=False)
    with lock_file(_lock_path_for(ctx, site_root)):
        config["build"]["cache_file"] = "other.json"
        with pytest.raises(FileExistsError):
            run_build(_CLI(), config, site_root)
    assert not (site_root / "output").exists()


@pytest.mark.parametrize("alias", [False, True])
def test_cache_lock_excludes_builds_with_other_outputs(site_root, alias):
    config = _site_config(site_root)
    cache_path = site_root / ".build-cache.json"
    cache_path.write_text("{}")
    if alias:
        (site_root / "alias.json").symlink_to(cache_path)
        config["build"]["cache_file"] = "alias.json"
    config["paths"]["output_dir"] = str(site_root / "other-output")
    with lock_file(cache_lock_path(cache_path)):
        with pytest.raises(FileExistsError):
            run_build(_CLI(), config, site_root)
    assert cache_path.read_text() == "{}"
    assert not (site_root / "other-output").exists()


def test_shared_cache_preserves_each_output_manifest(site_root):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    other = copy.deepcopy(config)
    other["paths"]["output_dir"] = str(site_root / "other-output")
    other["urls"]["article"] = "/{lang}/posts/{slug}/"
    run_build(_CLI(), other, site_root)
    _set_publication(site_root / "content/en/first-post.xml", "private")
    run_build(_CLI(), config, site_root)
    assert not (site_root / "output/en/articles/first-post/index.html").exists()
    assert (site_root / "other-output/en/posts/first-post/index.html").exists()
    run_build(_CLI(), other, site_root)
    assert not (site_root / "other-output/en/posts/first-post/index.html").exists()
    roots = json.loads((site_root / ".build-cache.json").read_text())["__output_roots__"]
    assert set(roots) == {str(site_root / "output"), str(site_root / "other-output")}


def test_legacy_cache_migration_keeps_pruning_ownership(site_root):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    path = site_root / ".build-cache.json"
    legacy = json.loads(path.read_text())["__output_roots__"][str(site_root / "output")]
    path.write_text(json.dumps(legacy))
    ownership_path(site_root / "output").unlink()
    _set_publication(site_root / "content/en/first-post.xml", "private")
    run_build(_CLI(), config, site_root)
    assert not (site_root / "output/en/articles/first-post/index.html").exists()
    assert "__output_roots__" in json.loads(path.read_text())


@pytest.mark.parametrize("loss", ["removed", "corrupt", "invalid-roots", "changed-name"])
@pytest.mark.parametrize("options", [{}, {"only_sections": ["articles"], "only_slugs": ["first-post"]}])
def test_cache_loss_preserves_unpublishing_ownership(site_root, loss, options):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    path = site_root / ".build-cache.json"
    if loss == "removed":
        path.unlink()
    elif loss == "changed-name":
        config["build"]["cache_file"] = "other-cache.json"
    else:
        path.write_text("{" if loss == "corrupt" else '{"__output_roots__": null}')
    _set_publication(site_root / "content/en/first-post.xml", "private")
    run_build(_CLI(**options), config, site_root)
    assert not (site_root / "output/en/articles/first-post/index.html").exists()
    assert (site_root / "output/en/articles/second-post/index.html").exists()


def test_cache_write_failure_keeps_output_ownership(site_root, monkeypatch):
    config = _site_config(site_root)

    def fail_write(*_args):
        raise OSError("cache unavailable")

    with monkeypatch.context() as patch:
        patch.setattr("articulous.runtime.write_text_atomic", fail_write)
        run_build(_CLI(), config, site_root)
    assert not (site_root / ".build-cache.json").exists()
    assert ownership_path(site_root / "output").is_file()
    _set_publication(site_root / "content/en/first-post.xml", "private")
    run_build(_CLI(), config, site_root)
    assert not (site_root / "output/en/articles/first-post/index.html").exists()


def test_missing_all_ownership_stops_before_publication(site_root):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    output = site_root / "output"
    before = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
    ownership_path(output).unlink()
    (site_root / ".build-cache.json").unlink()
    _set_publication(site_root / "content/en/first-post.xml", "private")
    with pytest.raises(ValueError, match="Output ownership unavailable"):
        run_build(_CLI(), config, site_root)
    assert {path: path.read_bytes() for path in output.rglob("*") if path.is_file()} == before


def _fail_after_article_publication(plan, _ctx):
    for task in plan["articles"]:
        task()
    raise RuntimeError("later section failed")


def _run_interrupted_build(site_root, config, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr("articulous.pipeline._run_plan", _fail_after_article_publication)
        with pytest.raises(RuntimeError, match="later section failed"):
            run_build(_CLI(), config, site_root)


def test_failed_first_build_preserves_ownership_for_unpublishing(site_root, monkeypatch):
    config = _site_config(site_root)
    _run_interrupted_build(site_root, config, monkeypatch)
    output = site_root / "output"
    page = output / "en/articles/first-post/index.html"
    assert page.is_file()
    assert not (site_root / ".build-cache.json").exists()
    _set_publication(site_root / "content/en/first-post.xml", "private")
    journal = ownership_path(output).read_bytes()
    run_build(_CLI(dry_run=True), config, site_root)
    assert ownership_path(output).read_bytes() == journal
    assert page.is_file()
    run_build(_CLI(), config, site_root)
    assert not page.exists()
    assert not load_ownership(output).pending


def test_repeated_failed_url_moves_preserve_every_owned_path(site_root, monkeypatch):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    for folder in ("moved", "again"):
        config["urls"]["article"] = f"/{{lang}}/{folder}/{{slug}}/"
        _run_interrupted_build(site_root, config, monkeypatch)
    output = site_root / "output"
    paths = [f"en/{folder}/first-post/index.html" for folder in ("articles", "moved", "again")]
    assert all(path in load_ownership(output).paths for path in paths)
    _set_publication(site_root / "content/en/first-post.xml", "private")
    (site_root / ".build-cache.json").unlink()
    run_build(_CLI(), config, site_root)
    assert not any((output / path).exists() for path in paths)
    assert (output / "en/again/second-post/index.html").is_file()


def test_recovery_rebuilds_when_source_reverts_to_cached_bytes(site_root, monkeypatch):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    source = site_root / "content/en/first-post.xml"
    page = site_root / "output/en/articles/first-post/index.html"
    original_source, original_page = source.read_bytes(), page.read_bytes()
    source.write_bytes(original_source.replace(b"Inaugural article.", b"Interrupted version."))
    _run_interrupted_build(site_root, config, monkeypatch)
    assert b"Interrupted version." in page.read_bytes()
    source.write_bytes(original_source)
    run_build(_CLI(), config, site_root)
    assert page.read_bytes() == original_page


@pytest.mark.parametrize("options", [
    {"only_sections": ["articles"]}, {"only_langs": ["en"]}, {"only_slugs": ["first-post"]},
])
def test_interrupted_build_requires_full_recovery(site_root, monkeypatch, options):
    config = _site_config(site_root)
    _run_interrupted_build(site_root, config, monkeypatch)
    output = site_root / "output"
    journal = ownership_path(output).read_bytes()
    with pytest.raises(ValueError, match="requires a full recovery build"):
        run_build(_CLI(**options), config, site_root)
    assert ownership_path(output).read_bytes() == journal
    assert load_ownership(output).pending


def test_journal_write_failure_prevents_publication(site_root, monkeypatch):
    config = _site_config(site_root)

    def fail_write(*_args):
        raise OSError("ownership unavailable")

    monkeypatch.setattr("articulous.ownership.write_text_atomic", fail_write)
    with pytest.raises(OSError, match="ownership unavailable"):
        run_build(_CLI(), config, site_root)
    assert not (site_root / "output").exists()
    assert not (site_root / ".build-cache.json").exists()


def test_final_ownership_failure_keeps_recovery_journal(site_root, monkeypatch):
    config = _site_config(site_root)

    def fail_finalize(_output, _paths):
        raise OSError("final ownership unavailable")

    with monkeypatch.context() as patch:
        patch.setattr("articulous.pipeline.save_ownership", fail_finalize)
        with pytest.raises(OSError, match="final ownership unavailable"):
            run_build(_CLI(), config, site_root)
    assert load_ownership(site_root / "output").pending
    _set_publication(site_root / "content/en/first-post.xml", "private")
    run_build(_CLI(), config, site_root)
    assert not (site_root / "output/en/articles/first-post/index.html").exists()


def test_recovery_preserves_unowned_target_never_published(site_root, monkeypatch):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    output = site_root / "output"
    manual = output / "manual.txt"
    manual.write_text("keep unowned content")
    config["urls"]["rss"] = "/manual.txt"
    _run_interrupted_build(site_root, config, monkeypatch)
    assert "manual.txt" not in load_ownership(output).paths
    config["urls"]["rss"] = "/rss.xml"
    run_build(_CLI(), config, site_root)
    assert manual.read_text() == "keep unowned content"


def test_recovery_tracks_existing_target_after_publication(site_root, monkeypatch):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    output = site_root / "output"
    target = output / "en/moved/first-post/index.html"
    target.parent.mkdir(parents=True)
    target.write_text("previous unowned content")
    config["urls"]["article"] = "/{lang}/moved/{slug}/"
    _run_interrupted_build(site_root, config, monkeypatch)
    assert "en/moved/first-post/index.html" in load_ownership(output).paths
    _set_publication(site_root / "content/en/first-post.xml", "private")
    run_build(_CLI(), config, site_root)
    assert not target.exists()


@pytest.mark.parametrize("roots", [None, "invalid", {"output": []}])
def test_invalid_cache_namespaces_start_empty(tmp_path, roots):
    path = tmp_path / "cache.json"
    output = tmp_path / "output"
    if isinstance(roots, dict):
        roots = {str(output): []}
    path.write_text(json.dumps({"__output_roots__": roots}))
    cache, _ = _load_build_cache(path, output)
    assert cache == {}


def test_cache_cannot_alias_output_lock(tmp_path):
    ctx = dataclasses.replace(_ctx_for(tmp_path), cache_file=".output.articulous.lock")
    with pytest.raises(ValueError, match="alias"):
        _lock_path_for(ctx, tmp_path)


def test_lock_suffix_cache_survives_repeated_builds(site_root):
    from articulous.config import apply_cli_overrides, load_or_create_config
    config = load_or_create_config(site_root / "config.json")
    config["build"]["cache_file"] = "state.lock"
    apply_cli_overrides(config, _CLI(), site_root)
    run_build(_CLI(), config, site_root)
    path = site_root / "state.lock"
    modified = path.stat().st_mtime_ns
    run_build(_CLI(), config, site_root)
    assert path.stat().st_mtime_ns == modified
    assert "pid" not in json.loads(path.read_text())


def test_run_build_rejects_source_overlap_before_writes(site_root):
    from articulous.config import load_or_create_config
    config = load_or_create_config(site_root / "config.json")
    config["paths"]["output_dir"] = "content"
    source = site_root / "content/en/first-post.xml"
    previous = source.read_bytes()
    with pytest.raises(ValueError, match="overlap"):
        run_build(_CLI(), config, site_root)
    assert source.read_bytes() == previous
    assert not (site_root / ".content.articulous.lock").exists()


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


@pytest.mark.parametrize("dependency", [False, True])
def test_stylesheet_edits_and_reverts_cannot_poison_cache(site_root, monkeypatch, dependency):
    config = _site_config(site_root)
    main = site_root / "xsl/pages/article.xsl"
    changed = main
    if dependency:
        main.write_bytes(
            b'<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
            b'<xsl:include href="common.xsl"/></xsl:stylesheet>'
        )
        changed = main.with_name("common.xsl")
    changed.write_bytes(MINIMAL_XSLT)
    run_build(_CLI(), config, site_root)
    page = site_root / "output/en/articles/first-post/index.html"
    original = page.read_bytes()
    original_run = _run_plan

    def edit_during_execution(plan, ctx):
        changed.write_bytes(MINIMAL_XSLT.replace(b"<out/>", b"<intermediate/>"))
        try:
            return original_run(plan, ctx)
        finally:
            changed.write_bytes(MINIMAL_XSLT)

    config["build"]["force_full_build"] = True
    with monkeypatch.context() as patch:
        patch.setattr("articulous.pipeline._run_plan", edit_during_execution)
        run_build(_CLI(), config, site_root)
    assert page.read_bytes() == original
    modified = page.stat().st_mtime_ns
    config["build"]["force_full_build"] = False
    run_build(_CLI(), config, site_root)
    assert page.read_bytes() == original
    assert page.stat().st_mtime_ns == modified


def _redirect_page_output(page, target, component):
    if component == "ancestor":
        target.mkdir()
        (target / page.name).write_text("keep")
        page.parent.rename(page.parent.with_name("original"))
        page.parent.symlink_to(target, target_is_directory=True)
        return target / page.name
    target.write_text("keep")
    page.unlink()
    page.symlink_to(target)
    return target


@pytest.mark.parametrize("section", ["rss", "search"])
@pytest.mark.parametrize("kind", ["directory", "fifo"])
@pytest.mark.parametrize("force", [False, True])
def test_build_rejects_nonregular_cached_output(site_root, section, kind, force):
    config = _site_config(site_root)
    run_build(_CLI(), config, site_root)
    filename = {"rss": "rss.xml", "search": "search.json"}[section]
    page = site_root / "output" / filename
    page.unlink()
    if kind == "directory":
        page.mkdir()
        (page / "manual.txt").write_text("keep")
    else:
        os.mkfifo(page)
    before = page.lstat()
    config["build"]["force_full_build"] = force
    with pytest.raises(ValueError, match="Path must be a regular file"):
        run_build(_CLI(only_sections=[section]), config, site_root)
    assert page.lstat() == before
    if kind == "directory":
        assert (page / "manual.txt").read_text() == "keep"


@pytest.mark.parametrize("section", ["articles", "search"])
@pytest.mark.parametrize("component", ["leaf", "ancestor"])
@pytest.mark.parametrize("stage", ["planning", "publication"])
def test_build_rejects_live_output_links(site_root, monkeypatch, section, component, stage):
    config = _site_config(site_root)
    config["urls"]["search"] = "/nested/search.json"
    run_build(_CLI(), config, site_root)
    rel = {"articles": "en/articles/first-post/index.html", "search": "nested/search.json"}
    page = site_root / "output" / rel[section]
    target = site_root / "output/manual"
    victim = target / page.name if component == "ancestor" else target
    original_run = _run_plan

    def redirect_then_run(plan, ctx):
        _redirect_page_output(page, target, component)
        return original_run(plan, ctx)

    if stage == "planning":
        _redirect_page_output(page, target, component)
    else:
        monkeypatch.setattr("articulous.pipeline._run_plan", redirect_then_run)
        config["build"]["force_full_build"] = True
    with pytest.raises(ValueError, match="Generated output path contains a symlink"):
        run_build(_CLI(only_sections=[section]), config, site_root)
    assert victim.read_text() == "keep"
    state = json.loads(ownership_path(site_root / "output").read_text())
    assert all(not path.startswith("manual") for path in state["paths"])


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
    cache, _ = _load_build_cache(site_root / ".build-cache.json", site_root / "output")
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
    assert not (site_root / "output").exists()


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
