"""SEO-04: indexing directives are independent of publication status."""
import random
from xml.sax.saxutils import escape

import lxml.etree as etree
import pytest

from articulous.articles import parse_article_xml
from articulous.pipeline import run_build


@pytest.mark.parametrize("status", ["published", "unlisted", "private", "draft"])
@pytest.mark.parametrize("directive", ["index", "noindex"])
def test_seo04_indexing_publication_matrix(site_root, seo_config, status, directive):
    cli, config = seo_config
    source = site_root / "content/en/first-post.xml"
    source.write_text(source.read_text().replace("</article>", f"<status>{status}</status><indexing>{directive}</indexing></article>"))
    article = parse_article_xml(source)
    assert article is not None
    assert article.indexable == (status in {"published", "unlisted"} and directive == "index")
    run_build(cli, config, site_root)
    page = site_root / "output/en/articles/first-post/index.html"
    assert page.exists() == (status in {"published", "unlisted"})
    assert ("first-post" in (site_root / "output/sitemap.xml").read_text()) == (status == "published" and directive == "index")
    if page.exists():
        root = etree.HTML(page.read_bytes())
        assert root.xpath("head/meta[@name='robots']/@content") == (["noindex"] if directive == "noindex" else [])


def test_seo04_directive_change_rebuilds_page_and_sitemap(site_root, seo_config):
    cli, config = seo_config
    source = site_root / "content/en/first-post.xml"
    original = source.read_text()
    for extra, expected in [("", True), ("<indexing>noindex</indexing>", False), ("", True)]:
        source.write_text(original.replace("</article>", extra + "</article>"))
        run_build(cli, config, site_root)
        page = etree.HTML((site_root / "output/en/articles/first-post/index.html").read_bytes())
        assert bool(page.xpath("head/meta[@name='robots']")) != expected
        assert ("first-post" in (site_root / "output/sitemap.xml").read_text()) == expected


def test_seo04_reproducible_invalid_directive_fuzz(tmp_path):
    rng = random.Random(4)
    path = tmp_path / "article.xml"
    values = ["", "INDEX", "none", "true", "noindex,follow", "x" * 4096]
    values.extend("".join(rng.choices("indexNO <>/日本", k=rng.randrange(1, 40))) for _ in range(40))
    for value in values:
        path.write_text(f"<article><title>Valid</title><date>2024-02-29</date><indexing>{escape(value)}</indexing></article>")
        assert parse_article_xml(path) is None


@pytest.mark.parametrize("extra", ["<indexing>index</indexing><indexing>noindex</indexing>", "<indexing>noindex<child/></indexing>"])
def test_seo04_duplicate_and_nested_directives_rejected(tmp_path, extra):
    path = tmp_path / "article.xml"
    path.write_text(f"<article><title>Valid</title><date>2024-02-29</date>{extra}</article>")
    assert parse_article_xml(path) is None
