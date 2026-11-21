"""REVIEW28-07: projection selection preserves canonical route uniqueness."""
import pytest

from articulous.ownership import ownership_path
from articulous.pipeline import run_build


def _installed_files(root):
    output = root / 'output'
    files = [root / '.build-cache.json', ownership_path(output)]
    files.extend(path for path in output.rglob('*') if path.is_file())
    return {path.relative_to(root): path.read_bytes() for path in files}


@pytest.mark.parametrize('sections', [('rss', 'sitemap', 'search'), ('index', 'tags')])
def test_review28_07_filtered_article_collision_preserves_installed_site(site_root, seo_config, sections):
    cli, config = seo_config
    run_build(cli, config, site_root)
    installed = _installed_files(site_root)
    original = site_root / 'content/en/first-post.xml'
    original.with_name('duplicate.xml').write_bytes(original.read_bytes())
    cli.only_sections = sections
    with pytest.raises(ValueError, match='Duplicate generated'):
        run_build(cli, config, site_root)
    assert _installed_files(site_root) == installed


@pytest.mark.parametrize('labels', [('News', 'news'), ('a+b', 'a-b'), ('X', 'x!')])
def test_review28_07_sitemap_only_checks_distinct_tag_labels(site_root, seo_config, labels):
    cli, config = seo_config
    cli.only_sections = ['sitemap']
    config['sitemap']['include_listings'] = True
    for source, label in zip(sorted((site_root / 'content/en').glob('*.xml')), labels, strict=True):
        source.write_text(source.read_text().replace('<tag>news</tag>', f'<tag>{label}</tag>'))
    with pytest.raises(ValueError, match='Duplicate generated'):
        run_build(cli, config, site_root)
    assert not (site_root / 'output').exists()


def test_review28_07_actual_tag_and_article_routes_collide_across_sections(site_root, seo_config):
    cli, config = seo_config
    cli.only_sections = ['sitemap']
    config['sitemap']['include_listings'] = True
    config['urls']['tag'] = '/{lang}/articles/{tag}'
    first = site_root / 'content/en/first-post.xml'
    first.write_text(first.read_text().replace('<tag>news</tag>', '<tag>second-post</tag>'))
    with pytest.raises(ValueError, match='Duplicate generated'):
        run_build(cli, config, site_root)


def test_review28_07_paginated_tags_count_distinct_article_memberships(site_root, seo_config):
    cli, config = seo_config
    cli.only_sections = ['sitemap']
    config['sitemap']['include_listings'] = True
    config['site']['pagination'].update(per_page=1, paginate_tags=True)
    config['urls']['article'] = '/{lang}/tags/news/page/{slug}/'
    first = site_root / 'content/en/first-post.xml'
    original = first.read_text().replace('</article>', '<slug>2</slug></article>')
    first.write_text(original.replace('<tag>news</tag>', '<tag>intro</tag>'))
    run_build(cli, config, site_root)
    first.write_text(original)
    with pytest.raises(ValueError, match='Duplicate generated'):
        run_build(cli, config, site_root)


def test_review28_07_rss_ignores_tag_routes_and_unlisted_twins(site_root, seo_config):
    cli, config = seo_config
    cli.only_sections = ['rss']
    first = site_root / 'content/en/first-post.xml'
    content = first.read_text().replace('</article>', '<tag>NEWS</tag></article>')
    first.write_text(content)
    first.with_name('unlisted.xml').write_text(content.replace('</article>', '<status>unlisted</status></article>'))
    run_build(cli, config, site_root)
    feed = (site_root / 'output/rss.xml').read_text()
    assert feed.count('<title>First Post</title>') == 1


def test_review28_07_selected_listing_language_excludes_other_languages(site_root, seo_config):
    cli, config = seo_config
    run_build(cli, config, site_root)
    first = site_root / 'content/en/first-post.xml'
    first.with_name('duplicate.xml').write_bytes(first.read_bytes())
    cli.only_langs = ['fr']
    cli.only_sections = ['index', 'tags']
    run_build(cli, config, site_root)


def test_review28_07_full_manifest_avoids_extra_route_store(site_root, seo_config, monkeypatch):
    from articulous import projection_routes
    cli, config = seo_config
    from unittest.mock import Mock
    sqlite = Mock()
    monkeypatch.setattr(projection_routes, 'sqlite3', sqlite)
    run_build(cli, config, site_root)
    sqlite.connect.assert_not_called()


def test_review28_07_distinct_article_ids_can_format_to_one_url(site_root, seo_config):
    cli, config = seo_config
    cli.only_sections = ['search']
    config['site']['languages'] = ['en', 'eng']
    config['urls']['article'] = '/posts/{lang}{slug}/'
    first = site_root / 'content/en/first-post.xml'
    first.write_text(first.read_text().replace('</article>', '<slug>ga</slug></article>'))
    other = site_root / 'content/fr/premier.xml'
    other.write_text(other.read_text().replace('<lang>fr</lang>', '<lang>eng</lang>').replace('</article>', '<slug>a</slug></article>'))
    with pytest.raises(ValueError, match='Duplicate generated.*posts/enga/'):
        run_build(cli, config, site_root)


def test_review28_07_partial_build_preserves_selected_unlisted_article_ownership(site_root, seo_config):
    cli, config = seo_config
    first = site_root / 'content/en/first-post.xml'
    first.write_text(first.read_text().replace('</article>', '<status>unlisted</status></article>'))
    run_build(cli, config, site_root)
    first.with_name('duplicate.xml').write_bytes(first.read_bytes())
    cli.only_slugs = ['first-post']
    cli.only_sections = ['articles', 'index']
    with pytest.raises(ValueError, match='Duplicate generated'):
        run_build(cli, config, site_root)
