"""CC-003: independent inventories, calibrated providers and stale-report rejection."""
import json
from pathlib import Path
import ast
from copy import deepcopy
from types import SimpleNamespace

import pytest

from articulous import complexity_native as native
from articulous import complexity_python as worker
from articulous import complexity_gate as gate
from articulous import complexity_contracts as contracts


def test_cc003_javascript_results_are_matched_by_file_identity(tmp_path, monkeypatch):
    files = ['second.js', 'first.js']
    for name in files:
        (tmp_path / name).write_text('')

    def metadata(_):
        return {'analyzer': 'ESLint', 'version': '10.8.1'}

    def output(*_, **kwargs):
        return json.dumps([{'filePath': str(tmp_path / name)} for name in sorted(files)])

    def file_result(root, name, result, eslint):
        assert root / name == Path(result['filePath'])
        return {'path': name}

    monkeypatch.setattr(native, 'installed_javascript', metadata)
    monkeypatch.setattr(native, 'command', output)
    monkeypatch.setattr(native, 'javascript_file', file_result)
    result = native.javascript_measurements(tmp_path, files, tmp_path / 'eslint')
    assert [row['path'] for row in result['files']] == files


@pytest.fixture
def record():
    source = 'def f(value):\n return value\n'
    row = gate.python_identities(source)['f']
    return dict(row, complexity=1)


@pytest.mark.parametrize('field,value', [
    ('name', ''), ('name', None), ('line', 0), ('line', True), ('column', -1),
    ('column', False), ('end_line', 0), ('end_column', -1), ('line', 3),
    ('body_sha256', 'A' * 64), ('projection_sha256', None),
    ('complexity', 0), ('complexity', True), ('complexity', '2'),
])
def test_cc003_invalid_function_records(record, field, value):
    record[field] = value
    with pytest.raises(ValueError):
        contracts.decode_function(record)


@pytest.mark.parametrize('value', [None, [], {}, {'unknown': 1}])
def test_cc003_invalid_record_shapes(value):
    with pytest.raises(ValueError):
        contracts.decode_function(value)


@pytest.mark.parametrize('value', [None, '', '/a', '../a', 'a//b', 'a/./b', 'a/../b', 'a\\b', 'C:a'])
def test_cc003_invalid_paths(value):
    with pytest.raises(ValueError):
        contracts.require_relative(value)


def test_cc003_bounded_property_records(record):
    for complexity in range(1, 12):
        row = contracts.decode_function(dict(record, complexity=complexity))
        assert row.complexity == complexity
    for column in range(32):
        contracts.require_position(1, column)
    contracts.require_relative('tests/a.py')


def test_cc003_encoding_and_nested_scope_projection():
    source = '# coding: latin-1\ndef f():\n return "é"\n'
    assert worker.python_text(source.encode('latin-1')) == source
    assert worker.python_text(source) == source
    tree = ast.parse('async def outer():\n async def inner():\n  pass\n return lambda x=1: x\n')
    rows = list(worker.definitions(tree))
    assert [name for name, _ in rows] == ['outer', 'outer.inner', 'outer.<lambda>@4:8']
    assert 'inner' not in worker.projection(rows[0][1])
    assert 'return x' in worker.projection(rows[-1][1])
    assert list(worker.identity_fields(ast.Constant(1)))
    node = type('GenericNode', (ast.AST,), {'_fields': ('type_params',), 'type_params': []})()
    assert list(worker.identity_fields(node)) == []


def test_cc003_class_and_async_projection_boundaries(monkeypatch):
    source = 'def f():\n class C(Base, metaclass=Meta):\n  def method(self): return 1\n async def inner(): pass\n return C\n'
    rows = list(worker.definitions(ast.parse(source)))
    assert [name for name, _ in rows] == ['f', 'f.C.method', 'f.inner']
    projected = worker.projection(rows[0][1])
    assert 'Base' in projected and 'Meta' in projected
    assert 'async def inner' not in projected
    nested = ast.parse('def outer():\n def inner(value=1): pass\n return inner\n').body[0]
    assert 'def inner' not in worker.projection(nested)
    monkeypatch.setattr(worker.ast, 'get_source_segment', lambda *_: None)
    with pytest.raises(ValueError, match='no source boundary'):
        worker.function_identity('f', rows[0][1], source)


def test_cc003_callable_header_decisions_are_preserved():
    source = '@(first if flag else second)\ndef f(value=1 if flag else 2):\n return value\n'
    node = ast.parse(source).body[0]
    projected = ast.parse(worker.projection(node))
    assert sum(isinstance(item, ast.IfExp) for item in ast.walk(projected)) == 2


def test_cc003_formatted_string_decisions_are_visible_to_native_analyzer():
    source = 'def f(flag):\n return f"{1 if flag else 2:{3 if flag else 4}}"\n'
    projected = ast.parse(worker.projection(ast.parse(source).body[0]))
    assert not any(isinstance(item, ast.JoinedStr) for item in ast.walk(projected))
    assert sum(isinstance(item, ast.IfExp) for item in ast.walk(projected)) == 2


def test_cc003_annotations_and_unsupported_syntax():
    source = 'def f(x: (1 if flag else 2)) -> (3 if flag else 4):\n return x\n'
    node = ast.parse(source).body[0]
    assert sum(isinstance(item, ast.IfExp) for item in ast.walk(ast.parse(worker.projection(node)))) == 2
    for statement in ('match x:\n  case 1: pass', 'try: pass\n except* ValueError: pass'):
        node = ast.parse('def f(x):\n ' + statement + '\n').body[0]
        with pytest.raises(ValueError, match='Unsupported Python decision'):
            worker.projection(node)
    node = type('GenericNode', (ast.AST,), {'_fields': (), 'type_params': [ast.Constant(1)]})()
    with pytest.raises(ValueError, match='generic'):
        worker.require_supported(node)


def analyzer_for(source, complexity=1, *, wrong=False):
    end = ast.parse(source).body[0].end_lineno
    row = SimpleNamespace(name='measurement', start_line=1, end_line=end,
                          cyclomatic_complexity=complexity)
    values = [] if wrong else [row]
    return SimpleNamespace(analyze_file=SimpleNamespace(
        analyze_source_code=lambda *_: SimpleNamespace(function_list=values)))


def test_cc003_worker_measurement_and_missing_boundary():
    source = 'def f():\n return 1\n'
    node = ast.parse(source).body[0]
    analyzer = analyzer_for(worker.projection(node))
    assert worker.measure_source(analyzer, source)[0]['complexity'] == 1
    with pytest.raises(ValueError, match='complete isolated'):
        worker.measure_function(analyzer_for(source, wrong=True), 'f', node, source)


def test_cc003_projection_identity_survives_unparse_quote_changes(monkeypatch):
    source = 'def f():\n return "text"\n'
    projections = iter(['def measurement():\n return "text"\n', "def measurement():\n return 'text'\n"])
    monkeypatch.setattr(worker, 'projection', lambda _: next(projections))
    analyzer = analyzer_for(source)
    first = worker.measure_source(analyzer, source)[0]
    second = worker.measure_source(analyzer, source)[0]
    assert first['projection_sha256'] == second['projection_sha256']


def test_cc003_calibration_controls(monkeypatch):
    expected = {source: values for _, source, values in worker.CALIBRATIONS}

    def measured(_, source):
        return [{'complexity': value} for value in expected[source]]

    monkeypatch.setattr(worker, 'measure_source', measured)
    rows = worker.calibrate(None)
    gate.check_python_calibration({'analyzer': 'Lizard', 'version': '1', 'calibration': rows})
    expected[worker.CALIBRATIONS[0][1]] = [2]
    with pytest.raises(ValueError, match='calibration failed'):
        worker.calibrate(None)
    rows[0]['actual'] = [2]
    with pytest.raises(ValueError, match='Failed Python'):
        gate.check_python_calibration({'analyzer': 'Lizard', 'version': '1', 'calibration': rows})


@pytest.mark.parametrize('metadata', [
    {'analyzer': 'Other', 'version': '1', 'calibration': [1]},
    {'analyzer': 'Lizard', 'version': '', 'calibration': [1]},
    {'analyzer': 'Lizard', 'version': '1', 'calibration': []},
    {'analyzer': 'Lizard', 'version': '1', 'calibration': [{'expected': [], 'actual': []}]},
])
def test_cc003_invalid_python_provenance(metadata):
    with pytest.raises(ValueError):
        gate.check_python_calibration(metadata)


def test_cc003_worker_entry_points(tmp_path, monkeypatch, capsys):
    (tmp_path / 'a.py').write_text('def f():\n return 1\n')
    monkeypatch.setattr(worker, 'installed_analyzer', lambda: (analyzer_for('def f():\n return 1\n'), '1'))
    monkeypatch.setattr(worker, 'calibrate', lambda _: ['calibrated'])
    assert worker.main([str(tmp_path), 'a.py']) == 0
    assert json.loads(capsys.readouterr().out)['files'][0]['functions'][0]['complexity'] == 1
    monkeypatch.setattr(worker, 'baseline_inventory', lambda *_: {'revision': worker.BASELINE})
    assert worker.main([str(tmp_path), 'a.py', '--baseline']) == 0
    assert json.loads(capsys.readouterr().out)['revision'] == worker.BASELINE


def test_cc003_installed_analyzer_and_baseline(monkeypatch, tmp_path):
    monkeypatch.setattr(worker.importlib, 'import_module', lambda _: 'analyzer')
    monkeypatch.setattr(worker.importlib.metadata, 'version', lambda _: '1.23.0')
    assert worker.installed_analyzer() == ('analyzer', '1.23.0')

    def run(arguments, **kwargs):
        assert kwargs == {'capture_output': True, 'check': True}
        output = b'a.py\0' if 'ls-tree' in arguments else b'def f():\n return 1\n'
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr(worker.subprocess, 'run', run)
    baseline = worker.baseline_inventory(tmp_path, ['a.py', 'new.py'])
    assert list(baseline['functions']) == ['a.py']


def test_cc003_native_command_and_python_adapter(monkeypatch):
    result = SimpleNamespace(returncode=0, stdout='output', check_returncode=lambda: pytest.fail('unexpected'))
    monkeypatch.setattr(native, 'run_browser_suite', lambda *_, **__: result)
    assert native.command(['tool']) == 'output'
    result.returncode = 2
    result.check_returncode = lambda: (_ for _ in ()).throw(ValueError('exit'))
    with pytest.raises(ValueError, match='exit'):
        native.command(['tool'])
    monkeypatch.setattr(native, 'command', lambda _: json.dumps({'analyzer': 'Lizard', 'calibration': [1]}))
    assert native.python_measurements(Path('.'), ['a.py'], 'python')['adapter_sha256']


@pytest.mark.parametrize('value', [{}, {'analyzer': 'Lizard', 'calibration': []}])
def test_cc003_native_python_missing_results(monkeypatch, value):
    monkeypatch.setattr(native, 'command', lambda _: json.dumps(value))
    with pytest.raises(ValueError):
        native.python_measurements(Path('.'), [], 'python')


def region_node(kind='FunctionDeclaration', start=0, end=30):
    return {'type': kind, 'start': start, 'end': end,
            'loc': {'start': {'line': 1, 'column': start}, 'end': {'line': 1, 'column': end}}}


def diagnostic(label='Function', column=1):
    return {'ruleId': 'complexity', 'message': f'{label} has a complexity of 2. Maximum allowed is 0.',
            'line': 1, 'column': column}


def test_cc003_javascript_boundaries_and_implicit_scopes():
    node = region_node()
    parent = dict(region_node('MethodDefinition'), value=node)
    assert len(list(native.function_regions([parent]))) == 1
    arrow = region_node('ArrowFunctionExpression', 2, 20)
    field = dict(region_node('PropertyDefinition'), value=arrow)
    scopes = list(native.function_regions([field, region_node('StaticBlock')]))
    assert [row['kind'] for row in scopes] == ['Class field initializer', 'function', 'Class static block']
    assert native.diagnostic_kind('Class static block has') == 'Class static block'
    assert native.diagnostic_region(diagnostic(column=1), scopes)['node'] is arrow
    assert native.diagnostic_region(diagnostic('Class field initializer', 3), scopes)['node'] is arrow
    assert native.javascript_records([diagnostic()], node, 'x' * 30)[0]['complexity'] == 2


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'outside', 'ambiguous', 'rule', 'message'])
def test_cc003_javascript_fault_controls(fault):
    node = region_node()
    messages = [diagnostic()]
    tree = node
    if fault == 'missing':
        messages = []
    if fault == 'duplicate':
        messages *= 2
    if fault == 'outside':
        messages[0]['line'] = 2
    if fault == 'ambiguous':
        tree = [node, deepcopy(node)]
    if fault == 'rule':
        messages[0]['ruleId'] = 'other'
    if fault == 'message':
        messages[0]['message'] = 'Unexpected message'
    with pytest.raises(ValueError):
        native.javascript_records(messages, tree, 'x' * 30)


def test_cc003_installed_javascript_metadata(tmp_path):
    eslint = tmp_path / 'eslint'
    (eslint / 'lib/rules').mkdir(parents=True)
    (eslint / 'package.json').write_text('{"version":"10.8.1"}')
    (eslint / 'lib/rules/complexity.js').write_text('rule')
    acorn = tmp_path / 'acorn'
    (acorn / 'dist').mkdir(parents=True)
    (acorn / 'package.json').write_text('{"version":"8"}')
    (acorn / 'dist/acorn.js').write_text('parser')
    assert native.installed_javascript(eslint)['parser_version'] == '8'


@pytest.mark.parametrize('fault', ['none', 'fatal', 'suppressed', 'source-edit'])
def test_cc003_javascript_file_lifetime(tmp_path, monkeypatch, fault):
    path = tmp_path / 'a.js'
    path.write_text('x' * 30)

    def command(_):
        if fault == 'source-edit':
            path.write_text('changed')
        return json.dumps(region_node())

    monkeypatch.setattr(native, 'command', command)
    result = {'messages': [diagnostic()], 'fatalErrorCount': fault == 'fatal',
              'suppressedMessages': ['hidden'] if fault == 'suppressed' else []}
    if fault == 'none':
        assert native.javascript_file(tmp_path, 'a.js', result, tmp_path / 'eslint')['path'] == 'a.js'
    else:
        with pytest.raises(ValueError):
            native.javascript_file(tmp_path, 'a.js', result, tmp_path / 'eslint')


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'analyzer-edit', 'source-edit'])
def test_cc003_javascript_inventory_lifetime(tmp_path, monkeypatch, fault):
    path = tmp_path / 'a.js'
    path.write_text('initial')
    results = [{'filePath': str(path)}]
    if fault == 'missing':
        results = []
    if fault == 'duplicate':
        results *= 2
    versions = iter([1, 2] if fault == 'analyzer-edit' else [1, 1])
    monkeypatch.setattr(native, 'installed_javascript', lambda _: next(versions))

    def command(*_, **__):
        if fault == 'source-edit':
            path.write_text('edited')
        return json.dumps(results)

    monkeypatch.setattr(native, 'command', command)
    monkeypatch.setattr(native, 'javascript_file', lambda *_: {})
    with pytest.raises(ValueError):
        native.javascript_measurements(tmp_path, ['a.js'], tmp_path / 'eslint')


@pytest.fixture
def evidence(tmp_path, record):
    (tmp_path / 'articulous').mkdir()
    (tmp_path / 'articulous/a.py').write_text('def f(value):\n return value\n')
    report = {'schema': 1, 'baseline': worker.BASELINE, 'upstream': {},
              'analyzers': {'python': {'analyzer': 'Lizard', 'version': '1.23.0',
                  'calibration': [{'name': name, 'source': source, 'expected': values, 'actual': values}
                                  for name, source, values in worker.CALIBRATIONS]},
                  'javascript': {'analyzer': 'ESLint', 'version': '10.8.1', 'parser': 'Acorn'}},
              'files': [{'path': 'articulous/a.py', 'language': 'python',
                         'sha256': worker.digest((tmp_path / 'articulous/a.py').read_bytes()),
                         'functions': [record]}]}
    calibration = tmp_path / gate.JS_CALIBRATION
    calibration.parent.mkdir(parents=True)
    calibration.write_text('')
    report['files'].append({'path': gate.JS_CALIBRATION, 'language': 'javascript',
                           'sha256': worker.digest(b''),
                           'functions': [dict(record, name=name, complexity=cc, line=index + 1,
                                              end_line=index + 2) for index, (name, cc) in enumerate(gate.JS_EXPECTED)]})
    manifest = tmp_path / gate.PRISM
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"upstream_unmodified": {"LICENSE": "ignored"}}')
    baseline = tmp_path / gate.BASELINE_FILE
    baseline.parent.mkdir(parents=True)
    baseline.write_text(json.dumps({'revision': worker.BASELINE, 'functions': {}}))
    return tmp_path, report


def test_cc003_report_and_prepolicy_identity(evidence):
    root, report = evidence
    assert gate.check_report(root, report) == 14
    entry = report['files'][0]
    entry['functions'][0]['complexity'] = 10
    baseline = {entry['functions'][0]['name']: entry['functions'][0]['body_sha256']}
    assert gate.check_functions(entry, baseline, (root / entry['path']).read_bytes()) == 1
    with pytest.raises(ValueError, match='exceeds 9'):
        gate.check_report(root, report)


def corrupt_report(report, fault):
    entry = report['files'][0]
    mutations = {
        'schema': lambda: report.update(schema=2),
        'baseline': lambda: report.update(baseline='other'),
        'upstream': lambda: report.update(upstream={'unknown': 'a' * 64}),
        'duplicate-file': lambda: report['files'].append(deepcopy(entry)),
        'language': lambda: entry.update(language='javascript'),
        'hash': lambda: entry.update(sha256='a' * 64),
        'missing-function': lambda: entry.update(functions=[]),
        'duplicate-function': lambda: entry['functions'].append(deepcopy(entry['functions'][0])),
        'identity': lambda: entry['functions'][0].update(body_sha256='a' * 64),
        'projection': lambda: entry['functions'][0].update(projection_sha256='a' * 64),
        'unknown-function': lambda: entry['functions'][0].update(name='absent'),
        'js-calibration': lambda: report['files'][1]['functions'].pop(),
    }
    mutations[fault]()


@pytest.mark.parametrize('fault', ['schema', 'baseline', 'upstream', 'duplicate-file', 'language', 'hash',
                                 'missing-function', 'duplicate-function', 'identity', 'projection',
                                 'unknown-function', 'js-calibration'])
def test_cc003_report_fault_controls(evidence, fault):
    root, report = evidence
    corrupt_report(report, fault)
    with pytest.raises(ValueError):
        gate.check_report(root, report)


@pytest.mark.parametrize('field,value', [('analyzer', 'other'), ('version', ''), ('parser', 'other')])
def test_cc003_invalid_js_provenance(evidence, field, value):
    root, report = evidence
    report['analyzers']['javascript'][field] = value
    with pytest.raises(ValueError, match='provenance'):
        gate.check_report(root, report)


def test_cc003_upstream_integrity(evidence):
    root, report = evidence
    path = root / 'articulous/theme_assets/vendor.js'
    path.write_text('original')
    expected = worker.digest(path.read_bytes())
    (root / gate.PRISM).write_text(json.dumps({'upstream_unmodified': {'vendor.js': expected}}))
    assert gate.upstream_files(root) == {'articulous/theme_assets/vendor.js': expected}
    report['upstream'] = gate.upstream_files(root)
    report['files'].append({'path': 'articulous/theme_assets/vendor.js'})
    with pytest.raises(ValueError, match='cannot replace'):
        gate.check_report(root, report)
    path.write_text('modified')
    with pytest.raises(ValueError, match='Upstream dependency'):
        gate.upstream_files(root)


def test_cc003_baseline_validation_and_capacity(evidence, monkeypatch):
    root, _ = evidence
    path = root / gate.BASELINE_FILE
    path.write_text(json.dumps({'revision': worker.BASELINE, 'functions': {'a.py': {'f': 'a' * 64}}}))
    assert gate.baseline_data(root)['a.py']['f'] == 'a' * 64
    path.write_text('{"revision":"other"}')
    with pytest.raises(ValueError, match='baseline changed'):
        gate.baseline_data(root)
    monkeypatch.setattr(gate, 'MAX_EVIDENCE_BYTES', 2)
    path.write_text('{}')
    assert gate.load_json(path) == {}
    path.write_text('{} ')
    with pytest.raises(ValueError, match='capacity'):
        gate.load_json(path)


def test_cc003_measurement_and_cli(evidence, monkeypatch, capsys):
    root, report = evidence
    python = dict(report['analyzers']['python'], files=[report['files'][0]])
    js = dict(report['analyzers']['javascript'], files=[report['files'][1]])
    monkeypatch.setattr(native, 'python_measurements', lambda *_: deepcopy(python))
    monkeypatch.setattr(native, 'javascript_measurements', lambda *_: deepcopy(js))
    assert gate.measured_report(root, 'python', Path('eslint')) == report
    path = root / 'result.json'
    assert gate.main(['measure', '--root', str(root), '--report', str(path), '--eslint', 'eslint']) == 0
    assert '14 source-bound' in capsys.readouterr().out
    assert gate.main(['check', '--root', str(root), '--report', str(path)]) == 0
    with pytest.raises(SystemExit):
        gate.main(['measure'])
