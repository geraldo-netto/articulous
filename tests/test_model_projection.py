"""PERF-018/023: model projections follow preparation and remain caller-owned."""
import pytest
import hashlib
from articulous.builds import prepare_build, render_prepared
from articulous.extensions import BuildComposition, TemplateInput
from articulous.composition_contracts import ExtraPage, Route
from articulous import extensions

STYLE = b'''<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">
<xsl:template match="/"><html><body><xsl:value-of select="extra/@value"/></body></html></xsl:template>
</xsl:stylesheet>'''


def test_perf018_projection_runs_after_factories_on_captured_bytes(site_root, seo_config):
    cli, config = seo_config
    ready = []
    inputs = []
    route = Route('page:projected', 'pages', config['site']['base_url'] + '/projected/',
                  'projected/index.html', category='static')

    def templates(snapshot, routes):
        ready.append(True)
        return (TemplateInput('pages/projected.xsl', STYLE),)

    def project(model):
        assert ready
        inputs.append(model)
        with pytest.raises(TypeError):
            model.parameters['changed'] = 'forbidden'
        return b'<extra value="projected"/>' if model.output_path == 'projected/index.html' else model.source

    def compose(snapshot):
        page = ExtraPage(route, b'<extra value="original"/>', site_root / 'xsl/pages/projected.xsl')
        return BuildComposition((page,), templates, project_model=project)

    with prepare_build(cli, config, site_root, composer=compose) as prepared:
        (site_root / 'content/en/first-post.xml').write_text('<changed/>')
        staged = render_prepared(prepared)
        with staged.open_artifact(route.output_path) as stream:
            assert b'projected' in stream.read()
    article = next(model for model in inputs if model.parameters.get('articulous-title') == 'First Post')
    assert b'First Post' in article.source
    assert b'<changed/>' not in article.source


@pytest.mark.parametrize('value', [None, 'not bytes', 42, b'<broken'])
def test_perf018_invalid_projection_preserves_prior_output(site_root, seo_config, value):
    cli, config = seo_config
    output = site_root / 'output'
    output.mkdir(exist_ok=True)
    prior = output / 'manual.txt'
    prior.write_bytes(b'prior')
    def project(model):
        return value
    def compose(snapshot):
        return BuildComposition(project_model=project)
    with pytest.raises((ValueError, RuntimeError, ExceptionGroup)) as failure:
        with prepare_build(cli, config, site_root, composer=compose) as prepared:
            render_prepared(prepared)
    assert_projection_failure(failure.value)
    assert prior.read_bytes() == b'prior'
    assert not list(site_root.glob('.articulous-stage-*'))


def assert_projection_failure(error):
    if isinstance(error, ExceptionGroup):
        for child in error.exceptions:
            assert_projection_failure(child)
    else:
        assert isinstance(error, (ValueError, RuntimeError))


def test_perf018_projection_contract_owns_immutable_parameters():
    params = {'key': 'before'}
    value = extensions.ModelInput(b'<root/>', 'index.html', params)
    params['key'] = 'after'
    assert value.parameters['key'] == 'before'
    with pytest.raises(TypeError):
        value.parameters['key'] = 'changed'
    with pytest.raises(ValueError):
        BuildComposition(project_model=42)


@pytest.mark.parametrize('source,path,parameters', [
    ('xml', 'index.html', {}), (b'', 'index.html', {}),
    (b'<x/>', '../outside', {}), (b'<x/>', '/absolute', {}),
    (b'<x/>', 'index.html', []), (b'<x/>', 'index.html', {1: 'value'}),
    (b'<x/>', 'index.html', {'key': 1}),
])
def test_perf018_invalid_model_inputs_reject(source, path, parameters):
    with pytest.raises(ValueError):
        extensions.ModelInput(source, path, parameters)


def test_perf018_projected_bytes_own_cache_identity(tmp_path):
    from articulous.engines import LxmlEngine, stylesheet_hash
    from articulous.pipeline import BuildCtx, _make_xslt_task
    output = tmp_path / 'output'
    output.mkdir()
    target = output / 'index.html'
    target.write_text('old output')
    style = tmp_path / 'page.xsl'
    style.write_bytes(STYLE)
    engine = LxmlEngine()
    original = b'<extra value="original"/>'
    projected = [b'<extra value="first"/>']
    def project(model):
        return projected[0]
    context = BuildCtx(tmp_path, tmp_path, output, tmp_path / 'assets', model_projection=project)
    style_hash = stylesheet_hash(style)
    cache = {'page': [hashlib.sha256(original).hexdigest(), style_hash, engine.cache_identity, 'index.html']}
    for value in (b'<extra value="first"/>', b'<extra value="second"/>'):
        projected[0] = value
        task = _make_xslt_task(xml_input=original, xsl_path=style, xsl_hash=style_hash,
                               output_path=target, cache=cache, cache_key='page', engine=engine, ctx=context)
        assert task is not None
        task()
        assert cache['page'][0] == hashlib.sha256(value).hexdigest()
    assert 'second' in target.read_text()


def test_perf018_projection_cancellation_cleans_owned_preparation(site_root, seo_config):
    cli, config = seo_config
    def project(model):
        raise KeyboardInterrupt
    def compose(snapshot):
        return BuildComposition(project_model=project)
    with pytest.raises(KeyboardInterrupt):
        with prepare_build(cli, config, site_root, composer=compose) as prepared:
            render_prepared(prepared)
    assert not list(site_root.glob('.articulous-stage-*'))


def test_perf018_streamed_artifacts_bypass_presentation_projection(tmp_path):
    from articulous.engines import LxmlEngine, stylesheet_hash
    from articulous.pipeline import BuildCtx, _make_xslt_task
    style = tmp_path / 'page.xsl'
    style.write_bytes(STYLE)
    source = tmp_path / 'stream.xml'
    source.write_bytes(b'<extra value="streamed"/>')
    output = tmp_path / 'output'
    output.mkdir()
    def project(model):
        pytest.fail('Streamed artifact must retain its native file input')
    context = BuildCtx(tmp_path, tmp_path, output, tmp_path / 'assets', model_projection=project)
    task = _make_xslt_task(xml_input=source, xsl_path=style, xsl_hash=stylesheet_hash(style),
                           output_path=output / 'index.html', cache={}, cache_key='stream',
                           engine=LxmlEngine(), ctx=context)
    task()
    assert 'streamed' in (output / 'index.html').read_text()
