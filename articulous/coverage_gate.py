"""Optional native per-function coverage validation; source is the independent oracle."""
import argparse
import ast
import json
import math
from pathlib import Path

from coverage import Coverage
from coverage.python import PythonFileReporter


def inventory(node, prefix=''):
    names = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Lambda):
            raise ValueError('Use a named function so coverage can measure it individually')
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = prefix + child.name
            if not isinstance(child, ast.ClassDef):
                names.append(name)
            names.extend(inventory(child, name + '.'))
        else:
            names.extend(inventory(child, prefix))
    return names


def line_counters(function, field):
    counters = function.get(field)
    if not isinstance(counters, list):
        raise ValueError('invalid or missing native ' + field)
    if any(type(line) is not int or line < 1 for line in counters):
        raise ValueError('invalid or missing native ' + field)
    if len(counters) != len(set(counters)):
        raise ValueError('inconsistent native counters or summary')
    return set(counters)


def check_function(function, region, statements):
    executed = line_counters(function, 'executed_lines')
    missing = line_counters(function, 'missing_lines')
    expected = statements & region.lines
    summary = function.get('summary', {})
    counts = (summary.get('covered_lines'), summary.get('missing_lines'), summary.get('num_statements'))
    if any(type(value) is not int for value in counts):
        raise ValueError('inconsistent native counters or summary')
    if (executed & missing or executed | missing != expected
            or type(function.get('start_line')) is not int
            or function.get('start_line') != region.start
            or counts != (len(executed), len(missing), len(expected))):
        raise ValueError('inconsistent native counters or summary')
    check_percent(summary.get('percent_covered'), len(executed), len(expected))


def check_percent(percent, executed, expected):
    actual = 100 * executed / expected if expected else 100
    if type(percent) not in (int, float) or not math.isclose(percent, actual, abs_tol=1e-8):
        raise ValueError('inconsistent native counters or summary')
    if not 80 <= percent <= 100:
        raise ValueError(f'{percent!r}% executable lines; require 80–100%')


def check_file(path, root, report):
    filename = path.relative_to(root).as_posix()
    names = inventory(ast.parse(path.read_text()))
    if len(names) != len(set(names)):
        raise ValueError('Ambiguous callable names; native counters cannot distinguish definitions')
    reporter = PythonFileReporter(str(path), Coverage())
    statements = reporter.lines()
    regions = {region.name: region for region in reporter.code_regions() if region.kind == 'function'}
    functions = report.get('files', {}).get(filename, {}).get('functions', {})
    failures = []
    for name in names:
        if name not in functions:
            failures.append(f'{filename}:{name}: missing native counters')
            continue
        try:
            check_function(functions[name], regions[name], statements)
        except ValueError as error:
            failures.append(f'{filename}:{name}: {error}')
    unexpected = set(functions) - set(names) - {''}
    if unexpected:
        failures.append(f'{filename}: stale function counters: {sorted(unexpected)}')
    return len(names), failures


def check_report(root: Path, directories, report):
    """Borrow source/report for this call; retain only bounded scalar diagnostics."""
    failures = []
    count = 0
    for directory in directories:
        for path in sorted((root / directory).rglob('*.py')):
            try:
                measured, errors = check_file(path, root, report)
            except ValueError as error:
                failures.append(f'{path.relative_to(root)}: {error}')
                continue
            count += measured
            failures.extend(errors)
    return count, failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--directory', action='append', required=True)
    args = parser.parse_args(argv)
    count, failures = check_report(args.root, args.directory, json.loads(args.report.read_text()))
    if failures:
        raise SystemExit('\n'.join(failures))
    print(f'{count} maintained Python functions: all have native counters and at least 80% executable-line coverage')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
