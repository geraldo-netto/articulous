"""CC-005: independent calibration, source scope and fail-closed acceptance."""
from copy import deepcopy
from dataclasses import asdict
import json
import random

from lxml import etree  # type: ignore[attr-defined]
import pytest

from articulous import complexity_xslt as metric
from articulous import complexity_xslt_calibration as controls
from articulous import complexity_xpath as adapter
from articulous.backends import xpath as worker
from articulous.complexity_xslt_contracts import XPathDecisions


def native(expression):
    return adapter.decisions(worker.compile_trace(expression))


@pytest.fixture
def calibration():
    return controls.calibrate(native, metric.measure_source)


def test_cc005_real_native_and_control_calibration(calibration):
    assert controls.check_calibration(calibration) == native('a').compiler_version
    assert calibration['templates'][-1]['actual'] == 9


@pytest.mark.parametrize('fault', ['native', 'template'])
def test_cc005_deliberately_faulty_provider_calibration(fault):
    def incorrect(_):
        return XPathDecisions(0, 0, '20914', 'a' * 64)

    provider = incorrect if fault == 'native' else native
    measure = metric.measure_source if fault == 'native' else lambda *_: [{'complexity': 0}]
    with pytest.raises(ValueError, match='calibration'):
        controls.calibrate(provider, measure)


@pytest.mark.parametrize('fault', ['xpath-missing', 'xpath-actual', 'versions', 'template-missing', 'template-actual'])
def test_cc005_recorded_calibration_faults(calibration, fault):
    if fault == 'xpath-missing':
        calibration['xpath'].pop()
    if fault == 'xpath-actual':
        calibration['xpath'][0]['actual'] = [1, 0]
    if fault == 'versions':
        calibration['xpath'][0]['version'] = '99999'
    if fault == 'template-missing':
        calibration['templates'].pop()
    if fault == 'template-actual':
        calibration['templates'][0]['actual'] = 0
    with pytest.raises(ValueError):
        controls.check_calibration(calibration)


@pytest.mark.parametrize('source,expected', [
    ('text', []), ('{{literal}}', []), ('{a} {b}', ['a', 'b']),
    ('''{contains('}', '{')}''', ["contains('}', '{')"]),
    ('{contains("}", "{")}', ['contains("}", "{")']), ('{{{a}}}', ['a']),
])
def test_cc005_avt_quote_and_escape_boundaries(source, expected):
    assert metric.avt_expressions(source) == expected


@pytest.mark.parametrize('source', ['{', '}', '{a', 'a}', '{"unterminated}', '{a{b}}'])
def test_cc005_avt_invalid_boundaries(source):
    with pytest.raises(ValueError, match='attribute value'):
        metric.avt_expressions(source)


def test_cc005_avt_capacity_boundary(monkeypatch):
    monkeypatch.setattr(metric, 'MAX_AVT_EXPRESSIONS', 2)
    assert metric.avt_expressions('{a}{b}') == ['a', 'b']
    with pytest.raises(ValueError, match='capacity'):
        metric.avt_expressions('{a}{b}{c}')


@pytest.mark.parametrize('body', [
    '<xsl:iterate select="a"/>', '<xsl:if test="a" use-when="false()"/>',
    '<out xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xsl:version="2.0"/>',
    '<xsl:if test="a" extension-element-prefixes="ext"/>',
    '<out xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xsl:extension-element-prefixes="ext"/>',
])
def test_cc005_unsupported_instruction_boundaries(body):
    with pytest.raises(ValueError, match='unsupported|Unsupported'):
        metric.measure_source(controls.stylesheet(body), native)


@pytest.mark.parametrize('source', [
    b'<out/>', b'<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="2.0"/>',
    b'<!DOCTYPE xsl:stylesheet><xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0"/>',
    b'<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0"><xsl:variable name="v" select="true()"/></xsl:stylesheet>',
])
def test_cc005_unsupported_root_and_global_scope(source):
    with pytest.raises(ValueError):
        metric.parse_stylesheet(source)


def test_cc005_stylesheet_capacity_and_comments(monkeypatch):
    source = controls.stylesheet('<!-- ignored --><?probe text?><out/>')
    monkeypatch.setattr(metric, 'MAX_STYLESHEET_BYTES', len(source))
    assert metric.measure_source(source, native)[0]['complexity'] == 1
    with pytest.raises(ValueError, match='capacity'):
        metric.parse_stylesheet(source + b' ')


@pytest.mark.parametrize('source', [None, 1, '<out/>', bytearray(b'<out/>')])
def test_cc005_immutable_source_admission(source):
    with pytest.raises(ValueError, match='capacity'):
        metric.parse_stylesheet(source)


def test_cc005_match_select_avt_and_sort_scopes():
    body = '''<xsl:for-each select="a[b]">
<xsl:sort select="c[d]" order="{'ascending'}"/>
<out value="{e[f]}"/><xsl:value-of select="g"/></xsl:for-each>'''
    source = controls.stylesheet(body).replace(b'match="/"', b'match="a[b]"')
    result = metric.measure_source(source, native)[0]
    assert result['complexity'] == 6
    assert {row['attribute'] for row in result['expressions']} == {'match', 'select', 'order', 'value'}


def test_cc005_literal_attribute_names_do_not_enable_extensions():
    result = metric.measure_source(controls.stylesheet('<out extension-element-prefixes="literal"/>'), native)
    assert result[0]['complexity'] == 1


def test_cc005_named_template_without_xpath_is_accepted(tmp_path):
    path = tmp_path / metric.DIRECTORY / 'empty.xsl'
    path.parent.mkdir(parents=True)
    path.write_bytes(controls.stylesheet('<out/>').replace(b'match="/"', b'name="empty"'))
    report = metric.measured_report(tmp_path, native)
    assert metric.check_report(tmp_path, report) == 1


@pytest.fixture
def evidence(tmp_path):
    path = tmp_path / metric.DIRECTORY / 'simple.xsl'
    path.parent.mkdir(parents=True)
    path.write_bytes(controls.stylesheet('<xsl:if test="a and b"/>'))
    return tmp_path, metric.measured_report(tmp_path, native)


def test_cc005_source_bound_acceptance(evidence):
    root, report = evidence
    assert metric.check_report(root, report) == 1
    path = root / report['files'][0]['path']
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='Stale'):
        metric.check_report(root, report)


@pytest.mark.parametrize('fault', ['schema', 'metric', 'inventory', 'template', 'complexity', 'compiler-version', 'expression'])
def test_cc005_source_report_fault_controls(evidence, fault):
    root, report = evidence
    entry = report['files'][0]
    mutations = {
        'schema': lambda: report.update(schema=2), 'metric': lambda: report.update(metric='other'),
        'inventory': lambda: report['files'].append(deepcopy(entry)),
        'template': lambda: entry.update(templates=[]),
        'complexity': lambda: entry['templates'][0].update(complexity=1),
        'compiler-version': lambda: entry['templates'][0]['expressions'][0].update(compiler_version='99999'),
        'expression': lambda: entry['templates'][0]['expressions'][1].update(source='a'),
    }
    mutations[fault]()
    with pytest.raises((ValueError, KeyError)):
        metric.check_report(root, report)


def test_cc005_conflicting_compiler_evidence():
    row = dict(asdict(native('a')), source='a')
    with pytest.raises(ValueError, match='Conflicting'):
        metric.recorded_compiler([row, dict(row, booleans=1)])


def test_cc005_above_limit_cannot_be_accepted(evidence):
    root, report = evidence
    template = report['files'][0]['templates'][0]
    row = next(row for row in template['expressions'] if row['source'] == 'a and b')
    row['booleans'] = 9
    template['complexity'] = 11
    with pytest.raises(ValueError, match='complexity 11 exceeds 9'):
        metric.check_report(root, report)


def test_cc005_source_change_during_native_borrow(tmp_path):
    path = tmp_path / metric.DIRECTORY / 'simple.xsl'
    path.parent.mkdir(parents=True)
    path.write_bytes(controls.stylesheet('<xsl:if test="changed"/>'))

    def modified(expression):
        if expression == 'changed':
            path.write_bytes(controls.stylesheet('<out/>'))
        return native(expression)

    with pytest.raises(ValueError, match='changed during'):
        metric.measured_report(tmp_path, modified)


def test_cc005_cli_uses_qualified_native_provider(evidence, monkeypatch, capsys):
    root, report = evidence
    monkeypatch.setattr(adapter, 'compile_xpath', native)
    path = root / 'report.json'
    assert metric.main(['measure', '--root', str(root), '--report', str(path)]) == 0
    assert json.loads(path.read_text()) == report
    assert '1 source-bound XSLT templates accepted' in capsys.readouterr().out
    assert metric.main(['check', '--root', str(root), '--report', str(path)]) == 0


def test_cc005_bounded_invalid_xml_and_avt_property():
    randomizer = random.Random(5005)
    for _ in range(64):
        value = ''.join(randomizer.choice('abc\'"{}[]&<>') for _ in range(16))
        source = controls.stylesheet('<out value="' + value + '"/>')
        try:
            rows = metric.measure_source(source, native)
        except (ValueError, etree.LxmlError):
            continue
        assert rows[0]['complexity'] >= 1
