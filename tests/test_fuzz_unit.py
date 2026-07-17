"""
Unit-level fuzz tests.

Deterministic seeds keep these reproducible. They poke the parts that
take user-controlled input:

  - normalize_slug (arbitrary text)
  - parse_article_xml (random XML payloads)
  - _xml_doc + leaf escapers (untrusted strings into XML)
  - _make_xslt_task (random in-memory bytes)
"""
from __future__ import annotations

import random
import string
import hashlib
from datetime import datetime
from pathlib import Path

import lxml.etree as etree

from articulous.articles import (
    Article,
    normalize_slug,
    parse_article_xml,
)
from articulous.pipeline import (
    BuildCtx,
    _article_xml,
    _make_xslt_task,
    _rss_item_xml,
    _sitemap_url_xml,
    _xml_doc,
)
from articulous.engines import LxmlEngine
from articulous.runtime import file_hash


# --- normalize_slug fuzz ---

PRINTABLE = string.ascii_letters + string.digits + " -_.!@#$%^&*()<>?/" + string.punctuation


def _rand_text(rnd: random.Random, max_len=40) -> str:
    n = rnd.randint(0, max_len)
    return "".join(rnd.choice(PRINTABLE) for _ in range(n))


def test_normalize_slug_only_lower_alnum_dash():
    rnd = random.Random(0xDEADBEEF)
    for _ in range(500):
        slug = normalize_slug(_rand_text(rnd))
        if slug:
            assert all(c.islower() or c.isdigit() or c == "-" for c in slug)
            assert not slug.startswith("-")
            assert not slug.endswith("-")
            assert "--" not in slug


# --- XML helpers fuzz ---

def test_xml_helpers_produce_well_formed_documents():
    """Random titles / urls / tags must never break XML well-formedness."""
    rnd = random.Random(0xC0FFEE)
    for _ in range(200):
        title = _rand_text(rnd) or "x"
        url = _rand_text(rnd) or "u"
        a = Article(
            title=title, slug="s", lang="en", date="2025-01-01",
            datetime=datetime(2025, 1, 1), description="d", tags=(),
            source_path=Path("/x.xml"), url=url,
        )
        doc = _xml_doc("index", [_article_xml(a)])
        etree.fromstring(doc.encode())   # raises if malformed


def test_rss_item_xml_well_formed():
    rnd = random.Random(0xFEED)
    items = []
    for _ in range(50):
        a = Article(
            title=_rand_text(rnd) or "t",
            slug="s", lang="en", date="2025-01-01",
            datetime=datetime(2025, 1, 1), description="d", tags=(),
            source_path=Path("/x.xml"),
            url=_rand_text(rnd) or "u",
        )
        items.append(_rss_item_xml(a))
    doc = _xml_doc("rss", items)
    etree.fromstring(doc.encode())


def test_sitemap_url_xml_well_formed():
    rnd = random.Random(0xBABE)
    urls = [_rand_text(rnd) or "u" for _ in range(100)]
    doc = _xml_doc("sitemap", [_sitemap_url_xml(u) for u in urls])
    etree.fromstring(doc.encode())


# --- parse_article_xml fuzz ---

def test_parse_article_xml_never_crashes_on_garbled_input(tmp_path):
    rnd = random.Random(2026)
    for i in range(40):
        p = tmp_path / f"a{i}.xml"
        # Mix valid and invalid XML
        if rnd.random() < 0.3:  # NOSONAR - deterministic test data, not security-sensitive
            p.write_text(_rand_text(rnd, max_len=80))
        else:
            p.write_text(
                f"<article><title>{_rand_text(rnd)}</title>"
                f"<date>{rnd.choice(['2025-01-01', 'nope', ''])}</date>"  # NOSONAR - deterministic test data
                f"<description>{_rand_text(rnd)}</description>"
                f"<lang>{rnd.choice(['en', 'fr', 'zz', '../bad'])}</lang>"  # NOSONAR - deterministic test data
                f"<tag>{_rand_text(rnd)}</tag>"
                f"</article>"
            )
        # Should always return either Article or None, never raise.
        result = parse_article_xml(
            p, default_lang="en",
            url_builder=lambda lang, slug: f"/{lang}/{slug}/",
            allowed_langs=frozenset({"en", "fr"}),
        )
        assert result is None or isinstance(result, Article)


# --- _make_xslt_task fuzz: random XML bytes hash consistently ---

MINIMAL_XSLT = (
    b'<?xml version="1.0"?>'
    b'<xsl:stylesheet version="1.0" '
    b'xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
    b'<xsl:template match="/"><out/></xsl:template>'
    b'</xsl:stylesheet>'
)


def test_make_xslt_task_random_xml_hashes_consistently(tmp_path):
    xsl = tmp_path / "x.xsl"
    xsl.write_bytes(MINIMAL_XSLT)
    xsl_hash = file_hash(xsl)
    ctx = BuildCtx(
        content_dir=tmp_path, xsl_dir=tmp_path,
        output_dir=tmp_path, assets_dir=tmp_path,
    )
    rnd = random.Random(0xABCD)
    for i in range(20):
        payload = f"<root>{rnd.randint(0, 1_000_000)}</root>".encode()  # NOSONAR - deterministic test data
        cache = {}
        task = _make_xslt_task(
            xml_input=payload, xsl_path=xsl, xsl_hash=xsl_hash,
            output_path=tmp_path / f"o{i}.html",
            cache=cache, cache_key=f"k{i}",
            engine=LxmlEngine(), ctx=ctx,
        )
        assert task is not None
        task()
        assert cache[f"k{i}"][0] == hashlib.sha256(payload).hexdigest()
