"""API-002: independent engine interfaces, errors and captured dispatch."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from articulous.engines import LxmlEngine, StylesheetCapture
from articulous.filesystem import atomic_output
from articulous.pipeline import _make_xslt_task, _resolve_parallelism, _section_runtime, build_ctx_from_config


def test_api002_contract_import_needs_no_engine_or_native_modules():
    script = '''
import sys
sys.modules['lxml'] = None
sys.modules['fcntl'] = None
from articulous.transform_contracts import TransformEngine, TransformFailure, ExecutionCapabilities
assert 'articulous.engines' not in sys.modules
assert 'articulous.filesystem' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


class IndependentEngine:
    name = 'independent'
    cache_identity = 'independent:v1'

    def __init__(self, capabilities):
        self.capabilities = capabilities
        self.calls = 0

    def prepare_stylesheet(self, path):
        return 'independent-stylesheet-v1'

    def resolve_stylesheet_fingerprint(self, path, fingerprint):
        return fingerprint

    def run(self, xml_input, xsl_path, output_path, dry_run=False,
            stylesheet_fingerprint=None, xml_base_uri=None, parameters=None):
        if dry_run:
            return
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_output(output_path, generated=True) as staged:
            staged.write_bytes(b'neutral output')
        self.calls += 1


@pytest.mark.parametrize('external', [False, True])
def test_api002_structural_engine_runs_captured_pipeline(site_root, seo_config, monkeypatch, external):
    from articulous.transform_contracts import ExecutionCapabilities
    _, config = seo_config
    engine = IndependentEngine(ExecutionCapabilities(external))
    capture = StylesheetCapture()
    wrapped = capture.wrap(engine)
    assert wrapped is not engine
    context = replace(build_ctx_from_config(config, False), engines={'articles': wrapped}, parallelism='auto')
    path, revision, selected = _section_runtime(context, 'articles')
    capture.freeze()
    cache = {}
    output = context.output_dir / 'neutral.html'
    task = _make_xslt_task(xml_input=b'<article/>', xsl_path=path, xsl_hash=revision,
                           output_path=output, cache=cache, cache_key='neutral', engine=selected, ctx=context)
    assert task is not None
    task()
    assert output.read_bytes() == b'neutral output'
    assert engine.calls == 1
    assert cache['neutral'][1] == 'independent-stylesheet-v1'
    monkeypatch.setattr('articulous.pipeline.os.cpu_count', lambda: 2)
    assert _resolve_parallelism(context) == (2 if external else 4)


@pytest.mark.parametrize('value', [None, 0, 'engine', {}, object()])
def test_api002_rejects_incomplete_engine_contract(value):
    from articulous.transform_contracts import TransformFailure, require_transform
    with pytest.raises(TransformFailure, match='engine'):
        require_transform(value)


@pytest.mark.parametrize('value', [None, 0, 1, 'true', [], {}])
def test_api002_capability_values_are_boolean(value):
    from articulous.transform_contracts import ExecutionCapabilities
    with pytest.raises(ValueError, match='boolean'):
        ExecutionCapabilities(value)


@pytest.mark.parametrize('value', [None, -1, {}, False])
def test_api002_invalid_inputs_use_independent_errors(tmp_path, value):
    from articulous.transform_contracts import TransformFailure
    output = tmp_path / 'output.xml'
    with pytest.raises(TransformFailure) as failure:
        LxmlEngine().run(value, Path('unused.xsl'), output)
    assert failure.value.operation == 'transform'
    assert failure.value.returncode is None
    assert not output.exists()


@pytest.mark.parametrize('parameters', [[], False, {1: 'text'}, {'': 'text'}, {'name': None}, {'name': 1}])
def test_api002_invalid_parameter_mappings_reject_before_output(tmp_path, parameters):
    from articulous.transform_contracts import TransformFailure
    output = tmp_path / 'output.xml'
    with pytest.raises(TransformFailure, match='parameters'):
        LxmlEngine().run(b'<root/>', Path('unused.xsl'), output, parameters=parameters)
    assert not output.exists()


def test_api002_capture_preserves_provider_failure_identity(tmp_path):
    from articulous.transform_contracts import ExecutionCapabilities, TransformFailure
    failure = TransformFailure('provider', 'failed', 17)
    engine = IndependentEngine(ExecutionCapabilities())
    capture = StylesheetCapture()
    wrapped = capture.wrap(engine)
    wrapped.prepare_stylesheet(tmp_path / 'captured.xsl')
    capture.freeze()
    engine.run = Mock(side_effect=failure)
    with pytest.raises(TransformFailure) as caught:
        wrapped.run(b'<root/>', tmp_path / 'captured.xsl', tmp_path / 'output.xml')
    assert caught.value is failure
    with pytest.raises(TransformFailure, match='not captured'):
        wrapped.resolve_stylesheet_fingerprint(tmp_path / 'unknown.xsl', '')


@pytest.mark.parametrize('invalid', [1, None, 'true'])
def test_api002_invalid_dry_run_uses_contract_error(tmp_path, invalid):
    from articulous.transform_contracts import TransformFailure
    with pytest.raises(TransformFailure, match='boolean'):
        LxmlEngine().run(b'<root/>', Path('unused.xsl'), tmp_path / 'output', dry_run=invalid)


def test_api002_prepare_errors_use_contract_channel(tmp_path):
    from articulous.transform_contracts import TransformFailure
    with pytest.raises(TransformFailure) as failure:
        LxmlEngine().prepare_stylesheet(tmp_path / 'missing.xsl')
    assert failure.value.operation == 'prepare_stylesheet'
