"""Unit tests for articulous.articles."""
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

import lxml.etree as etree
import pytest

from articulous.articles import (
    Article,
    ArticleStats,
    PublicationState,
    _discover_article_files,
    _read_article_fields,
    _validated_publication,
    _validated_lang,
    iter_articles,
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
        "publication": "published",
        "publish_at": "",
    }


def test_read_article_fields_missing_optionals():
    root = etree.fromstring(b"<article><title>T</title></article>")
    fields = _read_article_fields(root)
    assert fields["title"] == "T"
    assert fields["date"] == ""
    assert fields["description"] == ""
    assert fields["lang"] == ""
    assert fields["tags"] == []
    assert fields["publication"] == "published"
    assert fields["publish_at"] == ""


def test_read_article_fields_handles_none_text():
    # <title/> element with no text content
    root = etree.fromstring(b"<article><title/></article>")
    fields = _read_article_fields(root)
    assert fields["title"] == ""


def test_read_article_fields_reads_publish_at():
    root = etree.fromstring(
        b"<article><publish-at>2025-01-01T00:00:00</publish-at></article>"
    )
    assert _read_article_fields(root)["publish_at"] == "2025-01-01T00:00:00"


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


# --- _validated_publication ---

def test_validated_publication_accepts_known_status():
    state = _validated_publication(" UNLISTED ", "", Path("/x"))
    assert state is not None
    assert state.name == "unlisted"


def test_validated_publication_normalizes_publish_at():
    state = _validated_publication(
        "scheduled", "2025-01-01T12:00:00+05:00", Path("/x")
    )
    assert state is not None
    assert state.publish_at == datetime(2025, 1, 1, 7, tzinfo=timezone.utc)


def test_validated_publication_skips_unknown(caplog):
    with caplog.at_level("WARNING"):
        assert _validated_publication("weird", "", Path("/x")) is None
    assert any("unknown status" in r.message for r in caplog.records)


def test_publication_state_scheduled_policy():
    future = PublicationState("scheduled", datetime.now() + timedelta(days=1))
    past = PublicationState("scheduled", datetime.now() - timedelta(days=1))
    unscheduled = PublicationState("scheduled")
    assert future.policy.page is False
    assert past.policy.page is True
    assert unscheduled.policy.page is False


def test_validated_publication_invalid_publish_at(caplog):
    with caplog.at_level("WARNING"):
        state = _validated_publication("scheduled", "bad-date", Path("/x"))
    assert state is not None
    assert state.policy.page is False
    assert any("invalid publish-at" in r.message for r in caplog.records)


@pytest.mark.parametrize("date", [
    "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00",
])
def test_article_utc_overflow_is_skipped(tmp_path, date):
    source = tmp_path / "article.xml"
    source.write_text(f"<article><title>T</title><date>{date}</date></article>")
    assert parse_article_xml(source) is None


@pytest.mark.parametrize("date", [
    "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00",
])
def test_scheduled_utc_overflow_stays_unpublished(date):
    state = _validated_publication("scheduled", date, Path("article.xml"))
    assert state is not None
    assert not state.policy.page


def test_validated_publication_warns_for_scheduled_without_publish_at(caplog):
    with caplog.at_level("WARNING"):
        state = _validated_publication("scheduled", "", Path("/x"))
    assert state is not None
    assert state.policy.page is False
    assert any("scheduled without publish-at" in r.message for r in caplog.records)


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
    assert art.policy.search is True


@pytest.mark.parametrize("kind", ["symlink", "fifo", "directory"])
def test_article_parser_skips_unsafe_source_entries(tmp_path, kind):
    source = tmp_path / "article.xml"
    outside = tmp_path / "outside.xml"
    outside.write_text(ARTICLE_XML)
    makers = {
        "symlink": lambda: source.symlink_to(outside),
        "fifo": lambda: os.mkfifo(source),
        "directory": source.mkdir,
    }
    makers[kind]()
    assert parse_article_xml(source) is None
    assert outside.read_text() == ARTICLE_XML


def test_parse_article_xml_normalizes_dates_for_sorting(tmp_path):
    naive_path = tmp_path / "naive.xml"
    aware_path = tmp_path / "aware.xml"
    naive_path.write_text(ARTICLE_XML)
    aware_path.write_text(
        ARTICLE_XML.replace("2025-01-15", "2025-01-15T12:00:00+05:00")
    )
    articles = [
        parse_article_xml(naive_path),
        parse_article_xml(aware_path),
    ]
    parsed = [article for article in articles if article is not None]
    assert all(article.datetime.tzinfo is timezone.utc for article in parsed)
    assert len(sorted(parsed, key=lambda article: article.datetime)) == 2


def test_parse_article_xml_publication_status(tmp_path):
    p = tmp_path / "a.xml"
    p.write_text(ARTICLE_XML.replace("</article>", "<status>draft</status></article>"))
    art = parse_article_xml(p, default_lang="en", url_builder=_url_builder)
    assert art is not None
    assert art.publication_state.name == "draft"
    assert art.policy.page is False


def test_parse_article_xml_unknown_status_skipped(tmp_path, caplog):
    p = tmp_path / "a.xml"
    p.write_text(ARTICLE_XML.replace("</article>", "<status>privte</status></article>"))
    with caplog.at_level("WARNING"):
        assert parse_article_xml(p, default_lang="en") is None
    assert any("unknown status" in r.message for r in caplog.records)


def test_parse_article_xml_without_url_builder(tmp_path):
    p = tmp_path / "a.xml"
    p.write_text(ARTICLE_XML)
    art = parse_article_xml(p, default_lang="en")
    assert art is not None
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


def test_parse_article_xml_wrong_root_skipped(tmp_path, caplog):
    p = tmp_path / "not-article.xml"
    p.write_text(
        "<page><title>T</title><date>2025-01-01</date>"
        "<description>d</description></page>"
    )
    with caplog.at_level("WARNING"):
        art = parse_article_xml(p, default_lang="en")
    assert art is None
    assert any("expected 'article'" in r.message for r in caplog.records)


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
    assert art is not None
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
    assert art is not None
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


# --- iter_articles (streaming) ---

def test_iter_articles_yields_lazily(tmp_path):
    """Generator surface: yields Article one at a time, skips Nones."""
    (tmp_path / "good1.xml").write_text(ARTICLE_XML)
    (tmp_path / "bad.xml").write_text("<not-well-formed")
    (tmp_path / "good2.xml").write_text(
        '<article><title>Second</title><date>2025-02-01</date>'
        '<description>d</description></article>'
    )
    stats = ArticleStats()
    out = list(iter_articles(
        tmp_path, default_lang="en", url_builder=_url_builder, stats=stats,
    ))
    slugs = [a.slug for a in out]
    assert "hello-world" in slugs
    assert "second" in slugs
    # Bad article is dropped, not yielded.
    assert len(out) == 2
    assert stats.scanned == 3
    assert stats.parsed == 2
    assert stats.skipped == 1


def test_iter_articles_empty_dir(tmp_path):
    assert list(iter_articles(tmp_path, default_lang="en")) == []


def test_iter_articles_invalid_without_stats(tmp_path):
    (tmp_path / "bad.xml").write_text("<not-well-formed")
    assert list(iter_articles(tmp_path, default_lang="en")) == []


def test_iter_articles_allowed_langs_filter(tmp_path):
    (tmp_path / "a.xml").write_text(
        "<article><title>T</title><date>2025-01-01</date>"
        "<description>d</description><lang>zz</lang></article>"
    )
    arts = list(iter_articles(
        tmp_path, default_lang="en",
        url_builder=_url_builder,
        allowed_langs=["en"],
    ))
    # Lang fell back to "en"; URL built with that fallback.
    assert arts[0].lang == "en"
    assert arts[0].url.startswith("/en/")
