"""Optional offline complexity measurement and source-bound evidence acceptance."""
import argparse
import ast
import json
from pathlib import Path

from . import complexity_native as native
from .complexity_contracts import MAX_EVIDENCE_BYTES, decode_function, require_digest, require_relative
from .complexity_python import BASELINE, CALIBRATIONS, ast_identity, definitions, digest, function_identity, projection, python_text
from .filesystem import write_text_atomic

EVIDENCE = 'reviews/complexity/functions.json'
BASELINE_FILE = 'reviews/complexity/baseline.json'
PRISM = 'articulous/theme_assets/third_party/prism/manifest.json'
JS_CALIBRATION = 'tests/fixtures/complexity/calibration.js'
JS_EXPECTED = (("Function 'straight'", 1), ("Function 'choices'", 4), ("Function 'outer'", 1),
               ("Function 'inner'", 2), ('Arrow function', 2), ("Method 'show'", 1),
               ("Method 'restore'", 1), ("Function 'optional'", 4), ("Function 'boundary'", 9),
               ('Class field initializer', 2), ('Class field initializer', 1),
               ("Method 'factory'", 2), ('Class static block', 2))


def source_paths(root):
    paths = set(root.glob('*.py'))
    for directory in ('articulous', 'tests'):
        paths.update(path for path in (root / directory).rglob('*') if path.suffix in ('.py', '.js', '.mjs'))
    return sorted(path.relative_to(root).as_posix() for path in paths)


def upstream_files(root):
    manifest = json.loads((root / PRISM).read_text())
    result = {}
    for name, expected in manifest['upstream_unmodified'].items():
        path = 'articulous/theme_assets/' + name
        if not name.endswith('.js'):
            continue
        require_relative(path)
        require_digest(expected)
        if digest((root / path).read_bytes()) != expected:
            raise ValueError('Upstream dependency source changed: ' + path)
        result[path] = expected
    return result


def load_json(path):
    with path.open('rb') as source:
        payload = source.read(MAX_EVIDENCE_BYTES + 1)
    if len(payload) > MAX_EVIDENCE_BYTES:
        raise ValueError('Complexity evidence capacity exceeded')
    return json.loads(payload)


def baseline_data(root):
    result = load_json(root / BASELINE_FILE)
    if result['revision'] != BASELINE:
        raise ValueError('Complexity policy baseline changed')
    for path, functions in result['functions'].items():
        require_relative(path)
        for value in functions.values():
            require_digest(value)
    return result['functions']


def python_identities(content):
    source = python_text(content)
    return {name: dict(function_identity(name, node, source),
                       projection_sha256=digest(ast_identity(ast.parse(projection(node))).encode()))
            for name, node in definitions(ast.parse(source))}


def check_python_function(row, identities):
    wanted = identities.get(row.name)
    if wanted is None:
        raise ValueError('Unexpected Python function measurement: ' + row.name)
    actual = {key: getattr(row, key) for key in wanted}
    if actual != wanted:
        raise ValueError('Python function identity or boundary changed: ' + row.name)


def unique_functions(values):
    rows = [decode_function(value) for value in values]
    keys = [(row.name, row.line, row.column, row.end_line, row.end_column) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate complexity function boundary')
    return rows


def check_functions(entry, baseline, content):
    rows = unique_functions(entry['functions'])
    identities = python_identities(content) if entry['language'] == 'python' else None
    for row in rows:
        if identities is not None:
            check_python_function(row, identities)
        if row.complexity > 9 and baseline.get(row.name) != row.body_sha256:
            raise ValueError(f'{entry["path"]}:{row.name}: complexity {row.complexity} exceeds 9')
    if identities is not None and len(rows) != len(identities):
        raise ValueError('Missing Python function measurements')
    return len(rows)


def check_file(root, entry, baseline):
    name = entry['path']
    require_relative(name)
    require_digest(entry['sha256'])
    expected_language = 'python' if name.endswith('.py') else 'javascript'
    if entry['language'] != expected_language:
        raise ValueError('Complexity source language changed')
    content = (root / name).read_bytes()
    if digest(content) != entry['sha256']:
        raise ValueError('Stale complexity source: ' + name)
    return check_functions(entry, baseline.get(name, {}), content)


def check_python_calibration(python):
    if python['analyzer'] != 'Lizard' or not python['version'] or not python['calibration']:
        raise ValueError('Missing Python analyzer provenance')
    for row in python['calibration']:
        if row['expected'] != row['actual']:
            raise ValueError('Failed Python analyzer calibration')
    expected = [{'name': name, 'source': source, 'expected': values, 'actual': values}
                for name, source, values in CALIBRATIONS]
    if python['calibration'] != expected:
        raise ValueError('Incomplete Python analyzer calibration')


def check_javascript_calibration(report):
    js = report['analyzers']['javascript']
    if js['analyzer'] != 'ESLint' or not js['version'] or js['parser'] != 'Acorn':
        raise ValueError('Missing JavaScript analyzer provenance')
    actual = [(row['name'], row['complexity']) for entry in report['files']
              if entry['path'] == JS_CALIBRATION for row in entry['functions']]
    if sorted(actual) != sorted(JS_EXPECTED):
        raise ValueError('Failed JavaScript analyzer calibration')


def check_report(root, report):
    if report['schema'] != 1 or report['baseline'] != BASELINE:
        raise ValueError('Invalid complexity evidence version or baseline')
    check_python_calibration(report['analyzers']['python'])
    check_javascript_calibration(report)
    baseline = baseline_data(root)
    upstream = upstream_files(root)
    if report['upstream'] != upstream:
        raise ValueError('Upstream source inventory changed')
    paths = [entry['path'] for entry in report['files']]
    if len(paths) != len(set(paths)) or set(paths) | set(upstream) != set(source_paths(root)):
        raise ValueError('Complexity source inventory changed')
    if set(paths) & set(upstream):
        raise ValueError('Upstream functions cannot replace maintained measurements')
    return sum(check_file(root, entry, baseline) for entry in report['files'])


def measured_report(root, python, eslint):
    upstream = upstream_files(root)
    paths = [name for name in source_paths(root) if name not in upstream]
    py = native.python_measurements(root, [name for name in paths if name.endswith('.py')], python)
    js = native.javascript_measurements(root, [name for name in paths if not name.endswith('.py')], eslint)
    files = [dict(entry, language='python') for entry in py.pop('files')]
    files.extend(dict(entry, language='javascript') for entry in js.pop('files'))
    report = {'schema': 1, 'baseline': BASELINE, 'upstream': upstream, 'files': files,
              'analyzers': {'python': py, 'javascript': js}}
    check_report(root, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('check', 'measure'))
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--report', type=Path, default=Path(EVIDENCE))
    parser.add_argument('--python-analyzer', default='/usr/bin/python3')
    parser.add_argument('--eslint', type=Path)
    args = parser.parse_args(argv)
    if args.mode == 'measure':
        if args.eslint is None:
            parser.error('--eslint must name an installed ESLint package directory')
        report = measured_report(args.root, args.python_analyzer, args.eslint)
        write_text_atomic(args.report, json.dumps(report, indent=2, sort_keys=True) + '\n')
    count = check_report(args.root, load_json(args.report))
    print(f'{count} source-bound functions accepted; unchanged pre-policy identities remain explicit')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
