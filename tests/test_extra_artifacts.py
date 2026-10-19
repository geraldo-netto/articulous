"""ARCH-007: auxiliary bytes share the normal ownership/publication lifecycle."""

import pytest

from articulous.builds import check_build, prepare_build, render_prepared, validate_generated
from articulous.composition import ExtraArtifact
from articulous.extensions import BuildComposition
from articulous.pipeline import run_build
from articulous.publication import build_site


@pytest.mark.parametrize('path', ['', '../escape', '/absolute', 'assets/escape', 'a//b', 'a\\b'])
def test_arch007_unsafe_artifact_paths(path):
    with pytest.raises(ValueError):
        ExtraArtifact(path, b'bytes')


@pytest.mark.parametrize('values', [['bad'], [42]])
def test_arch007_invalid_artifacts_rejected_before_output(site_root, seo_config, values):
    cli, config = seo_config
    with pytest.raises(ValueError, match='ExtraArtifact'):
        check_build(cli, config, site_root, extra_artifacts=values)
    assert not (site_root / 'output').exists()


@pytest.mark.parametrize('content', ['text', None, bytearray(b'mutable')])
def test_arch007_content_is_immutable(content):
    with pytest.raises(ValueError, match='bytes'):
        ExtraArtifact('report.json', content)


def test_arch007_published_artifacts_cache_retirement_and_check_only(site_root, seo_config):
    cli, config = seo_config
    artifact = ExtraArtifact('.htaccess', b'caller-owned server requirements\n')
    build_site(cli, config, site_root, extra_artifacts=[artifact])
    root = site_root / 'output'
    assert (root / '.htaccess').read_bytes() == artifact.content
    cache = (site_root / '.build-cache.json').read_bytes()
    run_build(cli, config, site_root, extra_artifacts=[artifact])
    assert (site_root / '.build-cache.json').read_bytes() == cache
    check_build(cli, config, site_root, extra_artifacts=[ExtraArtifact('.htaccess', b'not published')])
    assert (root / '.htaccess').read_bytes() == artifact.content
    build_site(cli, config, site_root)
    assert not (root / '.htaccess').exists()


@pytest.mark.parametrize('artifacts', [
    [ExtraArtifact('sitemap.xml', b'collision')],
    [ExtraArtifact('report', b'one'), ExtraArtifact('report/child', b'two')],
    [ExtraArtifact('report', b'one'), ExtraArtifact('report', b'two')],
])
def test_arch007_collisions_preserve_prior_generation(site_root, seo_config, artifacts):
    cli, config = seo_config
    build_site(cli, config, site_root)
    previous = (site_root / 'output/search.json').read_bytes()
    with pytest.raises(ValueError, match='Duplicate'):
        build_site(cli, config, site_root, extra_artifacts=artifacts)
    assert (site_root / 'output/search.json').read_bytes() == previous


def test_arch007_route_aware_artifacts_precede_template_capture(site_root, seo_config):
    cli, config = seo_config
    def artifacts(snapshot, routes):
        count = len(list(routes))
        assert list(snapshot.articles())
        return (ExtraArtifact('report.txt', str(count).encode()),)
    def templates(snapshot, routes):
        assert any(route.section == 'artifacts' and not route.sitemap for route in routes)
        return ()
    def compose(snapshot):
        return BuildComposition(artifacts=artifacts, templates=templates)
    with prepare_build(cli, config, site_root, composer=compose) as prepared:
        staged = render_prepared(prepared)
        with staged.open_artifact('report.txt') as artifact:
            assert int(artifact.read()) == len(prepared.routes) - 1
        assert b'report.txt' not in (staged.root / 'sitemap.xml').read_bytes()
        validate_generated(staged)


@pytest.mark.parametrize('factory', [42, 'bad'])
def test_arch007_invalid_factory_contract(factory):
    with pytest.raises(ValueError, match='artifacts'):
        BuildComposition(artifacts=factory)
