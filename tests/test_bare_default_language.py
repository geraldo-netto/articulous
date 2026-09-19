"""The default language can own the bare routes.

``site.bare_default_language`` names the sections whose default-language pages
drop the ``/{lang}/`` segment of their pattern: ``/page/2/`` rather than
``/en/page/2/``, ``/tags/linux/`` rather than ``/en/tags/linux/``. Every other
language keeps its prefix. A site whose untranslated pages already live at bare
routes gets listings that behave the same way. The setting is off by default.
"""
import copy
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from articulous.cli import CliOptions, parse_cli_args
from articulous.config import (
    DEFAULT_CONFIG,
    apply_cli_overrides,
    load_or_create_config,
    validate_config,
)
from articulous.models import (
    build_index_models,
    build_rss_model,
    build_tags_models,
    section_pattern,
)
from articulous.pipeline import BuildCtx, _article_url_builder, run_build
from articulous.sections import bare_pattern

PATTERNS = {
    "article": "/{lang}/articles/{slug}/",
    "index": "/{lang}/page/{page}/",
    "tag": "/{lang}/tags/{tag}/",
    "rss": "/{lang}/rss.xml",
    "sitemap": "/sitemap.xml",
    "search": "/search.json",
}


def _config(sections, rss="/{lang}/rss.xml"):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["site"]["bare_default_language"] = sections
    config["urls"]["rss"] = rss
    return config


def _ctx(**overrides):
    base = {
        "base_url": "https://example.test",
        "languages": ["en", "fr"],
        "per_page": 2,
        "rss_items": 5,
        "url_patterns": dict(PATTERNS),
        "default_language": "en",
        "bare_default_language": ("index", "tags", "rss"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _build_ctx(**overrides):
    fields = dict(
        content_dir=Path("content"), xsl_dir=Path("xsl"), output_dir=Path("output"),
        assets_dir=Path("assets"), base_url="https://example.test",
        url_patterns=dict(PATTERNS), default_language="en",
        bare_default_language=("articles",),
    )
    fields.update(overrides)
    return BuildCtx(**fields)


def _build(root):
    cli = CliOptions(parse_cli_args([]))
    config = load_or_create_config(root / "config.json")
    apply_cli_overrides(config, cli, root)
    run_build(cli, config, root)


# --- config ---

def test_the_setting_is_off_by_default():
    assert DEFAULT_CONFIG["site"]["bare_default_language"] == []
    validate_config(copy.deepcopy(DEFAULT_CONFIG))


@pytest.mark.parametrize("sections", [
    ["articles"], ["index"], ["tags"], ["rss"], ["articles", "index", "tags", "rss"],
])
def test_accepts_every_section_that_names_a_language(sections):
    validate_config(_config(sections))


@pytest.mark.parametrize("value,message", [
    (None, "must be a list"),
    ("index", "must be a list"),
    ([7], "must be a list"),
    (["index", "index"], "duplicates"),
    (["sitemap"], "unknown section"),
    (["search"], "unknown section"),
    (["nope"], "unknown section"),
])
def test_rejects_values_that_name_nothing_usable(value, message):
    with pytest.raises(ValueError, match=f"site.bare_default_language.*{message}"):
        validate_config(_config(value))


def test_rejects_a_section_whose_pattern_has_no_language_segment():
    with pytest.raises(ValueError, match=r"urls.rss has no /\{lang\}/ segment"):
        validate_config(_config(["rss"], rss="/rss.xml"))


INVALID_POOL = [None, True, 0, "tags", {"index": True}, [None], [1], ["index", "index"],
                ["sitemap"], ["search"], [""], ["Index"], ["tags", "nope"]]
VALID_POOL = ["articles", "index", "tags", "rss"]


@pytest.mark.parametrize("seed", range(40))
def test_fuzz_invalid_values_are_rejected(seed):
    rng = random.Random(seed)
    value = rng.choice(INVALID_POOL)
    with pytest.raises(ValueError, match="site.bare_default_language"):
        validate_config(_config(value))


@pytest.mark.parametrize("seed", range(40))
def test_fuzz_any_subset_of_real_sections_is_accepted(seed):
    rng = random.Random(seed)
    sections = rng.sample(VALID_POOL, rng.randint(0, len(VALID_POOL)))
    validate_config(_config(sections))


# --- pattern ---

@pytest.mark.parametrize("pattern,expected", [
    ("/{lang}/page/{page}/", "/page/{page}/"),
    ("/{lang}/tags/{tag}/", "/tags/{tag}/"),
    ("/{lang}/rss.xml", "/rss.xml"),
    ("/{lang}/", "/"),
    ("/blog/{lang}/{slug}/", "/blog/{slug}/"),
])
def test_bare_pattern_drops_only_the_language_segment(pattern, expected):
    assert bare_pattern(pattern) == expected


def test_section_pattern_is_bare_only_for_the_default_language_and_listed_sections():
    ctx = _ctx()
    assert section_pattern(ctx, "index", "en") == "/page/{page}/"
    assert section_pattern(ctx, "index", "fr") == "/{lang}/page/{page}/"
    assert section_pattern(ctx, "articles", "en") == "/{lang}/articles/{slug}/"
    assert section_pattern(ctx, "rss", None) == "/{lang}/rss.xml"


def test_a_context_that_predates_the_setting_keeps_its_pattern():
    ctx = _ctx()
    del ctx.bare_default_language
    del ctx.default_language
    assert section_pattern(ctx, "index", "en") == "/{lang}/page/{page}/"


# --- models ---

def test_index_pages_of_the_default_language_lose_their_prefix():
    pages = list(build_index_models([1, 2, 3], "en", _ctx()))
    assert [p.url for p in pages] == ["https://example.test/page/1/", "https://example.test/page/2/"]
    assert [str(p.output_path) for p in pages] == ["page/1/index.html", "page/2/index.html"]
    assert pages[0].next_url == "https://example.test/page/2/"


def test_index_pages_of_other_languages_keep_their_prefix():
    pages = list(build_index_models([1, 2, 3], "fr", _ctx()))
    assert pages[0].url == "https://example.test/fr/page/1/"
    assert str(pages[1].output_path) == "fr/page/2/index.html"


def test_tag_pages_follow_the_same_rule():
    articles = [SimpleNamespace(tags=["Linux"])]
    english, = build_tags_models(articles, "en", _ctx())
    french, = build_tags_models(articles, "fr", _ctx())
    assert (english.url, str(english.output_path)) == ("https://example.test/tags/linux/", "tags/linux/index.html")
    assert (french.url, str(french.output_path)) == ("https://example.test/fr/tags/linux/", "fr/tags/linux/index.html")


def test_the_default_language_feed_can_be_the_bare_feed():
    assert str(build_rss_model([], _ctx(), "en").output_path) == "rss.xml"
    assert str(build_rss_model([], _ctx(), "fr").output_path) == "fr/rss.xml"


def test_article_urls_follow_the_rule_when_articles_are_listed():
    build = _article_url_builder(_build_ctx())
    assert build("en", "hello") == "https://example.test/articles/hello/"
    assert build("fr", "hello") == "https://example.test/fr/articles/hello/"


# --- end to end ---

def _configure(site_root, sections):
    path = site_root / "config.json"
    config = json.loads(path.read_text())
    config["site"]["bare_default_language"] = sections
    path.write_text(json.dumps(config))


def test_a_built_site_places_default_language_listings_at_the_root(site_root):
    _configure(site_root, ["index", "tags"])
    _build(site_root)
    output = site_root / "output"
    assert (output / "page/1/index.html").is_file()
    assert not (output / "en/page").exists()
    assert (output / "fr/page/1/index.html").is_file()
    assert (output / "tags/intro/index.html").is_file()
    assert not (output / "en/tags").exists()
    assert (output / "fr/tags/intro/index.html").is_file()


def test_a_built_site_keeps_its_prefixes_unless_asked(site_root):
    _build(site_root)
    output = site_root / "output"
    assert (output / "en/page/1/index.html").is_file()
    assert not (output / "page").exists()
