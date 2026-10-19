"""TEST-001/BUILD-008/REV-108: independent coverage evidence and faulty controls."""
import ast
from copy import deepcopy
import json

import pytest
from coverage import Coverage
from coverage.python import PythonFileReporter

from articulous.coverage_gate import check_report, inventory, main

SOURCE = 'def work():\n    x = 1\n    y = 2\n    z = 3\n    q = 4\n    return x + y + z + q\n'


@pytest.fixture
def evidence(tmp_path):
    path = tmp_path / 'code/example.py'
    path.parent.mkdir()
    path.write_text(SOURCE)
    reporter = PythonFileReporter(str(path), Coverage())
    region = next(r for r in reporter.code_regions() if r.kind == 'function')
    lines = sorted(reporter.lines() & region.lines)
    record = {'executed_lines': lines, 'missing_lines': [], 'start_line': region.start,
              'summary': {'percent_covered': 100, 'covered_lines': len(lines),
                          'missing_lines': 0, 'num_statements': len(lines)}}
    report = {'files': {'code/example.py': {'functions': {'work': record}}}}
    return tmp_path, report, record


def check(evidence):
    root, report, _ = evidence
    return check_report(root, ['code'], report)


def test_test001_valid_and_boundary_evidence(evidence):
    assert check(evidence) == (1, [])
    _, _, record = evidence
    record['missing_lines'] = record['executed_lines'][:1]
    record['executed_lines'] = record['executed_lines'][1:]
    record['summary'].update(percent_covered=80, covered_lines=4, missing_lines=1)
    assert check(evidence) == (1, [])
    record['missing_lines'].append(record['executed_lines'].pop())
    record['summary'].update(percent_covered=60, covered_lines=3, missing_lines=2)
    assert 'require 80' in check(evidence)[1][0]


@pytest.mark.parametrize('field', ['executed_lines', 'missing_lines'])
@pytest.mark.parametrize('invalid', [None, '1', [True], [0], [-1], [1.5]])
def test_build008_invalid_counters(evidence, field, invalid):
    evidence[2][field] = invalid
    assert 'native ' + field in check(evidence)[1][0]


@pytest.mark.parametrize('invalid', [None, True, '100', float('nan'), float('inf'), -1, 101])
def test_build008_invalid_percent(evidence, invalid):
    evidence[2]['summary']['percent_covered'] = invalid
    assert check(evidence)[1]


@pytest.mark.parametrize('defect', ['empty', 'overlap', 'duplicate', 'outside', 'omitted', 'percentage', 'summary', 'start'])
def test_rev108_inconsistent_records(evidence, defect):
    record = evidence[2]
    changes = {'empty': [], 'duplicate': record['executed_lines'] * 2,
               'outside': [9999], 'omitted': record['executed_lines'][1:]}
    if defect in changes:
        record['executed_lines'] = changes[defect]
    elif defect == 'overlap':
        record['missing_lines'] = record['executed_lines'][:1]
    elif defect == 'start':
        record['start_line'] += 1
    else:
        key = 'percent_covered' if defect == 'percentage' else 'num_statements'
        record['summary'][key] += 1
    assert check(evidence)[1]


@pytest.mark.parametrize('defect', ['function', 'file', 'stale'])
def test_build008_missing_and_stale(evidence, defect):
    functions = evidence[1]['files']['code/example.py']['functions']
    if defect == 'function':
        del functions['work']
    elif defect == 'file':
        evidence[1]['files'] = {}
    else:
        functions['retired'] = deepcopy(functions['work'])
    assert check(evidence)[1]


def test_test001_empty_declarations_and_nested_inventory(tmp_path):
    path = tmp_path / 'empty.py'
    path.write_text('class Contract:\n    def run(self):\n        ...\n')
    record = {'executed_lines': [], 'missing_lines': [], 'start_line': 2,
              'summary': {'covered_lines': 0, 'missing_lines': 0, 'num_statements': 0, 'percent_covered': 100}}
    assert check_report(tmp_path, ['.'], {'files': {'empty.py': {'functions': {'Contract.run': record}}}}) == (1, [])
    assert inventory(ast.parse('class A:\n def m(self):\n  def nested():\n   pass\n')) == ['A.m', 'A.m.nested']


def test_build008_anonymous_callback_rejected(tmp_path):
    (tmp_path / 'bad.py').write_text('callback = lambda value: value\n')
    assert 'named function' in check_report(tmp_path, ['.'], {})[1][0]


def test_test001_cli(evidence, capsys):
    root, report, _ = evidence
    path = root / 'coverage.json'
    path.write_text(json.dumps(report))
    args = [str(path), '--root', str(root), '--directory', 'code']
    assert main(args) == 0
    assert '1 maintained' in capsys.readouterr().out
    path.write_text('{}')
    with pytest.raises(SystemExit, match='missing native'):
        main(args)


def test_test001_boolean_summary_is_not_native_evidence(evidence):
    evidence[2]['summary']['missing_lines'] = False
    assert check(evidence)[1]


def test_test001_projection_default_has_native_function_counters():
    from articulous.filesystem import TempWorkspace
    from articulous.pipeline import StreamProjection, SECTION_NAMES, SitemapSink, SearchSink
    with TempWorkspace() as workspace:
        projection = StreamProjection(SitemapSink(workspace), SearchSink(workspace), [], 0)
        assert projection.sections == frozenset(SECTION_NAMES)
