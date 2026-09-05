"""Canonical sitemap locations agree with the generated route tree."""
from urllib.parse import unquote, urlsplit

import lxml.etree as etree
import pytest

from articulous.cli import CliOptions, parse_cli_args
from articulous.config import apply_cli_overrides, load_or_create_config
from articulous.models import build_url_from_pattern
from articulous.pipeline import build_ctx_from_config, build_sitemap_section, run_build
from articulous.sections import validate_sitemap_location


def _configuration(root, args=()):
    cli = CliOptions(parse_cli_args(list(args)))
    config = load_or_create_config(root / "config.json")
    apply_cli_overrides(config, cli, root)
    return cli, config


@pytest.mark.parametrize("url", [
    "", "/relative/", "//example.test/", "ftp://example.test/", "https:///missing-host/",
    "https://example.test/a b", "https://example.test/é", "https://example.test/\n",
    "https://user:pass@example.test/", "https://example.test/?a=b", "https://example.test/#top",
    "https://example.test:0/", "https://example.test:99999/", "https://example.test:bad/",
    "https://example.test/%xx", "https://example.test/" + "a" * 2048,
    "https://example.test/a/../b/", "https://example.test/a/./b/", "https://example.test/a//b/",
    "https://example.test/%2e%2e/b/", "https://example.test/a%5cb/", "https://example.test/%0a",
    "https://example.test/%7f", "https://example.test//a/",
])
def test_native_sitemap_rejects_invalid_locations(url):
    with pytest.raises(ValueError):
        validate_sitemap_location(url)


@pytest.mark.parametrize("url", [
    "https://example.test", "https://example.test/", "http://localhost:8080/blog/",
    "https://[::1]:443/a/", "https://example.test/caf%C3%A9/",
    "https://example.test/" + "a" * (2047 - len("https://example.test/")),
])
def test_native_sitemap_accepts_absolute_encoded_locations(url):
    validate_sitemap_location(url)


@pytest.mark.parametrize("dry_run", [False, True])
def test_relative_base_fails_selected_native_sitemap_before_publication(site_root, dry_run):
    cli, config = _configuration(site_root, ["--dry-run"] if dry_run else [])
    config["site"]["base_url"] = ""
    with pytest.raises(ValueError, match="absolute HTTP"):
        run_build(cli, config, site_root)
    assert not (site_root / "output").exists()
    assert not (site_root / ".build-cache.json").exists()


def test_relative_base_still_supports_sections_without_native_sitemap(site_root):
    cli, config = _configuration(site_root, ["--only", "articles,index,tags,search"])
    config["site"]["base_url"] = ""
    run_build(cli, config, site_root)
    assert (site_root / "output/en/articles/first-post/index.html").exists()
    assert '"url": "/en/articles/first-post/"' in (site_root / "output/search.json").read_text()
    assert not (site_root / "output/sitemap.xml").exists()


def test_custom_xslt_sitemap_keeps_relative_model_contract(site_root):
    cli, config = _configuration(site_root, ["--only", "sitemap"])
    config["site"]["base_url"] = ""
    config["engines"]["sitemap"] = "lxml"
    run_build(cli, config, site_root)
    assert "/en/articles/first-post/" in (site_root / "output/sitemap.xml").read_text()


@pytest.mark.parametrize("url", ["https://other.test/blog/a/", "http://example.test/blog/a/",
                                  "https://example.test/elsewhere/a/"])
def test_native_sitemap_rejects_locations_outside_its_scope(site_root, url):
    _, config = _configuration(site_root)
    config["urls"]["sitemap"] = "/blog/sitemap.xml"
    ctx = build_ctx_from_config(config, False)
    with pytest.raises(ValueError, match="outside its host or directory scope"):
        build_sitemap_section([url], ctx, {})
    assert not ctx.output_dir.exists()


def test_nested_sitemap_cannot_publish_unrelated_tree(site_root):
    cli, config = _configuration(site_root)
    config["urls"]["sitemap"] = "/feeds/sitemap.xml"
    with pytest.raises(ValueError, match="directory scope"):
        run_build(cli, config, site_root)
    assert not (site_root / "output").exists()


def test_canonical_urls_map_to_outputs_beneath_deployment_prefix(site_root):
    cli, config = _configuration(site_root)
    config["site"]["base_url"] = "https://example.test/blog"
    config["urls"]["article"] = "/cafés & news/{lang}/{slug}/"
    run_build(cli, config, site_root)
    root = etree.parse(str(site_root / "output/sitemap.xml")).getroot()
    urls = root.findall("{*}url/{*}loc")
    assert len(urls) == 3
    for loc in urls:
        assert "%C3%A9s%20%26%20news/" in loc.text
        relative = unquote(urlsplit(loc.text).path).removeprefix("/blog/")
        assert (site_root / "output" / relative / "index.html").is_file()


def test_encoded_url_pattern_joins_without_escaping_path_separators():
    assert build_url_from_pattern("", "/café & news/{lang}/", lang="en") == "/caf%C3%A9%20%26%20news/en/"
