"""SEO-03: crawlable pagination follows configured routes and boundaries."""
import lxml.etree as etree
import pytest

from articulous.pipeline import run_build


@pytest.mark.parametrize("per_page", [1, 2, 3, 100])
def test_seo03_all_index_pages_reachable_from_first(site_root, seo_config, per_page):
    cli, config = seo_config
    source = site_root / "content/en/first-post.xml"
    source.with_name("third.xml").write_text(source.read_text().replace("First Post", "Third Post"))
    config["site"]["pagination"]["per_page"] = per_page
    config["site"]["base_url"] = "https://example.test/blog"
    config["urls"]["index"] = "/{lang}/archive/part-{page}/"
    run_build(cli, config, site_root)
    count = (3 + per_page - 1) // per_page
    expected = [f"https://example.test/blog/en/archive/part-{page}/" for page in range(1, count + 1)]
    reached = []
    current = expected[0]
    while current:
        assert current not in reached
        reached.append(current)
        relative = current.removeprefix("https://example.test/blog/")
        root = etree.HTML((site_root / "output" / relative / "index.html").read_bytes())
        previous = reached[-2:-1]
        assert root.xpath("//a[@rel='prev']/@href") == previous
        following = root.xpath("//a[@rel='next']/@href")
        current = following[0] if following else ""
    assert reached == expected
