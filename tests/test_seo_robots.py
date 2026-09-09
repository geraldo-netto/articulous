"""SEO-05: optional host-root robots.txt uses validated sitemap discovery."""
import random

import pytest

from articulous.config import validate_config
from articulous.pipeline import run_build


@pytest.mark.parametrize("engine", ["native", "lxml"])
def test_seo05_robots_contains_absolute_sitemap_and_prunes_when_disabled(site_root, seo_config, engine):
    cli, config = seo_config
    config["robots"] = {"enabled": True}
    config["engines"]["sitemap"] = engine
    config["site"]["base_url"] = "https://example.test/blog"
    run_build(cli, config, site_root)
    output = site_root / "output/robots.txt"
    assert output.read_text() == "User-agent: *\nAllow: /\nSitemap: https://example.test/blog/sitemap.xml\n"
    before = output.stat().st_mtime_ns
    run_build(cli, config, site_root)
    assert output.stat().st_mtime_ns == before
    cli.only_sections = {"sitemap"}
    config["robots"]["enabled"] = False
    run_build(cli, config, site_root)
    assert not output.exists()


def test_seo05_robots_dry_run_leaves_no_publication(site_root, seo_config):
    cli, config = seo_config
    config["robots"] = {"enabled": True}
    cli.dry_run = True
    run_build(cli, config, site_root)
    assert not (site_root / "output").exists()
    assert not (site_root / ".build-cache.json").exists()


def test_seo05_robots_collision_fails_before_publication(site_root, seo_config):
    cli, config = seo_config
    config["robots"] = {"enabled": True}
    config["urls"]["search"] = "/robots.txt"
    with pytest.raises(ValueError, match="Duplicate generated output path"):
        run_build(cli, config, site_root)
    assert not (site_root / "output").exists()


@pytest.mark.parametrize("base", ["", "/blog", "https://example.test/\nDisallow: /", "ftp://example.test", "https://example.test/%0a"])
def test_seo05_invalid_discovery_urls_rejected_with_custom_xslt(site_root, seo_config, base):
    cli, config = seo_config
    config["robots"] = {"enabled": True}
    config["engines"]["sitemap"] = "lxml"
    config["site"]["base_url"] = base
    with pytest.raises(ValueError):
        run_build(cli, config, site_root)
    assert not (site_root / "output").exists()


def test_seo05_reproducible_invalid_rule_and_option_fuzz(seo_config):
    _, config = seo_config
    rng = random.Random(5)
    values = [None, 0, 1, "true", [], {}, -1]
    values.extend(rng.getrandbits(128) for _ in range(20))
    for value in values:
        config["robots"] = {"enabled": value}
        with pytest.raises(ValueError):
            validate_config(config)
    for rule in ["Disallow: /", "Allow: /assets/", "Sitemap: https://other.test/map.xml", "\nUser-agent: *"]:
        config["robots"] = {"enabled": True, "rules": rule}
        with pytest.raises(ValueError, match="unknown"):
            validate_config(config)
    for enabled in [True, False]:
        config["robots"] = {"enabled": enabled}
        validate_config(config)
