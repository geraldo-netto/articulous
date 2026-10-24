"""Source-bound XSLT 1.0 control-flow and native XPath complexity measurement."""
import argparse
from dataclasses import asdict
from functools import lru_cache
import json
from pathlib import Path
import re

from lxml import etree  # type: ignore[attr-defined]

from .complexity_python import digest
from .complexity_xslt_calibration import calibrate, check_calibration
from .complexity_xslt_contracts import (
    ATTRIBUTES, AVT_ATTRIBUTES, CONTROL, EXPRESSIONS, INSTRUCTIONS, LITERAL_ATTRIBUTES, MAX_AVT_EXPRESSIONS,
    MAX_STYLESHEET_BYTES, XSL, XSLT_METRIC, XPathCompiler, XPathDecisions,
)
from .engines import safe_xml_parser, safe_xslt_access_control
from .filesystem import write_text_atomic

EVIDENCE = 'reviews/complexity/xslt.json'
DIRECTORY = 'articulous/theme_assets/xsl'
AVT_TOKEN = re.compile(r'''\{\{|\}\}|\{(?:[^{}'"]|'[^']*'|"[^"]*")*\}|[^{}]+''')


def avt_expressions(value):
    offset, result = 0, []
    while offset < len(value):
        match = AVT_TOKEN.match(value, offset)
        if match is None:
            raise ValueError('Invalid XSLT attribute value template')
        token, offset = match[0], match.end()
        if token.startswith('{') and token != '{{':
            result.append(token[1:-1])
            if len(result) > MAX_AVT_EXPRESSIONS:
                raise ValueError('XSLT AVT expression capacity exceeded')
    return result


def require_instruction(node):
    name = etree.QName(node)
    if name.namespace == XSL:
        if name.localname not in INSTRUCTIONS:
            raise ValueError('Unsupported XSLT instruction: ' + name.localname)
        require_attributes(node, name.localname)
    else:
        require_literal_attributes(node)
    require_extensions(node)


def require_attributes(node, instruction):
    for key in node.attrib:
        name = etree.QName(key)
        if name.namespace == XSL or (name.namespace is None and key not in ATTRIBUTES[instruction]):
            raise ValueError('Unsupported XSLT attribute: ' + key)


def require_literal_attributes(node):
    for key in node.attrib:
        name = etree.QName(key)
        if name.namespace == XSL and name.localname not in LITERAL_ATTRIBUTES:
            raise ValueError('Unsupported XSLT literal metadata: ' + key)


def require_extensions(node):
    key = 'extension-element-prefixes' if etree.QName(node).namespace == XSL else '{' + XSL + '}extension-element-prefixes'
    extension = node.get(key)
    if extension:
        raise ValueError('XSLT extension instructions are unsupported')
    if node.get('{' + XSL + '}version') not in (None, '1.0'):
        raise ValueError('XSLT forward-compatible instructions are unsupported')


def require_root(root):
    if root.tag not in ('{' + XSL + '}stylesheet', '{' + XSL + '}transform') or root.get('version') != '1.0':
        raise ValueError('Only explicit XSLT 1.0 stylesheets are supported')
    if root.getroottree().docinfo.doctype:
        raise ValueError('DTD-bearing XSLT is unsupported')
    for node in root:
        if isinstance(node.tag, str) and node.tag != '{' + XSL + '}template':
            raise ValueError('Non-template XSLT top-level declarations are unsupported')


def parse_stylesheet(content):
    if not isinstance(content, bytes) or len(content) > MAX_STYLESHEET_BYTES:
        raise ValueError('XSLT source capacity exceeded')
    root = etree.fromstring(content, parser=safe_xml_parser())
    require_root(root)
    for node in root.iter():
        if isinstance(node.tag, str):
            require_instruction(node)
    etree.XSLT(root, access_control=safe_xslt_access_control())
    return root


def attribute_expressions(node):
    name = etree.QName(node)
    if name.namespace == XSL:
        for key, value in node.attrib.items():
            if key in EXPRESSIONS:
                yield key, value
    for key in avt_keys(node, name):
        for value in avt_expressions(node.get(key, '')):
            yield key, value


def avt_keys(node, name):
    if name.namespace == XSL:
        return AVT_ATTRIBUTES.get(name.localname, ())
    return tuple(key for key in node.attrib if etree.QName(key).namespace != XSL)


def template_records(template, compiler: XPathCompiler):
    controls, expressions = [], []
    for node in template.iter():
        if not isinstance(node.tag, str):
            continue
        name = etree.QName(node)
        if name.namespace == XSL and name.localname in CONTROL:
            controls.append({'line': node.sourceline, 'instruction': name.localname})
        for key, value in attribute_expressions(node):
            result = compiler(value)
            expressions.append(dict(asdict(result), line=node.sourceline, attribute=key, source=value))
    return controls, expressions


def measure_template(template, compiler):
    controls, expressions = template_records(template, compiler)
    name = template.get('name') or 'match=' + template.get('match', '') + ';mode=' + template.get('mode', '')
    return {'name': name, 'line': template.sourceline,
            'sha256': digest(etree.tostring(template, with_tail=False)),
            'complexity': 1 + len(controls) + sum(row['booleans'] + row['predicates'] for row in expressions),
            'controls': controls, 'expressions': expressions}


def measure_source(content, compiler):
    root = parse_stylesheet(content)
    cached = lru_cache(maxsize=256)(compiler)
    return [measure_template(node, cached) for node in root.findall('{' + XSL + '}template')]


def source_paths(root):
    return sorted(path.relative_to(root).as_posix() for path in (root / DIRECTORY).rglob('*.xsl'))


def measured_report(root, compiler):
    calibration = calibrate(compiler, measure_source)
    files = []
    for name in source_paths(root):
        content = (root / name).read_bytes()
        records = measure_source(content, compiler)
        if (root / name).read_bytes() != content:
            raise ValueError('XSLT source changed during measurement')
        files.append({'path': name, 'sha256': digest(content), 'templates': records})
    return {'schema': 1, 'metric': XSLT_METRIC, 'calibration': calibration, 'files': files}


def recorded_compiler(records):
    values = {}
    for row in records:
        result = XPathDecisions(**{key: row[key] for key in XPathDecisions.__dataclass_fields__})
        if row['source'] in values and values[row['source']] != result:
            raise ValueError('Conflicting XPath compiler evidence')
        values[row['source']] = result
    return values.__getitem__


def check_file(root, entry):
    content = (root / entry['path']).read_bytes()
    if digest(content) != entry['sha256']:
        raise ValueError('Stale XSLT source evidence')
    expressions = [row for template in entry['templates'] for row in template['expressions']]
    expected = measure_source(content, recorded_compiler(expressions))
    if entry['templates'] != expected:
        raise ValueError('XSLT template inventory or measurement changed')
    return [f'{entry["path"]}:{row["name"]}: complexity {row["complexity"]} exceeds 9'
            for row in expected if row['complexity'] > 9]


def check_report(root, report):
    if report['schema'] != 1 or report['metric'] != XSLT_METRIC:
        raise ValueError('Unsupported XSLT complexity metric')
    if [entry['path'] for entry in report['files']] != source_paths(root):
        raise ValueError('XSLT source inventory changed')
    version = check_calibration(report['calibration'])
    require_compiler_version(report['files'], version)
    failures = [message for entry in report['files'] for message in check_file(root, entry)]
    if failures:
        raise ValueError('\n'.join(failures))
    return sum(len(entry['templates']) for entry in report['files'])


def require_compiler_version(files, version):
    versions = {row['compiler_version'] for entry in files for template in entry['templates']
                for row in template['expressions']}
    if versions - {version}:
        raise ValueError('Native XPath compiler changed during measurement')


def main(argv=None):
    from .complexity_gate import load_json
    from .complexity_xpath import compile_xpath

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('measure', 'check'))
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--report', type=Path, default=Path(EVIDENCE))
    args = parser.parse_args(argv)
    if args.mode == 'measure':
        report = measured_report(args.root, compile_xpath)
        write_text_atomic(args.report, json.dumps(report, indent=2, sort_keys=True) + '\n')
    count = check_report(args.root, load_json(args.report))
    print(f'{count} source-bound XSLT templates accepted by {XSLT_METRIC}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
