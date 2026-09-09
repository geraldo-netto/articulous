"""SEO-10: optional structured data matches visible content and stays inert."""
import json
import os
import random
from xml.sax.saxutils import escape

import lxml.etree as etree
import pytest

from articulous.articles import parse_article_xml
from articulous.pipeline import run_build
from articulous.engines import SaxonCEngine


def _jsonld(page):
    root = etree.HTML(page.read_bytes())
    scripts = root.xpath("head/script[@type='application/ld+json']/text()")
    return root, [json.loads(text) for text in scripts]


@pytest.mark.parametrize("kind", ["Article", "BlogPosting"])
def test_seo10_structured_data_matches_visible_metadata(site_root, seo_config, kind):
    cli, config = seo_config
    source = site_root / "content/en/first-post.xml"
    extra = (f"<structured-data>{kind}</structured-data><author>Zoë 日本語</author>"
             "<image>https://example.test/image.jpg?w=800&amp;h=600</image><modified>2025-02-01</modified>")
    source.write_text(source.read_text().replace("</article>", extra + "</article>"))
    config["site"]["base_url"] = "https://example.test/blog"
    run_build(cli, config, site_root)
    root, scripts = _jsonld(site_root / "output/en/articles/first-post/index.html")
    data = scripts[0]
    assert data["@type"] == kind
    assert data["@context"] == "https://schema.org"
    assert data["headline"] == root.xpath("string(body/h1)")
    assert data["description"] == root.xpath("string(body/p[1])")
    assert data["author"] == {"@type": "Person", "name": root.xpath("string(body/p[@class='author'])")}
    assert data["image"] == root.xpath("string(body/img/@src)")
    assert data["datePublished"] == root.xpath("string(body/time[@class='published']/@datetime)")
    assert data["dateModified"] == "2025-02-01" == root.xpath("string(body/time[@class='modified']/@datetime)")
    assert data["mainEntityOfPage"] == root.xpath("string(head/link[@rel='canonical']/@href)")


def test_seo10_optional_values_and_opt_in(site_root, seo_config):
    cli, config = seo_config
    run_build(cli, config, site_root)
    page = site_root / "output/en/articles/first-post/index.html"
    assert _jsonld(page)[1] == []
    source = site_root / "content/en/first-post.xml"
    source.write_text(source.read_text().replace("</article>", "<structured-data>Article</structured-data></article>"))
    run_build(cli, config, site_root)
    data = _jsonld(page)[1][0]
    assert not {"author", "image", "dateModified"}.intersection(data)


def test_seo10_reproducible_script_termination_fuzz(site_root, seo_config):
    cli, config = seo_config
    cli.only_sections = {"articles"}
    rng = random.Random(10)
    source = site_root / "content/en/first-post.xml"
    original = source.read_text()
    values = ['</script><script>alert("x")</script>', '<!-- </ScRiPt> --> &', 'Unicode 日本語 \u2028 middle \u2029 end']
    values.extend(''.join(rng.choices('<>/script&\"\'日本', k=40)) for _ in range(12))
    for value in values:
        extra = "<structured-data>BlogPosting</structured-data><author>" + escape(value) + "</author>"
        source.write_text(original.replace("</article>", extra + "</article>"))
        run_build(cli, config, site_root)
        root, scripts = _jsonld(site_root / "output/en/articles/first-post/index.html")
        assert len(root.xpath("//script")) == 1
        assert scripts[0]["author"]["name"] == value


@pytest.mark.parametrize("field,value", [
    ("structured-data", ""), ("structured-data", "Person"), ("structured-data", "article"),
    ("author", ""), ("author", "x" * 513), ("image", ""), ("image", "javascript:alert(1)"),
    ("image", "https://example.test/x y"), ("image", "https://example.test/x?q=%GG"),
    ("image", "https://example.test/x#fragment"), ("image", "https://user:pass@example.test/x"),
    ("image", "https://example.test/x?q=1#fragment"),
])
def test_seo10_invalid_metadata_rejected(tmp_path, field, value):
    path = tmp_path / "article.xml"
    path.write_text(f"<article><date>2024-01-01</date><{field}>{escape(value)}</{field}></article>")
    assert parse_article_xml(path) is None


@pytest.mark.parametrize("field,value", [("author", "A" * 512), ("author", "é" * 512), ("image", "https://example.test/x?"), ("image", "https://example.test/%C3%A9.jpg?w=1&h=2")])
def test_seo10_valid_metadata_boundaries(tmp_path, field, value):
    path = tmp_path / "article.xml"
    path.write_text(f"<article><date>2024-01-01</date><{field}>{escape(value)}</{field}></article>")
    article = parse_article_xml(path)
    assert article is not None
    assert getattr(article, field) == value


@pytest.mark.parametrize("field,value", [("author", "Name"), ("image", "https://example.test/i"), ("structured-data", "Article")])
def test_seo10_duplicate_and_nested_fields_rejected(tmp_path, field, value):
    path = tmp_path / "article.xml"
    for content in [f"<{field}>{value}</{field}>" * 2, f"<{field}>{value}<child/></{field}>"]:
        path.write_text(f"<article><date>2024-01-01</date>{content}</article>")
        assert parse_article_xml(path) is None


def test_seo10_relative_url_omits_structured_data(site_root, seo_config):
    cli, config = seo_config
    cli.only_sections = {"articles"}
    config["site"]["base_url"] = ""
    source = site_root / "content/en/first-post.xml"
    source.write_text(source.read_text().replace("</article>", "<structured-data>Article</structured-data></article>"))
    run_build(cli, config, site_root)
    assert _jsonld(site_root / "output/en/articles/first-post/index.html")[1] == []


def test_seo10_reproducible_malformed_metadata_fuzz(tmp_path):
    rng = random.Random(1010)
    path = tmp_path / "article.xml"
    for _ in range(30):
        value = rng.choice(["javascript:", "data:", "file:", "ftp:"]) + str(rng.getrandbits(64))
        path.write_text(f"<article><date>2024-01-01</date><image>{value}</image></article>")
        assert parse_article_xml(path) is None


@pytest.mark.parametrize("name", ["articulous-jsonld", "articulous-extra"])
def test_seo10_large_saxon_parameters_use_literal_stylesheet_values(tmp_path, monkeypatch, name):
    stylesheet = tmp_path / "large.xsl"
    stylesheet.write_text(
        '<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
        '<xsl:param name="articulous-jsonld"><xsl:text>fallback</xsl:text></xsl:param>'
        '<xsl:template match="/"><out/></xsl:template></xsl:stylesheet>'
    )
    value = "Quoted ' Unicode café " * 10000
    observed = []

    def transform(command, check, pass_fds):
        assert all(len(argument.encode()) < 32768 for argument in command)
        path = next(argument[5:] for argument in command if argument.startswith("-xsl:"))
        root = etree.parse(path)
        node = root.xpath("/*/*[local-name()='param' and @name=$name]", name=name)[0]
        observed.append(node.get("select"))
        assert len(node) == 0
        os.write(pass_fds[0], b"<out/>")

    monkeypatch.setattr("articulous.engines.subprocess.run", transform)
    SaxonCEngine(tmp_path / "Transform").run(b"<root/>", stylesheet, tmp_path / "out.xml", parameters={name: value})
    assert observed == ["'" + value.replace("'", "''") + "'"]
