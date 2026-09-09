"""SEO-09: explicit slugs survive title edits and reject unsafe routes."""
import random
from xml.sax.saxutils import escape

import pytest

from articulous.articles import parse_article_xml
from articulous.pipeline import run_build


def test_seo09_explicit_slug_stays_stable_and_intentional_changes_prune(site_root, seo_config):
    cli, config = seo_config
    source = site_root / "content/en/first-post.xml"
    original = source.read_text()
    for title, slug in [("First Post", "permanent"), ("Renamed Post", "permanent"), ("Renamed Post", "new-address")]:
        text = original.replace("First Post", title).replace("</article>", f"<slug>{slug}</slug></article>")
        source.write_text(text)
        run_build(cli, config, site_root)
        page = site_root / f"output/en/articles/{slug}/index.html"
        assert title in page.read_text()
        for relative in ["sitemap.xml", "rss.xml", "search.json", "en/page/1/index.html"]:
            output = (site_root / "output" / relative).read_text()
            assert f"/en/articles/{slug}/" in output
            assert "/en/articles/first-post/" not in output
    assert not (site_root / "output/en/articles/permanent/index.html").exists()


@pytest.mark.parametrize("slug", ["x", "0", "a" * 128, "valid-123-slug"])
def test_seo09_valid_slug_boundaries(tmp_path, slug):
    path = tmp_path / "article.xml"
    path.write_text(f"<article><date>2024-01-01</date><slug>{slug}</slug></article>")
    article = parse_article_xml(path)
    assert article is not None
    assert article.slug == slug


def test_seo09_reproducible_invalid_slug_fuzz(tmp_path):
    rng = random.Random(9)
    path = tmp_path / "article.xml"
    values = ["", "../x", "/etc", "a/b", "a\\b", "%2f", "UPPER", "-x", "x-", "a--b", "a" * 129]
    values.extend("safe" + rng.choice("./%\\_é ") + str(rng.randrange(1000)) for _ in range(40))
    for value in values:
        path.write_text(f"<article><title>Valid</title><date>2024-01-01</date><slug>{escape(value)}</slug></article>")
        assert parse_article_xml(path) is None


@pytest.mark.parametrize("extra", ["<slug>one</slug><slug>two</slug>", "<slug>one<child/></slug>"])
def test_seo09_duplicate_and_nested_slugs_rejected(tmp_path, extra):
    path = tmp_path / "article.xml"
    path.write_text(f"<article><title>Valid</title><date>2024-01-01</date>{extra}</article>")
    assert parse_article_xml(path) is None


@pytest.mark.parametrize("slug", ["collision", "1", "a" * 128])
def test_seo09_slug_collisions_fail_before_publication(site_root, seo_config, slug):
    cli, config = seo_config
    for source in (site_root / "content/en").glob("*.xml"):
        source.write_text(source.read_text().replace("</article>", f"<slug>{slug}</slug></article>"))
    with pytest.raises(ValueError, match="Duplicate generated"):
        run_build(cli, config, site_root)
    assert not (site_root / "output").exists()
