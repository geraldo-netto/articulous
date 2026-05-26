"""Unit tests for articulous.articles."""
from pathlib import Path

import lxml.etree as etree
import pytest

from articulous.articles import (
    Article,
    _discover_article_files,
    _read_article_fields,
    _validated_lang,
    load_articles,
    normalize_slug,
    parse_article_xml,
)


# --- normalize_slug ---

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Hello World", "hello-world"),
        ("Multi---Dash", "multi-dash"),
        ("  surrounded  ", "surrounded"),
        ("UPPER lower 123", "upper-lower-123"),
        ("symbols!@#$%^&*()", "symbols"),
        ("---", ""),
        ("", ""),
    ],
)
def test_normalize_slug(raw, expected):
    assert normalize_slug(raw) == expected


# --- _read_article_fields ---

def test_read_article_fields_single_pass():
    root = etree.fromstring(
        b"<article><title>T</title><date>2025-01-01</date>"
        b"<description>D</description><lang>fr</lang>"
        b"<tag>a</tag><tag>b</tag><tag></tag></article>"
    )
    fields = _read_article_fields(root)
    assert fields == {
        "title": "T",
        "date": "2025-01-01",
        "description": "D",
        "lang": "fr",
        "tags": ["a", "b"],
    }


def test_read_article_fields_missing_optionals():
    root = etree.fromstring(b"<article><title>T</title></article>")
    fields = _read_article_fields(root)
    assert fields["title"] == "T"
    assert fields["date"] == ""
    assert fields["description"] == ""
    assert fields["lang"] == ""
    assert fields["tags"] == []


def test_read_article_fields_handles_none_text():
    # <title/> element with no text content
    root = etree.fromstring(b"<article><title/></article>")
    fields = _read_article_fields(root)
    assert fields["title"] == ""


# --- _validated_lang ---

def test_validated_lang_default_when_missing():
    assert _validated_lang("", "en", None, Path("/x")) == "en"


def test_validated_lang_uses_parsed_value_when_no_whitelist():
    assert _validated_lang("fr", "en", None, Path("/x")) == "fr"


def test_validated_lang_falls_back_when_outside_whitelist(caplog):
    with caplog.at_level("WARNING"):
        out = _validated_lang(
            "../bad", "en", frozenset({"en", "fr"}), Path("/x")
        )
    assert out == "en"
    assert any("outside the configured set" in r.message for r in caplog.records)


def test_validated_lang_passes_when_inside_whitelist():
    assert _validated_lang("fr", "en", frozenset({"en", "fr"}), Path("/x")) == "fr"


# --- parse_article_xml ---

ARTICLE_XML = (
    "<article>"
    "<title>Hello World</title>"
    "<date>2025-01-15</date>"
    "<description>Desc</description>"
    "<lang>en</lang>"
    "<tag>news</tag>"
    "</article>"
)


def _url_builder(lang, slug):
    return f"/{lang}/{slug}/"


def test_parse_article_xml_happy_path(tmp_path):
    p = tmp_path / "a.xml"
    p.write_text(ARTICLE_XML)
    art = parse_article_xml(p, default_lang="en", url_builder=_url_builder)
    assert isinstance(art, Article)
    assert art.title == "Hello World"
    assert art.slug == "hello-world"
    assert art.lang == "en"
    assert art.tags == ("news",)
    assert art.url == "/en/hello-world/"


def test_parse_article_xml_without_url_builder(tmp_path):
    p = tmp_path / "a.xml"
    p.write_text(ARTICLE_XML)
    art = parse_article_xml(p, default_lang="en")
    assert art.url == ""


def test_parse_article_xml_malformed_returns_none(tmp_path, caplog):
    p = tmp_path / "broken.xml"
    p.write_text("<article>not-closed")
    with caplog.at_level("ERROR"):
        art = parse_article_xml(p, default_lang="en")
    assert art is None
    assert any("Failed to parse XML" in r.message for r in caplog.records)


def test_parse_article_xml_missing_file_returns_none(tmp_path, caplog):
    p = tmp_path / "ghost.xml"
    with caplog.at_level("ERROR"):
        art = parse_article_xml(p, default_lang="en")
    assert art is None


def test_parse_article_xml_invalid_date_skipped(tmp_path, caplog):
    p = tmp_path / "a.xml"
    p.write_text(
        "<article><title>T</title><date>not-a-date</date>"
        "<description>d</description></article>"
    )
    with caplog.at_level("WARNING"):
        art = parse_article_xml(p, default_lang="en")
    assert art is None
    assert any("missing/invalid date" in r.message for r in caplog.records)


def test_parse_article_xml_falls_back_to_path_stem_when_no_title(tmp_path):
    p = tmp_path / "my-stem.xml"
    p.write_text(
        "<article><title></title><date>2025-01-01</date>"
        "<description>d</description></article>"
    )
    art = parse_article_xml(p, default_lang="en")
    assert art.slug == "my-stem"


def test_parse_article_xml_empty_slug_skipped(tmp_path, caplog):
    p = tmp_path / "  .xml"
    p.write_text(
        "<article><title>!!!</title><date>2025-01-01</date>"
        "<description>d</description></article>"
    )
    with caplog.at_level("WARNING"):
        art = parse_article_xml(p, default_lang="en")
    assert art is None


def test_parse_article_xml_lang_whitelist(tmp_path, caplog):
    p = tmp_path / "a.xml"
    p.write_text(
        "<article><title>T</title><date>2025-01-01</date>"
        "<description>d</description><lang>zz</lang></article>"
    )
    with caplog.at_level("WARNING"):
        art = parse_article_xml(
            p, default_lang="en",
            url_builder=_url_builder, allowed_langs=frozenset({"en"}),
        )
    assert art.lang == "en"


# --- _discover_article_files ---

def test_discover_article_files_recurses(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.xml").write_text("<a/>")
    (tmp_path / "sub" / "b.xml").write_text("<a/>")
    (tmp_path / "ignore.txt").write_text("nope")
    files = _discover_article_files(tmp_path)
    names = [f.name for f in files]
    assert names == ["a.xml", "b.xml"]


# --- load_articles ---

def test_load_articles_sorts_newest_first(tmp_path):
    (tmp_path / "old.xml").write_text(
        "<article><title>Old</title><date>2024-01-01</date>"
        "<description>d</description></article>"
    )
    (tmp_path / "new.xml").write_text(
        "<article><title>New</title><date>2026-01-01</date>"
        "<description>d</description></article>"
    )
    arts = load_articles(
        tmp_path, default_lang="en", url_builder=_url_builder,
    )
    assert [a.slug for a in arts] == ["new", "old"]


def test_load_articles_empty_dir(tmp_path):
    assert load_articles(tmp_path, default_lang="en") == []


def test_load_articles_skips_unparseable(tmp_path, caplog):
    (tmp_path / "good.xml").write_text(ARTICLE_XML)
    (tmp_path / "bad.xml").write_text("<article")
    with caplog.at_level("ERROR"):
        arts = load_articles(
            tmp_path, default_lang="en", url_builder=_url_builder,
        )
    assert len(arts) == 1
    assert arts[0].slug == "hello-world"


def test_load_articles_respects_max_workers(tmp_path):
    for i in range(3):
        (tmp_path / f"a{i}.xml").write_text(
            f"<article><title>T{i}</title><date>2025-01-{i+1:02d}</date>"
            f"<description>d</description></article>"
        )
    arts = load_articles(
        tmp_path, default_lang="en",
        url_builder=_url_builder, max_workers=1,
    )
    assert len(arts) == 3


def test_load_articles_allowed_langs_filter(tmp_path):
    (tmp_path / "a.xml").write_text(
        "<article><title>T</title><date>2025-01-01</date>"
        "<description>d</description><lang>zz</lang></article>"
    )
    arts = load_articles(
        tmp_path, default_lang="en",
        url_builder=_url_builder,
        allowed_langs=["en"],
    )
    # Lang fell back to "en"; URL built with that fallback.
    assert arts[0].lang == "en"
    assert arts[0].url.startswith("/en/")
