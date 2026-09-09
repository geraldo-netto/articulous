"""SEO-02: reference HTML has useful, self-consistent search metadata."""
import lxml.etree as etree
import pytest

from articulous.pipeline import run_build


@pytest.mark.parametrize("base", ["https://example.test/blog", "http://example.test", "", "/blog"])
def test_seo02_all_pages_have_language_title_and_self_canonical(site_root, seo_config, base):
    cli, config = seo_config
    cli.only_sections = {"articles", "index", "tags"}
    config["site"]["base_url"] = base
    config["site"]["pagination"]["per_page"] = 1
    config["urls"].update(article="/posts/{lang}/{slug}/", index="/{lang}/archive/{page}/", tag="/{lang}/topics/{tag}/")
    run_build(cli, config, site_root)
    output = site_root / "output"
    pages = list(output.rglob("*.html"))
    assert len(pages) >= 8
    for page in pages:
        root = etree.HTML(page.read_bytes())
        assert root.get("lang") in {"en", "fr"}
        assert root.xpath("string(head/title)").strip()
        expected = [base + "/" + page.relative_to(output).as_posix().removesuffix("index.html")] if base.startswith("http") else []
        assert root.xpath("head/link[@rel='canonical']/@href") == expected


@pytest.mark.parametrize("description", ["Inaugural article.", ""])
def test_seo02_description_omitted_when_unavailable(site_root, seo_config, description):
    cli, config = seo_config
    source = site_root / "content/en/first-post.xml"
    source.write_text(source.read_text().replace("Inaugural article.", description))
    run_build(cli, config, site_root)
    root = etree.HTML((site_root / "output/en/articles/first-post/index.html").read_bytes())
    assert root.xpath("head/meta[@name='description']/@content") == ([description] if description else [])
    assert "First Post" in root.xpath("string(head/title)")
    assert config["site"]["site_name"] in root.xpath("string(head/title)")
