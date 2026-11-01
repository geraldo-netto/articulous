"""SOCIAL-018: optional blank images remain absent through native metadata."""
import json
import random

import lxml.etree as etree
import pytest

from articulous.articles import parse_article_xml
from articulous.pipeline import run_build


@pytest.mark.parametrize("value", ["", " ", "\t\n\r ", "\u00a0"])
def test_social018_blank_image_preserves_article_and_source(site_root, value):
    path = site_root / "content/en/first-post.xml"
    root = etree.parse(str(path)).getroot()
    etree.SubElement(root, "image", width="999", alt="unused").text = value
    path.write_bytes(etree.tostring(root))
    captured = path.read_bytes()
    article = parse_article_xml(path)
    assert article is not None
    assert article.image == ""
    assert path.read_bytes() == captured


def test_social018_seeded_blank_and_nonempty_boundaries(site_root):
    path = site_root / "content/en/first-post.xml"
    original = path.read_bytes()
    rng = random.Random(18018)
    for _ in range(64):
        root = etree.fromstring(original)
        etree.SubElement(root, "image").text = "".join(rng.choices(" \t\r\n", k=rng.randrange(33)))
        path.write_bytes(etree.tostring(root))
        article = parse_article_xml(path)
        assert article is not None
        assert article.image == ""
    for _ in range(32):
        root = etree.fromstring(original)
        etree.SubElement(root, "image").text = "https://example.test/a#" + str(rng.getrandbits(32))
        path.write_bytes(etree.tostring(root))
        assert parse_article_xml(path) is None


def test_social018_blank_image_is_omitted_from_jsonld(site_root, seo_config):
    cli, config = seo_config
    source = site_root / "content/en/first-post.xml"
    root = etree.parse(str(source)).getroot()
    etree.SubElement(root, "image").text = "\n\t "
    etree.SubElement(root, "structured-data").text = "BlogPosting"
    source.write_bytes(etree.tostring(root))
    run_build(cli, config, site_root)
    page = etree.HTML((site_root / "output/en/articles/first-post/index.html").read_bytes())
    data = json.loads(page.xpath('string(//script[@type="application/ld+json"])'))
    assert data["@type"] == "BlogPosting"
    assert "image" not in data
