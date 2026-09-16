"""TAG-01: opt-in, crawlable tag pagination and incremental lifecycle."""
import copy
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import random
from types import SimpleNamespace
from typing import cast

import lxml.etree as etree
import pytest

from articulous.articles import Article
from articulous.config import DEFAULT_CONFIG, load_or_create_config, validate_config
from articulous.models import SiteModelCtx, build_tags_models
from articulous.pipeline import run_build


def _article(index, **changes):
    article = Article(
        title=f"Post {index}", slug=f"post-{index}", lang="en", date="2025-01-01",
        datetime=datetime(2025, 1, 1), description="", tags=("News", "News"),
        source_path=Path(f"post-{index}.xml"), url=f"https://example.test/en/articles/post-{index}/",
    )
    return replace(article, **changes)


def _context(**changes):
    values = dict(base_url="https://example.test/blog", languages=["en"], per_page=10,
                  rss_items=10, url_patterns={"tag": "/{lang}/tags/{tag}/"})
    values.update(changes)
    return cast(SiteModelCtx, SimpleNamespace(**values))


@pytest.mark.parametrize("count", [0, 1, 10, 11, 20, 21])
def test_tag01_page_boundaries_and_complete_membership(count):
    articles = [_article(i) for i in range(count)]
    pages = build_tags_models(iter(articles), "en", _context(), paginate=True)
    assert len(pages) == (count + 9) // 10
    assert [a for page in pages for a in page.articles] == articles
    for index, page in enumerate(pages, 1):
        assert page.page == index
        assert page.total_pages == len(pages)
        assert len(page.articles) <= 10
        assert page.previous_url == (pages[index - 2].url if index > 1 else "")
        assert page.next_url == (pages[index].url if index < len(pages) else "")


def test_tag01_default_remains_unpaginated():
    articles = [_article(i) for i in range(21)]
    pages = build_tags_models(articles, "en", _context())
    assert len(pages) == 1
    assert pages[0].articles == articles
    assert pages[0].url == "https://example.test/blog/en/tags/news/"


@pytest.mark.parametrize("pattern,lang,prefix", [
    ("/{lang}/topics/{tag}", "pt", "pt/topics/news"),
    ("/tags/{tag}/", "", "tags/news"),
    ("/café/{lang}/{tag}/", "en", "café/en/news"),
])
def test_tag01_custom_and_global_routes(pattern, lang, prefix):
    ctx = _context(url_patterns={"tag": pattern}, per_page=1)
    pages = build_tags_models([_article(0), _article(1)], lang, ctx, paginate=True)
    assert pages[0].output_path == Path(prefix) / "index.html"
    assert pages[1].output_path == Path(prefix) / "page/2/index.html"
    assert pages[1].url.endswith("/page/2/")
    assert pages[1].previous_url == pages[0].url


@pytest.mark.parametrize("enabled", [False, True])
def test_tag01_boolean_configuration_and_context(seo_config, enabled):
    from articulous.pipeline import build_ctx_from_config
    _, config = seo_config
    config["site"]["pagination"]["paginate_tags"] = enabled
    validate_config(config)
    assert build_ctx_from_config(config, False).paginate_tags is enabled


def test_tag01_legacy_config_loads_without_rewriting(tmp_path):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["site"]["pagination"].pop("paginate_tags", None)
    path = tmp_path / "config.json"
    original = json.dumps(config).encode()
    path.write_bytes(original)
    loaded = load_or_create_config(path)
    assert loaded["site"]["pagination"]["paginate_tags"] is False
    assert path.read_bytes() == original


@pytest.mark.parametrize("seed", [11, 2026, 0xC0FFEE])
def test_tag01_seeded_invalid_boolean_fuzz(seed, tmp_path):
    rng = random.Random(seed)
    invalid = [None, 0, 1, "true", "false", [], {}, 1.5]
    invalid.extend(rng.randint(-10**15, 10**15) for _ in range(20))
    path = tmp_path / "config.json"
    for value in invalid:
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["site"]["pagination"]["paginate_tags"] = value
        original = json.dumps(config).encode()
        path.write_bytes(original)
        with pytest.raises(ValueError, match="paginate_tags"):
            load_or_create_config(path)
        assert path.read_bytes() == original


def _seed_content(root, count):
    for path in (root / "content").rglob("*.xml"):
        path.unlink()
    for index in range(count):
        _write_post(root, f"post-{index:02}")
    _write_post(root, "french", lang="fr")
    _write_post(root, "hidden", status="unlisted")
    _write_post(root, "private", status="private")


def _write_post(root, slug, lang="en", status="published"):
    (root / "content" / lang / f"{slug}.xml").write_text(
        f"<article><title>{slug}</title><slug>{slug}</slug><lang>{lang}</lang>"
        f"<date>2025-01-01</date><status>{status}</status><tag>News</tag></article>"
    )


def _page(root, number=1, lang="en"):
    path = root / "output" / lang / "tags/news"
    if number > 1:
        path /= f"page/{number}"
    return etree.HTML((path / "index.html").read_bytes())


def _pagination_config(config):
    config["site"]["pagination"].update(per_page=10, paginate_tags=True)
    config["sitemap"]["include_listings"] = True


def test_tag01_real_build_sitemap_navigation_and_cache(site_root, seo_config):
    cli, config = seo_config
    _seed_content(site_root, 21)
    _pagination_config(config)
    run_build(cli, config, site_root)
    pages = [_page(site_root, i) for i in (1, 2, 3)]
    assert [len(page.xpath("//li/a")) for page in pages] == [10, 10, 1]
    urls = [page.xpath("string(//link[@rel='canonical']/@href)") for page in pages]
    assert pages[0].xpath("//a[@rel='next']/@href") == [urls[1]]
    assert pages[1].xpath("//a[@rel='prev']/@href") == [urls[0]]
    assert pages[2].xpath("//a[@rel='next']/@href") == []
    assert len(_page(site_root, lang="fr").xpath("//li/a")) == 1
    sitemap = etree.parse(str(site_root / "output/sitemap.xml"))
    assert set(urls) <= set(sitemap.xpath("//*[local-name()='loc']/text()"))
    files = list((site_root / "output").rglob("*.html"))
    times = {path: path.stat().st_mtime_ns for path in files}
    run_build(cli, config, site_root)
    assert times == {path: path.stat().st_mtime_ns for path in files}


def test_tag01_filtered_build_prunes_only_selected_language(site_root, seo_config):
    cli, config = seo_config
    _seed_content(site_root, 21)
    _pagination_config(config)
    run_build(cli, config, site_root)
    assert (site_root / "output/en/tags/news/page/3/index.html").is_file()
    french = site_root / "output/fr/tags/news/index.html"
    original = french.read_bytes()
    for path in sorted((site_root / "content/en").glob("post-*.xml"))[9:]:
        path.unlink()
    cli.only_sections = {"tags"}
    cli.only_langs = ["en"]
    run_build(cli, config, site_root)
    assert len(_page(site_root).xpath("//li/a")) == 9
    assert not (site_root / "output/en/tags/news/page").exists()
    assert french.read_bytes() == original


def test_tag01_disabling_pagination_removes_old_pages(site_root, seo_config):
    cli, config = seo_config
    _seed_content(site_root, 21)
    _pagination_config(config)
    run_build(cli, config, site_root)
    assert (site_root / "output/en/tags/news/page/3/index.html").is_file()
    config["site"]["pagination"]["paginate_tags"] = False
    run_build(cli, config, site_root)
    assert len(_page(site_root).xpath("//li/a")) == 21
    assert not (site_root / "output/en/tags/news/page").exists()


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_tag01_model_api_requires_boolean(value):
    with pytest.raises(ValueError, match="paginate"):
        build_tags_models([], "en", _context(), paginate=value)


@pytest.mark.parametrize("size", [1, 2, 10, 2**63, 10**100])
def test_tag01_large_and_small_page_sizes(size):
    articles = [_article(i) for i in range(21)]
    pages = build_tags_models(articles, "en", _context(per_page=size), paginate=True)
    assert len(pages) == (len(articles) + size - 1) // size
    assert [a for page in pages for a in page.articles] == articles
