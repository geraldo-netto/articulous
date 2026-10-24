"""Adapter from isolated native XPath traces to source-independent decisions."""
import json
from pathlib import Path
import re
import sys

from .backends import xpath as worker
from .complexity_native import command
from .complexity_python import digest
from .complexity_xslt_contracts import XPathDecisions

OPERATIONS = frozenset(('END', 'AND', 'OR', 'EQUAL', 'CMP', 'PLUS', 'MULT',
    'UNION', 'ROOT', 'NODE', 'RESET', 'COLLECT', 'ELEM', 'VARIABLE', 'FUNCTION',
    'ARG', 'PREDICATE', 'FILTER', 'SORT'))
HEADER = re.compile(r'Compiled Expression : ([0-9]+) elements')
OPERATION = re.compile(r' +([A-Z]+)(?: .*|$)')


def operations(payload):
    if not isinstance(payload, str) or len(payload.encode()) > worker.MAX_TRACE_BYTES:
        raise ValueError('Invalid native XPath trace capacity')
    lines = payload.splitlines()
    if lines == ['Streaming Expression']:
        return []
    if not lines or HEADER.fullmatch(lines[0]) is None:
        raise ValueError('Unknown native XPath trace header')
    result = [operation(line) for line in lines[1:]]
    if not result:
        raise ValueError('Missing native XPath operations')
    return result


def operation(line):
    match = OPERATION.fullmatch(line)
    if match is None or match[1] not in OPERATIONS:
        raise ValueError('Unknown native XPath operation: ' + line)
    return match[1]


def decisions(result):
    if not isinstance(result.get('version'), str) or not result['version'].isdigit():
        raise ValueError('Missing native XPath compiler provenance')
    rows = operations(result['trace'])
    return XPathDecisions(sum(row in ('AND', 'OR') for row in rows),
                          sum(row in ('PREDICATE', 'FILTER') for row in rows),
                          result['version'], digest(result['trace'].encode()))


def compile_xpath(expression):
    worker.require_expression(expression)
    path = Path(worker.__file__)
    return decisions(json.loads(command([sys.executable, path, '--', expression])))
