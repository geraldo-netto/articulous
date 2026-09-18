"""A site chooses one feed for everything, or one feed per language.

``urls.rss`` decides: naming ``{lang}`` opts into a feed per language, so a
subscriber reads only the language they picked instead of the same article
once per translation. Leaving the pattern alone keeps the single feed.
"""
import json
from pathlib import Path

import pytest
from lxml import etree

from articulous.cli import CliOptions, parse_cli_args
from articulous.config import apply_cli_overrides, load_or_create_config
from articulous.models import build_rss_model
from articulous.pipeline import run_build
from articulous.sections import section_is_per_lang, validate_url_pattern


def _build(root):
    cli = CliOptions(parse_cli_args([]))
    config = load_or_create_config(root / "config.json")
    apply_cli_overrides(config, cli, root)
    run_build(cli, config, root)


def _ctx(**overrides):
    from types import SimpleNamespace
    base = {
        "base_url": "https://example.test",
        "languages": ["en", "fr"],
        "rss_items": 5,
        "url_patterns": {"rss": "/{lang}/rss.xml"},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# --- pattern policy ---

def test_rss_accepts_the_optional_language_placeholder():
    validate_url_pattern("rss", "/rss.xml")
    validate_url_pattern("rss", "/{lang}/rss.xml")


def test_rss_still_rejects_placeholders_it_does_not_offer():
    with pytest.raises(ValueError) as failure:
        validate_url_pattern("rss", "/{tag}/rss.xml")
    message = str(failure.value)
    assert "optional ['lang']" in message
    assert "['tag']" in message


def test_section_scope_follows_the_pattern():
    assert not section_is_per_lang("rss", "/rss.xml")
    assert section_is_per_lang("rss", "/{lang}/rss.xml")
    # A section that is per-language by nature stays that way.
    assert section_is_per_lang("articles", "/{lang}/articles/{slug}/")


# --- model ---

def test_rss_model_places_the_feed_under_its_language():
    feed = build_rss_model([], _ctx(), "fr")
    assert feed.output_path == Path("fr/rss.xml")
    assert feed.url == "https://example.test/fr/rss.xml"


def test_rss_model_without_a_language_keeps_the_single_feed():
    feed = build_rss_model([], _ctx(url_patterns={"rss": "/rss.xml"}))
    assert feed.output_path == Path("rss.xml")


# --- end to end ---

def _configure_per_language_feeds(site_root):
    path = site_root / "config.json"
    config = json.loads(path.read_text())
    config["urls"]["rss"] = "/{lang}/rss.xml"
    path.write_text(json.dumps(config))
    return config["site"]["languages"]


def test_each_language_gets_its_own_feed(site_root):
    languages = _configure_per_language_feeds(site_root)
    _build(site_root)
    assert not (site_root / "output/rss.xml").exists()
    for lang in languages:
        feed = site_root / "output" / lang / "rss.xml"
        assert feed.is_file(), f"missing feed for {lang}"
        channel = etree.parse(str(feed)).getroot().find("channel")
        links = [item.findtext("link") for item in channel.findall("item")]
        assert links, f"feed for {lang} is empty"
        for link in links:
            assert f"/{lang}/" in link, f"{lang} feed carries {link}"


def test_a_language_without_articles_still_publishes_a_feed(site_root):
    _configure_per_language_feeds(site_root)
    for path in (site_root / "content/fr").glob("*.xml"):
        path.unlink()
    _build(site_root)
    feed = site_root / "output/fr/rss.xml"
    assert feed.is_file(), "an enabled language must be subscribable before it has articles"
    channel = etree.parse(str(feed)).getroot().find("channel")
    assert channel.findall("item") == []


def test_the_single_feed_remains_the_default(site_root):
    _build(site_root)
    assert (site_root / "output/rss.xml").is_file()
    assert not (site_root / "output/en/rss.xml").exists()
