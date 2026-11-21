"""HTML5 void-end projection over one caller-owned finite serialized document.

Only end-tag spans in HTML context are removed. Other bytes, including raw text,
comments and foreign markup, retain their order. One call owns its parser, stack,
line offsets and spans (O(document length)); nothing survives return/rejection.
"""
from html.parser import HTMLParser
import re
from string import ascii_lowercase, ascii_uppercase

VOID = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
RAW = frozenset('textarea title xmp iframe noembed noframes'.split())
MATH_TEXT = frozenset('mi mo mn ms mtext'.split())
_ASCII_LOWER = str.maketrans(ascii_uppercase, ascii_lowercase)
_RAW_NAME = re.compile(r'</?\s*([A-Za-z][^\t\n\r\f />]*)')
_END_TOKEN = re.compile(r"""(?:[^"'<>]|"[^"]*"|'[^']*')*>""")
_VOID_CANDIDATE = re.compile(r'</\s*(?ai:' + '|'.join(sorted(VOID)) + r')(?=[\t\n\r\f />]|$)')


def child_context(tag, namespace, attributes):
    if namespace == 'svg' and tag in ('foreignobject', 'desc', 'title'):
        return 'html'
    if namespace == 'math' and tag == 'annotation-xml':
        encoding = dict(attributes).get('encoding') or ''
        if encoding.lower() in ('text/html', 'application/xhtml+xml'):
            return 'html'
    if namespace == 'math' and tag in MATH_TEXT:
        return 'math-text'
    return namespace


class _VoidEnds(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0, *(match.end() for match in re.finditer('\n', source))]
        self.stack = []
        self.omissions = []
        self.plaintext = False
        self.omit_end = False

    def source_offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def raw_name(self):
        match = _RAW_NAME.match(self.source, self.source_offset())
        assert match is not None
        return match[1].translate(_ASCII_LOWER)

    def namespace(self, tag):
        context = self.stack[-1][1] if self.stack else 'html'
        if context == 'math-text':
            context = 'math' if tag in ('mglyph', 'malignmark') else 'html'
        if context == 'html' and tag in ('svg', 'math'):
            return tag
        return context

    def handle_starttag(self, tag, attrs):
        if self.plaintext:
            return
        tag = self.raw_name()
        namespace = self.namespace(tag)
        if namespace == 'html' and tag in VOID:
            return
        self.stack.append((tag, child_context(tag, namespace, attrs)))
        self.admit_text_mode(tag, namespace)

    def admit_text_mode(self, tag, namespace):
        if namespace != 'html':
            return
        if tag in RAW:
            self.set_cdata_mode(tag)
        if tag == 'plaintext':
            self.plaintext = True

    def handle_startendtag(self, tag, attrs):
        depth = len(self.stack)
        self.handle_starttag(tag, attrs)
        if len(self.stack) > depth:
            self.stack.pop()

    def parse_endtag(self, i):
        self.omit_end = False
        end = super().parse_endtag(i)
        if not self.omit_end:
            return end
        start = self.source_offset()
        token = _END_TOKEN.match(self.source, start + 2)
        if token is None:
            return end
        self.omissions.append((start, token.end()))
        return i + token.end() - start

    def handle_endtag(self, tag):
        if self.plaintext:
            return
        tag = self.raw_name()
        if self.namespace(tag) == 'html' and tag in VOID:
            self.omit_end = True
        elif self.stack and self.stack[-1][0] == tag:
            self.stack.pop()


def void_omissions(source):
    if not isinstance(source, str):
        raise ValueError('Serialized HTML must be text')
    if _VOID_CANDIDATE.search(source) is None:
        return ()
    parser = _VoidEnds(source)
    parser.feed(source)
    parser.close()
    return parser.omissions


def html5_void_ends(source):
    omissions = void_omissions(source)
    if not omissions:
        return source
    return omit_spans(source, omissions)


def omit_spans(source, omissions):
    parts = []
    position = 0
    for start, end in omissions:
        parts.append(source[position:start])
        position = end
    parts.append(source[position:])
    return source[:0].join(parts)
