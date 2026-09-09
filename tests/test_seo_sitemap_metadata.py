"""SEO-07: trustworthy modification dates and complete optional listings."""
import random
from xml.sax.saxutils import escape

import lxml.etree as etree
import pytest

from articulous.articles import parse_article_xml
from articulous.config import validate_config
from articulous.pipeline import run_build


@pytest.mark.parametrize("engine", ["native", "lxml"])
def test_seo07_modification_changes_rebuild_native_and_xslt(site_root, seo_config, engine):
    cli, config = seo_config
    config["engines"]["sitemap"] = engine
    config["urls"]["article"] = "/café/{lang}/{slug}/"
    source = site_root / "content/en/first-post.xml"
    original = source.read_text()
    for modified in ["2024-02-29", "2025-01-01T12:30:00+02:00"]:
        source.write_text(original.replace("</article>", f"<modified>{modified}</modified></article>"))
        run_build(cli, config, site_root)
        root = etree.parse(str(site_root / "output/sitemap.xml"))
        assert root.xpath("//*[local-name()='lastmod']/text()") == [modified]
        assert "%C3%A9" in root.xpath("string(//*[local-name()='loc'])")


def test_seo07_listing_scope_remains_global_when_filtered(site_root, seo_config):
    cli, config = seo_config
    config["sitemap"] = {"include_listings": True}
    cli.only_sections = {"sitemap"}
    cli.only_langs = ["fr"]
    cli.only_slugs = ["premier"]
    config["site"]["pagination"]["per_page"] = 1
    run_build(cli, config, site_root)
    root = etree.parse(str(site_root / "output/sitemap.xml"))
    urls = root.xpath("//*[local-name()='loc']/text()")
    assert "https://example.test/en/page/1/" in urls
    assert "https://example.test/en/page/2/" in urls
    assert "https://example.test/fr/page/1/" in urls
    assert "https://example.test/en/tags/intro/" in urls
    assert not root.xpath("//*[local-name()='lastmod']")


@pytest.mark.parametrize("modified", ["0001-01-01", "9999-12-31", "2024-02-29", "2024-01-01T00:00:00Z", "2024-01-01T01:00:00.123456+01:00"])
def test_seo07_valid_modified_boundaries(tmp_path, modified):
    path = tmp_path / "article.xml"
    path.write_text(f"<article><date>2024-01-01</date><modified>{modified}</modified></article>")
    article = parse_article_xml(path)
    assert article is not None
    assert article.modified == modified


def test_seo07_reproducible_invalid_date_fuzz(tmp_path):
    rng = random.Random(7)
    values = ["", "2023-02-29", "0000-01-01", "10000-01-01", "2024-01-01T00:00:00", "20240101", "2024-01-01T25:00:00Z",
              "2024-01-01T00:00:00+00:60", "2024-01-01T00:00:00+24:00"]
    values.extend(f"2024-{rng.randrange(13, 99):02d}-{rng.randrange(1, 99):02d}" for _ in range(40))
    path = tmp_path / "article.xml"
    for value in values:
        path.write_text(f"<article><date>2024-01-01</date><modified>{escape(value)}</modified></article>")
        assert parse_article_xml(path) is None


@pytest.mark.parametrize("extra", ["<modified>2024-01-01</modified><modified>2024-01-01</modified>", "<modified>2024-01-01<child/></modified>"])
def test_seo07_duplicate_nested_modified_rejected(tmp_path, extra):
    path = tmp_path / "article.xml"
    path.write_text(f"<article><date>2024-01-01</date>{extra}</article>")
    assert parse_article_xml(path) is None


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}, -1, 2**128])
def test_seo07_listing_setting_rejects_non_booleans(seo_config, value):
    _, config = seo_config
    config["sitemap"] = {"include_listings": value}
    with pytest.raises(ValueError):
        validate_config(config)
