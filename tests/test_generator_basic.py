"""Subprocess-driven smoke test of the full build pipeline."""

import json
from urllib.parse import urlsplit

import lxml.etree as etree
import pytest


def test_full_build_via_cli(site_root, run_sitegen):
    run_sitegen(["--force", "--verbose"])
    assert (site_root / "output").is_dir()


def test_required_output_files(site_root, run_sitegen):
    run_sitegen(["--force"])
    required = [
        site_root / "output" / "rss.xml",
        site_root / "output" / "sitemap.xml",
        site_root / "output" / "search.json",
        site_root / "output" / "en" / "articles" / "first-post" / "index.html",
        site_root / "output" / "en" / "articles" / "second-post" / "index.html",
        site_root / "output" / "fr" / "articles" / "premier-article" / "index.html",
        site_root / "output" / "assets" / "style.css",
    ]
    missing = [p for p in required if not p.exists()]
    assert not missing, f"Missing required output files: {missing}"


def test_dry_run_creates_nothing_meaningful(site_root, run_sitegen):
    run_sitegen(["--dry-run", "--force"])
    assert not (site_root / "output" / "rss.xml").exists()
    assert not (site_root / "output" / "search.json").exists()


def test_fixture_rss_has_required_channel_and_article_links(site_root, run_sitegen):
    run_sitegen([])
    root = etree.parse(str(site_root / "output/rss.xml")).getroot()
    assert root.tag == "rss"
    assert root.attrib["version"] == "2.0"
    assert len(root.findall("channel")) == 1
    channel = root.find("channel")
    assert channel.findtext("title") == "Articulous Test Site"
    assert channel.findtext("description")
    _assert_fixture_page_exists(site_root, channel.findtext("link"))
    assert len(channel.findall("item")) == 3
    for item in channel.findall("item"):
        assert item.findtext("title")
        _assert_fixture_page_exists(site_root, item.findtext("link"))


def _assert_fixture_page_exists(site_root, url):
    parsed = urlsplit(url)
    assert (parsed.scheme, parsed.netloc) == ("https", "example.test")
    assert (site_root / "output" / parsed.path.lstrip("/") / "index.html").is_file()


@pytest.mark.parametrize("engine", ["native", "lxml"])
def test_fixture_sitemap_has_namespaced_locations(site_root, run_sitegen, engine):
    config_path = site_root / "config.json"
    config = json.loads(config_path.read_text())
    config["engines"]["sitemap"] = engine
    config_path.write_text(json.dumps(config))
    run_sitegen([])
    root = etree.parse(str(site_root / "output/sitemap.xml")).getroot()
    namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    assert root.tag == namespace + "urlset"
    assert len(root) == 3
    for entry in root:
        assert entry.tag == namespace + "url"
        assert [child.tag for child in entry] == [namespace + "loc"]
        _assert_fixture_page_exists(site_root, entry.findtext(namespace + "loc"))
