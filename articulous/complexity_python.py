"""Optional Lizard adapter; analyze lexical Python scopes without executing them."""
import argparse
import ast
from copy import deepcopy
import hashlib
import importlib
import importlib.metadata
import io
import json
from pathlib import Path
import subprocess
import tokenize

BASELINE = 'd879c1c3b8f5523fc41dc9ebf4e54a2934411ac3'


def digest(content):
    return hashlib.sha256(content).hexdigest()


def identity_fields(node):
    for name, value in ast.iter_fields(node):
        if name == 'type_params' and not value:
            continue
        yield name, value


def ast_identity(node):
    if isinstance(node, ast.AST):
        return type(node).__name__ + '(' + ','.join(name + '=' + ast_identity(value)
            for name, value in identity_fields(node)) + ')'
    if isinstance(node, list):
        return '[' + ','.join(ast_identity(value) for value in node) + ']'
    return repr(node)


def definitions(node, prefix=''):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from definitions(child, prefix + child.name + '.')
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            name = getattr(child, 'name', f'<lambda>@{child.lineno}:{child.col_offset}')
            yield prefix + name, child
            yield from definitions(child, prefix + name + '.')
        else:
            yield from definitions(child, prefix)


def definition_inputs(node):
    if isinstance(node, ast.ClassDef):
        return [*node.decorator_list, *node.bases, *(item.value for item in node.keywords)]
    return [*getattr(node, 'decorator_list', []), *node.args.defaults,
            *(item for item in node.args.kw_defaults if item is not None),
            *argument_annotations(node.args), *return_annotation(node)]


def argument_annotations(arguments):
    values = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg]
    return [item.annotation for item in values if item is not None and item.annotation is not None]


def return_annotation(node):
    value = getattr(node, 'returns', None)
    return [] if value is None else [value]


def require_supported(node):
    if any(isinstance(item, (ast.Match, ast.TryStar)) for item in ast.walk(node)):
        raise ValueError('Unsupported Python decision syntax')
    if any(getattr(item, 'type_params', None) for item in ast.walk(node)):
        raise ValueError('Unsupported Python generic declarations')


class LexicalBody(ast.NodeTransformer):
    def definition(self, node):
        return [ast.Expr(self.visit(value)) for value in definition_inputs(node)] or [ast.Pass()]

    def visit_FunctionDef(self, node):
        return self.definition(node)

    def visit_AsyncFunctionDef(self, node):
        return self.definition(node)

    def visit_ClassDef(self, node):
        return self.definition(node)

    def visit_Lambda(self, node):
        return ast.Tuple([*(self.visit(value) for value in definition_inputs(node)), ast.Constant(None)], ast.Load())

    def visit_JoinedStr(self, node):
        return ast.Tuple([self.visit(value) for value in node.values], ast.Load())

    def visit_FormattedValue(self, node):
        values = [self.visit(node.value)]
        if node.format_spec is not None:
            values.append(self.visit(node.format_spec))
        return ast.Tuple(values, ast.Load())


def projection(node):
    require_supported(node)
    template = ast.parse('def measurement():\n    pass\n').body[0]
    if isinstance(node, ast.AsyncFunctionDef):
        template = ast.parse('async def measurement():\n    pass\n').body[0]
    assert isinstance(template, (ast.FunctionDef, ast.AsyncFunctionDef))
    body: list[ast.stmt] = [ast.Return(deepcopy(node.body))] if isinstance(node, ast.Lambda) else deepcopy(node.body)
    header = [ast.Expr(deepcopy(value)) for value in definition_inputs(node)]
    isolated = LexicalBody().visit(ast.Module(header + body, []))
    assert isinstance(isolated, ast.Module)
    template.body = isolated.body
    return ast.unparse(ast.fix_missing_locations(template)) + '\n'


def python_text(content):
    if isinstance(content, str):
        return content
    encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
    return content.decode(encoding)


def function_identity(name, node, source):
    segment = ast.get_source_segment(source, node)
    if segment is None:
        raise ValueError('Python callable has no source boundary')
    identity = ast_identity(node) + '\0' + segment
    return {'name': name, 'line': node.lineno, 'column': node.col_offset,
            'end_line': node.end_lineno, 'end_column': node.end_col_offset,
            'body_sha256': digest(identity.encode())}


def measure_function(analyzer, name, node, original):
    source = projection(node)
    measured = analyzer.analyze_file.analyze_source_code('projection.py', source).function_list
    tree = ast.parse(source).body[0]
    matches = [row for row in measured if row.name == 'measurement'
               and row.start_line == tree.lineno and row.end_line == tree.end_lineno]
    if len(measured) != 1 or len(matches) != 1:
        raise ValueError('Lizard did not measure the complete isolated callable')
    return dict(function_identity(name, node, original), complexity=matches[0].cyclomatic_complexity,
                projection_sha256=digest(ast_identity(ast.parse(source)).encode()))


def measure_source(analyzer, source):
    source = python_text(source)
    return [measure_function(analyzer, name, node, source) for name, node in definitions(ast.parse(source))]


CALIBRATIONS = (
    ('straight', 'def f():\n return 1\n', [1]),
    ('choices', 'def f(a,b,c):\n if a and b or c:\n  return 1\n return 0\n', [4]),
    ('nested', 'def outer():\n def inner(x):\n  return 1 if x else 2\n return inner\n', [1, 2]),
    ('lambda', 'def outer():\n return lambda x: 1 if x else 2\n', [1, 2]),
    ('definition-input', 'def outer(x):\n def inner(y=1 if x else 2):\n  return y\n return inner\n', [2, 2]),
    ('header', '@(first if flag else second)\ndef f(value=1 if flag else 2):\n return value\n', [3]),
    ('format-string', 'def f(x):\n return f"{1 if x else 2:{3 if x else 4}}"\n', [3]),
    ('annotations', 'def f(x: 1 if flag else 2) -> (3 if flag else 4):\n return x\n', [3]),
    ('comprehension', 'def f(xs):\n return [x for x in xs if x]\n', [3]),
    ('exceptions', 'def f():\n try:\n  return 1\n except ValueError:\n  return 2\n finally:\n  pass\n', [3]),
    ('async', 'async def f(x):\n if x:\n  await x\n', [2]),
    ('syntax-boundary', 'def f():\n class C:\n  def m(self): return "if or while"\n return C\n', [1, 1]),
    ('threshold-boundary', 'def f(xs):\n' + ' if xs:\n  pass\n' * 8, [9]),
)


def calibrate(analyzer):
    records = []
    for name, source, expected in CALIBRATIONS:
        actual = [row['complexity'] for row in measure_source(analyzer, source)]
        if actual != expected:
            raise ValueError('Lizard calibration failed: ' + name)
        records.append({'name': name, 'source': source, 'expected': expected, 'actual': actual})
    return records


def installed_analyzer():
    return importlib.import_module('lizard'), importlib.metadata.version('lizard')


def baseline_inventory(root, files):
    listing = subprocess.run(['git', '-C', str(root), 'ls-tree', '-rz', '--name-only', BASELINE],
                             capture_output=True, check=True).stdout.decode().split('\0')
    present = set(listing)
    result = {}
    for name in files:
        if name not in present:
            continue
        source = python_text(subprocess.run(['git', '-C', str(root), 'show', BASELINE + ':' + name],
                                capture_output=True, check=True).stdout)
        result[name] = {label: function_identity(label, node, source)['body_sha256']
                        for label, node in definitions(ast.parse(source))}
    return {'revision': BASELINE, 'functions': result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('files', nargs='+')
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args(argv)
    if args.baseline:
        print(json.dumps(baseline_inventory(args.root, args.files)))
        return 0
    analyzer, version = installed_analyzer()
    calibration = calibrate(analyzer)
    records = []
    for name in args.files:
        content = (args.root / name).read_bytes()
        records.append({'path': name, 'sha256': digest(content),
                        'functions': measure_source(analyzer, content)})
    print(json.dumps({'analyzer': 'Lizard', 'version': version, 'calibration': calibration,
                      'files': records}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
