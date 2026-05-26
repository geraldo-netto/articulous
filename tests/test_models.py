"""Unit tests for articulous.models."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from articulous.articles import Article
from articulous.models import (
    IndexPage,
    RssFeed,
    SearchIndex,
    Sitemap,
    TagPage,
    build_index_models,
    build_rel_path_from_pattern,
    build_rss_model,
    build_search_model,
    build_sitemap_model,
    build_tags_models,
    build_url_from_pattern,
)


def _ctx(**overrides):
    base = dict(
        base_url="https://example.test",
        languages=["en", "fr"],
        per_page=2,
        rss_items=5,
        url_patterns={
            "article": "/{lang}/articles/{slug}/",
            "index": "/{lang}/page/{page}/",
            "tag": "/{lang}/tags/{tag}/",
            "rss": "/rss.xml",
            "sitemap": "/sitemap.xml",
            "search": "/search.json",
        },
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _art(slug, lang="en", tags=(), url=None):
    return Article(
        title=slug.replace("-", " ").title(),
        slug=slug,
        lang=lang,
        date="2025-01-01",
        datetime=datetime(2025, 1, 1),
        description="d",
        tags=tags,
        source_path=Path(f"/content/{lang}/{slug}.xml"),
        url=url if url is not None else f"https://example.test/{lang}/articles/{slug}/",
    )


# --- URL helpers ---

def test_build_rel_path_from_pattern():
    p = build_rel_path_from_pattern("/{lang}/articles/{slug}/", lang="en", slug="x")
    assert p == Path("en/articles/x/index.html")


def test_build_url_from_pattern_strips_slashes():
    u = build_url_from_pattern(
        "https://e.test/", "/{lang}/page/{page}/", lang="en", page=2,
    )
    assert u == "https://e.test/en/page/2/"


# --- Page dataclasses are frozen ---

def test_index_page_frozen():
    p = IndexPage(
        lang="en", page=1, total_pages=1,
        articles=[], output_path=Path("x"), url="u",
    )
    with pytest.raises(Exception):
        p.page = 2


def test_other_page_frozen():
    for cls, kwargs in [
        (TagPage, dict(lang="en", tag="x", tag_slug="x", articles=[],
                       output_path=Path("p"), url="u")),
        (RssFeed, dict(articles=[], output_path=Path("p"), url="u")),
        (Sitemap, dict(urls=[], output_path=Path("p"), url="u")),
        (SearchIndex, dict(items=[], output_path=Path("p"), url="u")),
    ]:
        obj = cls(**kwargs)
        with pytest.raises(Exception):
            obj.url = "y"


# --- build_index_models ---

def test_build_index_models_paginates_per_lang():
    arts = [_art(f"a{i}", lang="en") for i in range(5)] + \
           [_art(f"b{i}", lang="fr") for i in range(3)]
    pages = build_index_models(arts, _ctx())
    # en: 5 articles, per_page=2 → 3 pages; fr: 3 → 2 pages
    en_pages = [p for p in pages if p.lang == "en"]
    fr_pages = [p for p in pages if p.lang == "fr"]
    assert len(en_pages) == 3
    assert len(fr_pages) == 2
    assert all(p.total_pages == 3 for p in en_pages)
    assert all(p.total_pages == 2 for p in fr_pages)


def test_build_index_models_skips_empty_lang():
    arts = [_art("a", lang="en")]
    pages = build_index_models(arts, _ctx())
    langs = {p.lang for p in pages}
    assert langs == {"en"}


# --- build_tags_models ---

def test_build_tags_models_group_by_lang_and_tag():
    arts = [
        _art("a", lang="en", tags=("news", "intro")),
        _art("b", lang="en", tags=("news",)),
        _art("c", lang="fr", tags=("news",)),
    ]
    models = build_tags_models(arts, _ctx())
    en_tags = sorted(m.tag for m in models if m.lang == "en")
    fr_tags = [m.tag for m in models if m.lang == "fr"]
    assert en_tags == ["intro", "news"]
    assert fr_tags == ["news"]


def test_build_tags_models_skips_empty_slug(caplog):
    arts = [_art("a", tags=("!!!",))]
    with caplog.at_level("WARNING"):
        models = build_tags_models(arts, _ctx(languages=["en"]))
    assert models == []
    assert any("slugifies to empty" in r.message for r in caplog.records)


def test_build_tags_models_url_encoded(caplog):
    arts = [_art("a", tags=("Hello World",))]
    models = build_tags_models(arts, _ctx(languages=["en"]))
    assert models[0].tag_slug == "hello-world"
    assert "hello-world" in models[0].url


# --- build_rss_model ---

def test_build_rss_model_respects_limit():
    arts = [_art(f"a{i}") for i in range(20)]
    rss = build_rss_model(arts, _ctx(rss_items=3))
    assert len(rss.articles) == 3
    assert rss.output_path == Path("rss.xml")


# --- build_sitemap_model ---

def test_build_sitemap_model_collects_urls():
    arts = [_art("a"), _art("b")]
    sm = build_sitemap_model(arts, _ctx())
    assert sm.urls == [arts[0].url, arts[1].url]
    assert sm.output_path == Path("sitemap.xml")


# --- build_search_model ---

def test_build_search_model_shape():
    arts = [_art("a", tags=("news",))]
    idx = build_search_model(arts, _ctx())
    assert idx.items[0]["title"] == arts[0].title
    assert idx.items[0]["url"] == arts[0].url
    assert idx.items[0]["tags"] == ["news"]
    assert idx.output_path == Path("search.json")
