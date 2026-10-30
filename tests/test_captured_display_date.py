"""BUILD-039: captured optional display dates preserve source text once parsed."""
import pytest
from articulous.articles import parse_article_xml
from articulous.builds import capture_site


@pytest.mark.parametrize('field,expected', [
    ('', ''), ('<display-date/>', ''),
    ('<display-date> 30 ottobre — café </display-date>', ' 30 ottobre — café '),
    ('<display-date>first</display-date><display-date>second</display-date>', 'first'),
    ('<display-date><![CDATA[<literal> & text]]></display-date>', '<literal> & text'),
])
def test_build039_native_and_captured_display_date(site_root, seo_config, field, expected):
    path = site_root / 'content/en/first-post.xml'
    path.write_text(path.read_text().replace('</article>', field + '</article>'))
    source = path.read_bytes()
    article = parse_article_xml(path)
    assert article.display_date == expected
    assert article.source_xml == source
    cli, config = seo_config
    with capture_site(cli, config, site_root) as snapshot:
        path.write_text('<changed/>')
        captured = next(item for item in snapshot.articles('en') if item.slug == 'first-post')
        assert captured.display_date == expected
        assert captured.source_xml == source
