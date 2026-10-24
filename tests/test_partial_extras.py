"""API-005: explicitly declared extras participate in partial-build ownership."""
from dataclasses import replace

import pytest

from articulous.composition import ExtraArtifact
from articulous.pipeline import run_build
from test_composition import page
from test_prepared_build import snapshot


@pytest.mark.parametrize('selection,values', [
    ('only_sections', ['rss']), ('only_langs', ['en']), ('only_slugs', ['first-post']),
])
@pytest.mark.parametrize('kind', ['page', 'artifact'])
def test_api005_resupplied_extras_are_selected(site_root, seo_config, selection, values, kind):
    cli, config = seo_config
    options = api005_inputs(config, kind, b'First')
    run_build(cli, config, site_root, **options)
    setattr(cli, selection, values)
    run_build(cli, config, site_root, **options)
    options = api005_inputs(config, kind, b'Updated')
    run_build(cli, config, site_root, **options)
    path = 'about/index.html' if kind == 'page' else 'report.txt'
    assert b'Updated' in (site_root / 'output' / path).read_bytes()


def api005_inputs(config, kind, content):
    if kind == 'artifact':
        return {'extra_artifacts': [ExtraArtifact('report.txt', content)]}
    model = b'<index lang="en" page="1" total="1"><article><title>' + content
    model += b'</title><url>/target/</url></article></index>'
    return {'extra_pages': [replace(page(config), model=model)]}


def test_api005_moved_extra_retires_selected_old_path(site_root, seo_config):
    cli, config = seo_config
    original = page(config)
    run_build(cli, config, site_root, extra_pages=[original])
    cli.only_sections = ['rss']
    moved = replace(original, route=replace(original.route, output_path='moved/index.html',
                                           url=config['site']['base_url'] + '/moved/'))
    run_build(cli, config, site_root, extra_pages=[moved])
    assert not (site_root / 'output/about').exists()
    assert (site_root / 'output/moved/index.html').is_file()


def test_api005_unselected_owner_still_blocks_collision(site_root, seo_config):
    cli, config = seo_config
    original = page(config)
    run_build(cli, config, site_root, extra_pages=[original])
    cli.only_sections = ['rss']
    other = replace(original, route=replace(original.route, key='page:other'))
    previous = snapshot(site_root / 'output')
    with pytest.raises(ValueError, match='Duplicate generated output'):
        run_build(cli, config, site_root, extra_pages=[other])
    assert snapshot(site_root / 'output') == previous


def test_api005_dry_selected_extra_preserves_generation(site_root, seo_config):
    cli, config = seo_config
    run_build(cli, config, site_root, **api005_inputs(config, 'artifact', b'First'))
    cli.only_sections = ['rss']
    cli.dry_run = True
    previous = snapshot(site_root / 'output')
    cache = (site_root / '.build-cache.json').read_bytes()
    run_build(cli, config, site_root, **api005_inputs(config, 'artifact', b'Updated'))
    assert snapshot(site_root / 'output') == previous
    assert (site_root / '.build-cache.json').read_bytes() == cache
