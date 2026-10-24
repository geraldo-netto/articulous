"""Installed analyzer adapters; owned processes read persistent source snapshots."""
import json
from pathlib import Path
import re

from .browser_process import run_browser_suite
from .complexity_python import digest

FUNCTION_TYPES = frozenset(('FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression'))
DIAGNOSTIC = re.compile(r'^(.*?) has a complexity of ([0-9]+)\. Maximum allowed is 0\.$')


def command(arguments, *, accepted=(0,)):
    result = run_browser_suite([str(item) for item in arguments], tooling=False)
    if result.returncode not in accepted:
        result.check_returncode()
    return result.stdout


def python_measurements(root, files, interpreter):
    worker = Path(__file__).with_name('complexity_python.py')
    result = json.loads(command([interpreter, worker, root, *files]))
    if result.get('analyzer') != 'Lizard' or not result.get('calibration'):
        raise ValueError('Missing calibrated Python analyzer results')
    result['adapter_sha256'] = digest(worker.read_bytes())
    return result


def javascript_tree(path):
    parser = Path(__file__).with_name('tooling_assets') / 'javascript-syntax.mjs'
    script = ("import {readFileSync} from 'node:fs';"
              "const {parseJavaScript}=await import(process.argv[1]);"
              "process.stdout.write(JSON.stringify(parseJavaScript(readFileSync(process.argv[2],'utf8')).tree));")
    return json.loads(command(['node', '--input-type=module', '-e', script, parser.as_uri(), path]))


def function_regions(node, parent=None):
    if isinstance(node, dict):
        yield from own_regions(node, parent)
        for value in node.values():
            yield from function_regions(value, node)
    elif isinstance(node, list):
        for child in node:
            yield from function_regions(child, parent)


def own_regions(node, parent):
    if node.get('type') in FUNCTION_TYPES:
        yield function_region(node, parent)
    if node.get('type') == 'PropertyDefinition' and node.get('value') is not None:
        yield function_region(node['value'], None, 'Class field initializer')
    if node.get('type') == 'StaticBlock':
        yield function_region(node, None, 'Class static block')


def function_region(node, parent, kind='function'):
    boundary = node
    if parent is not None and parent.get('type') in ('Property', 'MethodDefinition', 'PropertyDefinition') and parent.get('value') is node:
        boundary = parent
    return {'node': node, 'kind': kind, 'start': location(boundary['loc']['start']),
            'end': location(boundary['loc']['end'])}


def location(value):
    return value['line'], value['column']


def diagnostic_region(message, regions):
    position = message['line'], message['column'] - 1
    kind = diagnostic_kind(message['message'])
    candidates = [item for item in regions if item['kind'] == kind and item['start'] <= position < item['end']]
    if not candidates:
        raise ValueError(f'Analyzer reported a function outside the independent inventory: {message}')
    smallest = min(candidates, key=region_length)
    if sum(region_length(item) == region_length(smallest) for item in candidates) != 1:
        raise ValueError('Ambiguous JavaScript function boundary')
    return smallest


def diagnostic_kind(message):
    for kind in ('Class field initializer', 'Class static block'):
        if message.startswith(kind):
            return kind
    return 'function'


def region_length(region):
    return region['node']['end'] - region['node']['start']


def diagnostic_record(message, region, source):
    match = DIAGNOSTIC.fullmatch(message['message'])
    if message.get('ruleId') != 'complexity' or match is None:
        raise ValueError('Unexpected JavaScript analyzer diagnostic')
    node = region['node']
    content = source.encode('utf-16-le')[2 * node['start']:2 * node['end']].decode('utf-16-le')
    start, end = node['loc']['start'], node['loc']['end']
    return {'name': match[1], 'line': start['line'], 'column': start['column'],
            'end_line': end['line'], 'end_column': end['column'],
            'body_sha256': digest(content.encode()), 'projection_sha256': digest(content.encode()),
            'complexity': int(match[2])}


def javascript_records(messages, tree, source):
    regions = list(function_regions(tree))
    records, seen = [], set()
    for message in messages:
        region = diagnostic_region(message, regions)
        identity = region['kind'], region['node']['start'], region['node']['end']
        if identity in seen:
            raise ValueError('Duplicate JavaScript function measurement')
        seen.add(identity)
        records.append(diagnostic_record(message, region, source))
    if len(records) != len(regions):
        raise ValueError('Missing JavaScript function measurements')
    return records


def installed_javascript(eslint):
    acorn = eslint.parent / 'acorn'
    return {'analyzer': 'ESLint', 'version': json.loads((eslint / 'package.json').read_text())['version'],
            'rule_sha256': digest((eslint / 'lib/rules/complexity.js').read_bytes()),
            'parser': 'Acorn', 'parser_version': json.loads((acorn / 'package.json').read_text())['version'],
            'parser_sha256': digest((acorn / 'dist/acorn.js').read_bytes())}


def javascript_results(eslint, paths):
    output = command(['node', eslint / 'bin/eslint.js', '--no-config-lookup', '--no-inline-config',
                      '--no-ignore', '--rule', 'complexity: [error, {max: 0, variant: classic}]',
                      '--format', 'json', *paths], accepted=(0, 1))
    results = json.loads(output)
    by_path = {Path(row['filePath']): row for row in results}
    if len(by_path) != len(results) or set(by_path) != set(paths):
        raise ValueError('JavaScript analyzer file inventory mismatch')
    return by_path


def javascript_measurements(root, files, eslint):
    identity = installed_javascript(eslint)
    paths = [(root / name).absolute() for name in files]
    snapshots = {path: path.read_bytes() for path in paths}
    by_path = javascript_results(eslint, paths)
    records = [javascript_file(root, name, by_path[path], eslint) for name, path in zip(files, paths)]
    if any(path.read_bytes() != snapshots[path] for path in paths):
        raise ValueError('JavaScript source changed during analyzer execution')
    if installed_javascript(eslint) != identity:
        raise ValueError('Installed JavaScript analyzer changed during measurement')
    return dict(identity, files=records)


def javascript_file(root, name, result, eslint):
    content = (root / name).read_bytes()
    tree = json.loads(command(['node', eslint.parent / 'acorn/bin/acorn', '--module',
                               '--ecma2022', '--locations', root / name]))
    if result.get('fatalErrorCount') or result.get('suppressedMessages'):
        raise ValueError('Invalid or suppressed JavaScript measurements')
    records = javascript_records(result['messages'], tree, content.decode())
    if (root / name).read_bytes() != content:
        raise ValueError('JavaScript source changed during measurement')
    return {'path': name, 'sha256': digest(content), 'functions': records}
