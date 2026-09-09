"""SEO-06: explicit translations render reciprocal, valid hreflang links."""
import random
from xml.sax.saxutils import escape

import lxml.etree as etree
import pytest

from articulous.articles import parse_article_xml
from articulous.pipeline import run_build
from articulous.translations import _cached_metadata, hreflang


def _translation_pair(root):
    for relative in ["en/first-post.xml", "fr/premier.xml"]:
        path = root / "content" / relative
        path.write_text(path.read_text().replace("</article>", "<translation>first</translation></article>"))


def _alternates(path):
    root = etree.HTML(path.read_bytes())
    return {node.get("hreflang"): node.get("href") for node in root.xpath("head/link[@rel='alternate']")}


def test_seo06_reciprocal_links_use_explicit_relationships(site_root, seo_config):
    cli, config = seo_config
    _translation_pair(site_root)
    config["site"]["base_url"] = "https://example.test/blog"
    config["urls"]["article"] = "/posts/{lang}/{slug}/"
    run_build(cli, config, site_root)
    en = site_root / "output/posts/en/first-post/index.html"
    fr = site_root / "output/posts/fr/premier-article/index.html"
    expected = {"en": "https://example.test/blog/posts/en/first-post/", "fr": "https://example.test/blog/posts/fr/premier-article/"}
    assert _alternates(en) == _alternates(fr) == expected
    assert not _alternates(site_root / "output/posts/en/second-post/index.html")
    cli.only_langs = ["en"]
    run_build(cli, config, site_root)
    assert _alternates(en) == _alternates(fr) == expected


@pytest.mark.parametrize("extra", ["<status>private</status>", "<indexing>noindex</indexing>"])
def test_seo06_ineligible_translations_are_removed_and_invalidate_peers(site_root, seo_config, extra):
    cli, config = seo_config
    _translation_pair(site_root)
    run_build(cli, config, site_root)
    fr = site_root / "content/fr/premier.xml"
    fr.write_text(fr.read_text().replace("</article>", extra + "</article>"))
    run_build(cli, config, site_root)
    en = site_root / "output/en/articles/first-post/index.html"
    assert _alternates(en) == {"en": "https://example.test/en/articles/first-post/"}


def test_seo06_partial_relationship_change_requires_full_build(site_root, seo_config):
    cli, config = seo_config
    _translation_pair(site_root)
    run_build(cli, config, site_root)
    en = site_root / "content/en/first-post.xml"
    en.write_text(en.read_text().replace("<translation>first</translation>", ""))
    cli.only_langs = ["en"]
    with pytest.raises(ValueError, match="full build.*translation"):
        run_build(cli, config, site_root)
    cli.only_langs = None
    run_build(cli, config, site_root)
    assert not _alternates(site_root / "output/en/articles/first-post/index.html")


@pytest.mark.parametrize("locale,expected", [("en_US", "en-US"), ("pt-br", "pt-BR"), ("zh_Hant_TW", "zh-Hant-TW")])
def test_seo06_normalizes_annotation_without_changing_route(site_root, seo_config, locale, expected):
    cli, config = seo_config
    config["site"]["languages"] = [locale, "fr"]
    config["site"]["default_language"] = locale
    _translation_pair(site_root)
    run_build(cli, config, site_root)
    page = site_root / f"output/{locale}/articles/first-post/index.html"
    assert _alternates(page)[expected] == f"https://example.test/{locale}/articles/first-post/"


def test_seo06_duplicate_group_locale_fails_before_publication(site_root, seo_config):
    cli, config = seo_config
    for path in (site_root / "content/en").glob("*.xml"):
        path.write_text(path.read_text().replace("</article>", "<translation>same</translation></article>"))
    with pytest.raises(ValueError, match="Duplicate translation"):
        run_build(cli, config, site_root)
    assert not (site_root / "output").exists()


def test_seo06_reproducible_invalid_identifier_fuzz(tmp_path):
    rng = random.Random(6)
    values = ["", "a" * 129, "../x", "name/path", "white space"]
    values.extend("id" + rng.choice("/<>%&日本") + str(rng.randrange(1000)) for _ in range(40))
    path = tmp_path / "article.xml"
    for value in values:
        path.write_text(f"<article><date>2024-01-01</date><translation>{escape(value)}</translation></article>")
        assert parse_article_xml(path) is None


@pytest.mark.parametrize("extra", ["<translation>x</translation><translation>x</translation>", "<translation>x<child/></translation>"])
def test_seo06_duplicate_nested_identifiers_rejected(tmp_path, extra):
    path = tmp_path / "article.xml"
    path.write_text(f"<article><date>2024-01-01</date>{extra}</article>")
    assert parse_article_xml(path) is None


@pytest.mark.parametrize("identifier", ["x", "a" * 128, "Story-2024_first"])
def test_seo06_valid_identifier_boundaries(tmp_path, identifier):
    path = tmp_path / "article.xml"
    path.write_text(f"<article><date>2024-01-01</date><translation>{identifier}</translation></article>")
    article = parse_article_xml(path)
    assert article is not None
    assert article.translation == identifier


def test_seo06_reproducible_invalid_locale_fuzz():
    rng = random.Random(600)
    values = ["", "en_US_extra", "en-UK", "en-XX", "zz", "eng", "es-419", "en-Abcd", "en/EU"]
    values.extend("en_" + str(rng.randrange(1000)) for _ in range(40))
    for value in values:
        with pytest.raises(ValueError, match="Unsupported translation locale"):
            hreflang(value)


def test_seo06_new_partial_group_requires_full_build(site_root, seo_config):
    cli, config = seo_config
    _translation_pair(site_root)
    cli.only_slugs = ["first-post"]
    with pytest.raises(ValueError, match="full build.*translation"):
        run_build(cli, config, site_root)
    assert not (site_root / "output").exists()


@pytest.mark.parametrize("change", ["private", "deleted", "ungrouped"])
def test_seo06_partial_build_rejects_stale_unselected_peer(site_root, seo_config, change):
    cli, config = seo_config
    _translation_pair(site_root)
    run_build(cli, config, site_root)
    path = site_root / "content/fr/premier.xml"
    replacements = {"private": "<status>private</status>", "ungrouped": ""}
    if change == "deleted":
        path.unlink()
    else:
        path.write_text(path.read_text().replace("<translation>first</translation>", replacements[change]))
    cli.only_langs = ["en"]
    with pytest.raises(ValueError, match="full build.*translation"):
        run_build(cli, config, site_root)


@pytest.mark.parametrize("fingerprint", [None, [], {}, ["not-json", "base"], ["[]", "base"], ["{}", "base"]])
def test_seo06_legacy_or_invalid_fingerprints_have_no_translation_metadata(fingerprint):
    assert _cached_metadata(fingerprint) == {}


def test_seo06_relative_urls_omit_annotations(site_root, seo_config):
    cli, config = seo_config
    cli.only_sections = {"articles"}
    config["site"]["base_url"] = ""
    _translation_pair(site_root)
    run_build(cli, config, site_root)
    assert not _alternates(site_root / "output/en/articles/first-post/index.html")
