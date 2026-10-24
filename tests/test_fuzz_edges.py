"""
Targeted fuzz tests for invalid / out-of-bounds / oversize inputs.

Complements :mod:`tests.test_fuzz_unit` (random-shape fuzz) by hitting
the specific edge cases pulled from the input-boundary audit:

  - empty / oversize string fields
  - integer fields at -1, 0, 1, very large, or wrong type
  - cache-file shapes that don't match the schema
  - ISO date variants (timezone, microseconds, leap day, year extrema)
  - XML payloads with BOM, unicode filenames, internal entities
  - tag explosion / whitespace-only tag
  - run_parallel_tasks worker-count edges
  - _stream_projections with rss_items == 0
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import lxml.etree as etree
import pytest

from articulous.articles import (
    Article,
    iter_articles,
    normalize_slug,
    parse_article_xml,
)
from articulous.engines import LxmlEngine, safe_xml_parser
from articulous.transform_contracts import TransformFailure
from articulous.config import apply_cli_overrides, load_or_create_config
from articulous.models import (
    SiteModelCtx,
    build_index_models,
    build_rss_model,
    build_url_from_pattern,
)
from articulous.pipeline import (
    BuildCtx,
    _make_xslt_task,
    _stream_projections,
    run_build,
)
from articulous.runtime import (
    file_hash,
    load_cache,
    run_parallel_tasks,
    should_rebuild,
)


pytestmark = pytest.mark.usefixtures("projection_workspace_cleanup")


# ------------------------------------------------------------
# helpers
# ------------------------------------------------------------

URL_PATTERNS = {
    "article": "/{lang}/articles/{slug}/",
    "index": "/{lang}/page/{page}/",
    "tag": "/{lang}/tags/{tag}/",
    "rss": "/rss.xml",
    "sitemap": "/sitemap.xml",
    "search": "/search.json",
}


def _model_ctx(**overrides):
    base = {
        "base_url": "https://e.test",
        "languages": ["en"],
        "per_page": 10,
        "rss_items": 20,
        "url_patterns": URL_PATTERNS,
    }
    base.update(overrides)
    return cast(SiteModelCtx, SimpleNamespace(**base))


def _art(slug="s", **kw):
    base: dict[str, Any] = {
        "title": slug, "slug": slug, "lang": "en", "date": "2025-01-01",
        "datetime": datetime(2025, 1, 1), "description": "d", "tags": (),
        "source_path": Path(f"/c/{slug}.xml"),
        "url": f"https://e.test/en/{slug}/",
    }
    base.update(kw)
    return Article(**base)


def _no_filter_cli():
    return cast(
        Any,
        SimpleNamespace(only_langs=None, only_slugs=None, only_sections=None),
    )


XSLT_BYTES = (
    b'<?xml version="1.0"?>'
    b'<xsl:stylesheet version="1.0" '
    b'xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
    b'<xsl:template match="/"><out/></xsl:template>'
    b'</xsl:stylesheet>'
)


# ============================================================
# Strings — empty / oversize
# ============================================================

def test_empty_title_falls_back_to_path_stem(tmp_path):
    p = tmp_path / "the-stem.xml"
    p.write_text(
        '<article><title></title><date>2025-01-01</date>'
        '<description>d</description></article>'
    )
    a = parse_article_xml(
        p, default_lang="en", url_builder=lambda lang, slug: f"/{lang}/{slug}/",
    )
    assert a is not None
    assert a.slug == "the-stem"


def test_empty_description_field(tmp_path):
    p = tmp_path / "x.xml"
    p.write_text(
        '<article><title>T</title><date>2025-01-01</date>'
        '<description></description></article>'
    )
    a = parse_article_xml(p, default_lang="en")
    assert a is not None
    assert a.description == ""


def test_oversize_description(tmp_path):
    p = tmp_path / "x.xml"
    long_desc = "x" * 100_000
    p.write_text(
        f'<article><title>T</title><date>2025-01-01</date>'
        f'<description>{long_desc}</description></article>'
    )
    a = parse_article_xml(p, default_lang="en")
    assert a is not None
    assert len(a.description) == 100_000


def test_oversize_title_parses_but_build_rejects_before_writes(site_root):
    p = site_root / "content" / "en" / "x.xml"
    title = "ab" * 200
    p.write_text(
        f'<article><title>{title}</title><date>2025-01-01</date>'
        f'<description>d</description></article>'
    )
    a = parse_article_xml(p, default_lang="en")
    assert a is not None
    assert len(a.slug) == 400
    config = load_or_create_config(site_root / "config.json")
    cli = _no_filter_cli()
    cli.dry_run = cli.force_full_build = cli.verbose = False
    apply_cli_overrides(config, cli, site_root)
    with pytest.raises(ValueError, match="output component exceeds filesystem limit"):
        run_build(cli, config, site_root)
    assert not (site_root / "output").exists()
    assert not (site_root / ".build-cache.json").exists()


def test_empty_base_url_builds_relative_url():
    out = build_url_from_pattern(
        "", "/{lang}/articles/{slug}/", lang="en", slug="x",
    )
    assert out == "/en/articles/x/"


def test_normalize_slug_handles_oversize_input():
    out = normalize_slug("Hello " * 1000)
    assert out.startswith("hello-")
    assert len(out) > 1000


# ============================================================
# Integers — -1 / 0 / 1 / huge / wrong type
# ============================================================

def test_build_index_models_per_page_one():
    arts = [_art(f"a{i}") for i in range(3)]
    pages = list(build_index_models(arts, "en", _model_ctx(per_page=1)))
    assert len(pages) == 3
    assert all(len(p.articles) == 1 for p in pages)


def test_build_index_models_per_page_huge():
    arts = [_art(f"a{i}") for i in range(3)]
    pages = list(build_index_models(arts, "en", _model_ctx(per_page=10**6)))
    assert len(pages) == 1
    assert len(pages[0].articles) == 3


def test_build_rss_model_rss_items_zero():
    arts = [_art(f"a{i}") for i in range(5)]
    rss = build_rss_model(arts, _model_ctx(rss_items=0))
    assert rss.articles == []


def test_build_rss_model_rss_items_larger_than_input():
    arts = [_art(f"a{i}") for i in range(3)]
    rss = build_rss_model(arts, _model_ctx(rss_items=10_000))
    assert len(rss.articles) == 3


def test_stream_projections_rss_items_zero(tmp_path):
    arts = [_art("a"), _art("b")]
    projection = _stream_projections(
        lambda: iter(arts), _no_filter_cli(), cast(Any, _model_ctx(rss_items=0, sitemap_listings=False,
                                                             extra_pages=(), retained_page_routes=())),
    )
    assert projection.rss_heap == []
    assert projection.total == 2
    assert len(projection.sitemap_urls) == 2


@pytest.mark.parametrize("workers", [0, -1])
def test_run_parallel_tasks_invalid_worker_count(workers):
    with pytest.raises(ValueError):
        run_parallel_tasks([lambda: 1], max_workers=workers)


# ============================================================
# Cache file shapes
# ============================================================

def test_load_cache_dict_with_wrong_shape_values(tmp_path):
    """Wrong-shape values survive load and are treated as cache-miss."""
    p = tmp_path / "c.json"
    p.write_text('{"k": "not-a-list"}')
    cache = load_cache(p)
    assert cache == {"k": "not-a-list"}
    assert should_rebuild("k", cache, ("a", "b"), force=False)


def test_load_cache_dict_with_scalar_value(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"k": 42}')
    cache = load_cache(p)
    assert cache == {"k": 42}
    assert should_rebuild("k", cache, ("a", "b"), force=False)


# ============================================================
# Date variants
# ============================================================

@pytest.mark.parametrize("date_str", [
    "2025-01-01T12:00:00+05:00",   # timezone offset
    "2025-01-01T12:00:00.123456",  # microseconds
    "2024-02-29",                  # leap day
    "9999-12-31",                  # max year
    "0001-01-01",                  # min year
])
def test_parse_article_xml_accepts_iso_variants(tmp_path, date_str):
    p = tmp_path / "x.xml"
    p.write_text(
        f'<article><title>T</title><date>{date_str}</date>'
        f'<description>d</description></article>'
    )
    a = parse_article_xml(p, default_lang="en")
    assert a is not None
    assert a.date == date_str


@pytest.mark.parametrize("bad_date", [
    "",
    "not-a-date",
    "2025-13-01",
    "2025-02-30",
])
def test_parse_article_xml_rejects_bad_dates(tmp_path, bad_date):
    p = tmp_path / "x.xml"
    p.write_text(
        f'<article><title>T</title><date>{bad_date}</date>'
        f'<description>d</description></article>'
    )
    assert parse_article_xml(p, default_lang="en") is None


# ============================================================
# XML edges
# ============================================================

def test_parse_article_xml_with_bom(tmp_path):
    p = tmp_path / "bom.xml"
    p.write_bytes(
        b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>'
        b'<article><title>T</title><date>2025-01-01</date>'
        b'<description>d</description></article>'
    )
    assert parse_article_xml(p, default_lang="en") is not None


def test_safe_xml_parser_blocks_internal_entity():
    """resolve_entities=False keeps the parser from expanding even an
    inline DTD-declared entity."""
    payload = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE x [<!ENTITY lol "haha">]>'
        b'<x>&lol;</x>'
    )
    root = etree.fromstring(payload, parser=safe_xml_parser())
    assert (root.text or "") == ""


def test_parse_article_xml_unicode_filename(tmp_path):
    p = tmp_path / "héllo-世界.xml"
    p.write_text(
        '<article><title>T</title><date>2025-01-01</date>'
        '<description>d</description></article>',
        encoding="utf-8",
    )
    a = parse_article_xml(p, default_lang="en")
    assert a is not None


def test_iter_articles_handles_unicode_filename(tmp_path):
    """Streaming load tolerates non-ASCII filenames in the content tree."""
    p = tmp_path / "açai-piña.xml"
    p.write_text(
        '<article><title>Açai &amp; Piña</title><date>2025-01-01</date>'
        '<description>d</description></article>',
        encoding="utf-8",
    )
    out = list(iter_articles(tmp_path, default_lang="en"))
    assert len(out) == 1


# ============================================================
# Tag edges
# ============================================================

def test_many_tags_per_article(tmp_path):
    tags_xml = "".join(f"<tag>t{i}</tag>" for i in range(500))
    p = tmp_path / "x.xml"
    p.write_text(
        f'<article><title>T</title><date>2025-01-01</date>'
        f'<description>d</description>{tags_xml}</article>'
    )
    a = parse_article_xml(p, default_lang="en")
    assert a is not None
    assert len(a.tags) == 500


def test_whitespace_only_tag_filtered(tmp_path):
    p = tmp_path / "x.xml"
    p.write_text(
        '<article><title>T</title><date>2025-01-01</date>'
        '<description>d</description>'
        '<tag>   </tag><tag>real</tag></article>'
    )
    a = parse_article_xml(p, default_lang="en")
    assert a is not None
    assert a.tags == ("real",)


# ============================================================
# _make_xslt_task with empty bytes
# ============================================================

def test_make_xslt_task_empty_bytes_raises_at_run(tmp_path):
    """Empty bytes pass the in-memory hash but fail at lxml parse time —
    failure surfaces from the task, not from task construction, and
    leaves the cache untouched."""
    xsl = tmp_path / "x.xsl"
    xsl.write_bytes(XSLT_BYTES)
    ctx = BuildCtx(
        content_dir=tmp_path, xsl_dir=tmp_path,
        output_dir=tmp_path, assets_dir=tmp_path,
    )
    cache = {}
    task = _make_xslt_task(
        xml_input=b"",
        xsl_path=xsl,
        xsl_hash=file_hash(xsl),
        output_path=tmp_path / "o.html",
        cache=cache,
        cache_key="k",
        engine=LxmlEngine(),
        ctx=ctx,
    )
    assert task is not None
    with pytest.raises(TransformFailure):
        task()
    assert "k" not in cache
