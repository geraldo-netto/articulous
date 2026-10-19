"""ARCH-006: composition shares captured bytes, routes and lifecycle ownership."""
from datetime import datetime, timedelta, timezone

import pytest

from articulous.builds import check_build, prepare_build, render_prepared
from articulous.extensions import BuildComposition, TemplateInput
from articulous.composition import ExtraPage, Route
from articulous.engines import LxmlEngine, StylesheetCapture


STYLE = b'''<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">
<xsl:include href="../generated.xsl"/><xsl:template match="/">
<html><body><xsl:value-of select="$title"/></body></html></xsl:template></xsl:stylesheet>'''


def test_arch006_single_snapshot_and_route_aware_template_capture(site_root, seo_config):
    cli, config = seo_config
    saved = []
    def compose(snapshot):
        saved.append(snapshot)
        assert len(list(snapshot.articles("en"))) == 2
        first = next(article for article in snapshot.articles('en') if article.slug == 'first-post')
        route = Route('page:extra', 'pages', config['site']['base_url'] + '/extra/', 'extra/index.html', category='static')
        page = ExtraPage(route, b'<extra/>', site_root / 'xsl/pages/extra.xsl')
        def templates(current, routes):
            assert current is snapshot
            assert any(route.key == 'page:extra' for route in routes)
            assert list(snapshot.articles())
            content = ('<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">'
                       '<xsl:variable name="title">' + first.title + '</xsl:variable></xsl:stylesheet>').encode()
            return (TemplateInput('generated.xsl', content), TemplateInput('pages/extra.xsl', STYLE))
        return BuildComposition((page,), templates)
    with prepare_build(cli, config, site_root, composer=compose) as prepared:
        (site_root / 'content/en/first-post.xml').write_text('<broken')
        staged = render_prepared(prepared)
        with staged.open_artifact('extra/index.html') as artifact:
            assert b'First Post' in artifact.read()
        assert not (site_root / 'xsl/generated.xsl').exists()
    with pytest.raises(ValueError, match='closed'):
        next(saved[0].articles())


def test_arch006_snapshot_all_states_clock_and_reader_cutoff(site_root, seo_config):
    cli, config = seo_config
    path = site_root / 'content/en/first-post.xml'
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    path.write_text(path.read_text().replace('</article>', f'<status>scheduled</status><publish-at>{future}</publish-at></article>'))
    snapshots = []
    readers = []
    def compose(snapshot):
        snapshots.append(snapshot)
        readers.append(snapshot.articles('en'))
        assert next(readers[0]).slug == 'second-post'
        assert next(readers[0]).policy.page is False
        with pytest.raises(ValueError, match='disabled'):
            list(snapshot.articles('disabled'))
        return BuildComposition()
    assert check_build(cli, config, site_root, composer=compose).routes > 0
    with pytest.raises(ValueError, match='closed'):
        next(readers[0])
    assert snapshots[0].captured_at.tzinfo is not None


@pytest.mark.parametrize('composer', [42, lambda _: None])
def test_arch006_invalid_composition_preserves_output(site_root, seo_config, composer):
    cli, config = seo_config
    with pytest.raises(ValueError):
        check_build(cli, config, site_root, composer=composer)
    assert not (site_root / 'output').exists()
    assert not list(site_root.glob('.articulous-stage-*'))


@pytest.mark.parametrize('path', ['', '../escape', '/absolute', 'a//b', 'a\\b'])
def test_arch006_template_input_boundaries(path):
    with pytest.raises(ValueError):
        TemplateInput(path, b'content')


def test_arch006_invalid_contracts_and_duplicate_inputs(site_root, seo_config):
    assert TemplateInput('assets/functions.xsl', b'<sheet/>').path == 'assets/functions.xsl'
    cli, config = seo_config
    item = TemplateInput('generated.xsl', b'<ignored/>')
    def compose(snapshot):
        return BuildComposition(templates=lambda *_: (item, item))
    with pytest.raises(ValueError, match='unique'):
        check_build(cli, config, site_root, composer=compose)


def test_arch006_deferred_engines_enforce_capture_phase(tmp_path):
    capture = StylesheetCapture()
    engine = capture.wrap(LxmlEngine())
    path = tmp_path / 'source.xsl'
    path.write_bytes(b'<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0"/>')
    engine.prepare_stylesheet(path)
    with pytest.raises(ValueError, match='not frozen'):
        engine.resolve_stylesheet_fingerprint(path, '')
    capture.freeze()
    with pytest.raises(ValueError, match='frozen'):
        engine.prepare_stylesheet(path)


def test_arch006_invalid_source_policy_and_capture_failure(site_root, seo_config, monkeypatch):
    from articulous import capture_adapter
    cli, config = seo_config
    (site_root / 'content/en/broken.xml').write_text('<broken')
    def reject(snapshot):
        assert snapshot.invalid_articles == 1
        raise ValueError('source policy rejects invalid articles')
    with pytest.raises(ValueError, match='source policy'):
        check_build(cli, config, site_root, composer=reject)
    def failed_factory(*args):
        raise OSError('capture failed')
    monkeypatch.setattr(capture_adapter, '_article_stream_factory', failed_factory)
    with pytest.raises(OSError, match='capture failed'):
        check_build(cli, config, site_root, composer=lambda _: BuildComposition())
    assert not list(site_root.glob('.articulous-stage-*'))


def test_arch006_template_symlink_target_is_preserved(site_root, seo_config):
    cli, config = seo_config
    manual = site_root / 'manual'
    manual.write_bytes(b'keep')
    (site_root / 'xsl/generated.xsl').symlink_to(manual)
    def compose(snapshot):
        return BuildComposition(templates=lambda *_: (TemplateInput('generated.xsl', b'overwrite'),))
    with pytest.raises(ValueError, match='symlink'):
        check_build(cli, config, site_root, composer=compose)
    assert manual.read_bytes() == b'keep'


@pytest.mark.parametrize('contract,fields', [
    (TemplateInput, {'path': 'good.xsl', 'content': 'not bytes'}),
    (BuildComposition, {'pages': []}),
    (BuildComposition, {'pages': ('bad',)}),
    (BuildComposition, {'templates': 42}),
])
def test_arch006_invalid_public_contracts(contract, fields):
    with pytest.raises(ValueError):
        contract(**fields)


@pytest.mark.parametrize('templates', [lambda *_: ['bad']])
def test_arch006_invalid_template_factory_result(site_root, seo_config, templates):
    cli, config = seo_config
    def compose(snapshot):
        return BuildComposition(templates=templates)
    with pytest.raises(ValueError, match='TemplateInput'):
        check_build(cli, config, site_root, composer=compose)


def test_arch006_external_stylesheet_is_captured_without_relocation(site_root, seo_config):
    cli, config = seo_config
    stylesheet = site_root / 'external.xsl'
    stylesheet.write_bytes(STYLE.replace(b'<xsl:include href="../generated.xsl"/>', b'').replace(b'<xsl:value-of select="$title"/>', b'Captured external resource'))
    route = Route('page:external', 'pages', config['site']['base_url'] + '/external/', 'external/index.html')
    def compose(snapshot):
        return BuildComposition((ExtraPage(route, b'<external/>', stylesheet),))
    with prepare_build(cli, config, site_root, composer=compose) as prepared:
        stylesheet.write_bytes(b'<broken')
        with render_prepared(prepared).open_artifact('external/index.html') as artifact:
            assert b'Captured external resource' in artifact.read()


def test_arch009_readonly_source_capture_needs_no_render_or_publication(site_root, seo_config):
    from articulous.builds import capture_site
    cli, config = seo_config
    with capture_site(cli, config, site_root) as snapshot:
        rows = list(snapshot.articles())
        assert rows
        assert rows[0].source_xml in {path.read_bytes() for path in (site_root / 'content').rglob('*.xml')}
    assert not (site_root / 'output').exists()
    assert not (site_root / '.build-cache.json').exists()
    with pytest.raises(ValueError, match='closed'):
        list(snapshot.articles())
