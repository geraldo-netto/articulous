"""Duplicate singleton metadata must not silently select a publication policy."""
import json

import lxml.etree as etree
import pytest

from articulous.articles import parse_article_xml


SINGLETON_VALUES = {
    "title": "Title", "date": "2025-01-01", "description": "Description",
    "lang": "en", "status": "published", "publish-at": "2025-01-01T00:00:00Z",
}


def _duplicate_field(path, field, mode):
    root = etree.parse(str(path)).getroot()
    for child in root.findall(field):
        root.remove(child)
    first = SINGLETON_VALUES[field] if mode != "empty" else ""
    second = first if mode != "different" else "conflicting value"
    for value in (first, second):
        etree.SubElement(root, field).text = value
    path.write_bytes(etree.tostring(root))


@pytest.mark.parametrize("field", SINGLETON_VALUES)
@pytest.mark.parametrize("mode", ["identical", "empty", "different"])
def test_parser_rejects_any_duplicate_singleton(site_root, caplog, field, mode):
    source = site_root / "content/en/first-post.xml"
    _duplicate_field(source, field, mode)
    with caplog.at_level("WARNING"):
        assert parse_article_xml(source) is None
    assert any(str(source) in record.message and f"duplicate singleton field <{field}>" in record.message
               for record in caplog.records)


def test_repeated_tags_remain_valid_article_metadata(site_root):
    source = site_root / "content/en/first-post.xml"
    root = etree.parse(str(source)).getroot()
    etree.SubElement(root, "tag").text = "intro"
    source.write_bytes(etree.tostring(root))
    article = parse_article_xml(source)
    assert article is not None
    assert article.tags == ("intro", "news", "intro")


@pytest.mark.parametrize("field", SINGLETON_VALUES)
def test_cli_reports_duplicate_field_and_retracts_prior_output(site_root, run_sitegen, field):
    run_sitegen([])
    source = site_root / "content/en/first-post.xml"
    _duplicate_field(source, field, "identical")
    result = run_sitegen([])
    diagnostic = result.stdout.decode() + result.stderr.decode()
    assert str(source) in diagnostic
    assert f"duplicate singleton field <{field}>" in diagnostic
    output = site_root / "output"
    assert not (output / "en/articles/first-post/index.html").exists()
    assert not (output / "en/tags/intro/index.html").exists()
    assert all("first-post" not in item["url"] for item in json.loads((output / "search.json").read_text()))
    for page in ("en/page/1/index.html", "rss.xml", "sitemap.xml"):
        assert "first-post" not in (output / page).read_text()


@pytest.mark.parametrize("statuses", [("private", "published"), ("published", "private")])
def test_conflicting_statuses_cannot_publish_in_either_order(site_root, run_sitegen, statuses):
    source = site_root / "content/en/first-post.xml"
    root = etree.parse(str(source)).getroot()
    for status in statuses:
        etree.SubElement(root, "status").text = status
    source.write_bytes(etree.tostring(root))
    result = run_sitegen([])
    assert b"duplicate singleton field <status>" in result.stdout + result.stderr
    assert not (site_root / "output/en/articles/first-post/index.html").exists()
    assert "first-post" not in (site_root / "output/search.json").read_text()
