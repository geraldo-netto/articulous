"""Independent XSLT 1.0 metric contract and immutable compiler results."""
from dataclasses import dataclass
from typing import Protocol

from .complexity_contracts import require_digest

XSL = 'http://www.w3.org/1999/XSL/Transform'
XSLT_METRIC = 'xslt1-control-xpath-v1'
MAX_STYLESHEET_BYTES = 1024 * 1024
MAX_AVT_EXPRESSIONS = 128
CONTROL = frozenset(('if', 'when', 'for-each'))
INSTRUCTIONS = frozenset(('stylesheet', 'transform', 'template', 'param', 'variable',
    'copy', 'copy-of', 'apply-templates', 'call-template', 'value-of', 'text',
    'choose', 'when', 'otherwise', 'if', 'for-each', 'attribute', 'element',
    'with-param', 'sort', 'number', 'comment', 'processing-instruction',
    'message', 'fallback'))
EXPRESSIONS = frozenset(('select', 'test', 'match', 'value', 'count', 'from'))
AVT_ATTRIBUTES = {'attribute': ('name', 'namespace'), 'element': ('name', 'namespace'),
    'processing-instruction': ('name',), 'sort': ('lang', 'data-type', 'order', 'case-order'),
    'number': ('format', 'lang', 'letter-value', 'grouping-separator', 'grouping-size')}
ATTRIBUTES = {
    'stylesheet': ('version', 'id', 'extension-element-prefixes', 'exclude-result-prefixes'),
    'transform': ('version', 'id', 'extension-element-prefixes', 'exclude-result-prefixes'),
    'template': ('name', 'match', 'mode', 'priority'), 'param': ('name', 'select'),
    'variable': ('name', 'select'), 'copy': ('use-attribute-sets',), 'copy-of': ('select',),
    'apply-templates': ('select', 'mode'), 'call-template': ('name',),
    'value-of': ('select', 'disable-output-escaping'), 'text': ('disable-output-escaping',),
    'choose': (), 'when': ('test',), 'otherwise': (), 'if': ('test',), 'for-each': ('select',),
    'attribute': ('name', 'namespace'), 'element': ('name', 'namespace', 'use-attribute-sets'),
    'with-param': ('name', 'select'), 'sort': ('select', 'lang', 'data-type', 'order', 'case-order'),
    'number': ('level', 'count', 'from', 'value', 'format', 'lang', 'letter-value',
               'grouping-separator', 'grouping-size'),
    'comment': (), 'processing-instruction': ('name',), 'message': ('terminate',), 'fallback': (),
}


@dataclass(frozen=True)
class XPathDecisions:
    booleans: int
    predicates: int
    compiler_version: str
    trace_sha256: str

    def __post_init__(self):
        require_count(self.booleans)
        require_count(self.predicates)
        if not isinstance(self.compiler_version, str) or not self.compiler_version.isdigit():
            raise ValueError('Invalid XPath compiler provenance')
        require_digest(self.trace_sha256)


def require_count(value):
    if type(value) is not int or not 0 <= value <= 65536:
        raise ValueError('Invalid XPath decision count')


class XPathCompiler(Protocol):
    def __call__(self, expression: str) -> XPathDecisions:
        ...
