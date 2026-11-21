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
_VOID_CANDIDATE = re.compile(r'</(?ai:(' + '|'.join(sorted(VOID)) + r'))(?=[\t\n\r\f />]|$)')
_ATTR_GAP = re.compile(r'[\t\n\r\f /]*')
_ATTR_NAME = re.compile(r'[^\t\n\r\f />][^\t\n\r\f />=]*')
_ATTR_EQUALS = re.compile(r'[\t\n\r\f ]*=[\t\n\r\f ]*')
_BARE_VALUE = re.compile(r'[^\t\n\r\f >]*')
_SCRIPT_NAME = r'(?ai:script)(?=[\t\n\r\f />])'
_SCRIPT_END = rf'(?P<end></{_SCRIPT_NAME})'
_SCRIPT_EVENTS = {
    'data': re.compile(r'(?P<escaped><!(?=--))|' + _SCRIPT_END),
    'escaped': re.compile(rf'(?P<data>-->)|(?P<double><{_SCRIPT_NAME})|' + _SCRIPT_END),
    'double': re.compile(rf'(?P<data>-->)|(?P<escaped></{_SCRIPT_NAME})'),
}


def _value_end(source, position):
    quote = source[position:position + 1]
    if quote in ('"', "'"):
        close = source.find(quote, position + 1)
        return len(source) if close < 0 else close + 1
    bare = _BARE_VALUE.match(source, position)
    assert bare is not None
    return bare.end()


def _tag_end(source, position):
    while True:
        gap = _ATTR_GAP.match(source, position)
        assert gap is not None
        position = gap.end()
        name = _ATTR_NAME.match(source, position)
        if name is None:
            return position + 1 if source.startswith('>', position) else None
        equals = _ATTR_EQUALS.match(source, name.end())
        position = _value_end(source, equals.end()) if equals else name.end()


def _script_end(source, position):
    state = 'data'
    while event := _SCRIPT_EVENTS[state].search(source, position):
        position = event.end()
        if event.lastgroup == 'end':
            return _tag_end(source, position) or len(source)
        assert event.lastgroup is not None
        state = event.lastgroup
    return len(source)


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
        if len(self.stack) > depth and self.stack[-1] != ('script', 'html'):
            self.stack.pop()

    def parse_starttag(self, i):
        end = super().parse_starttag(i)
        if end >= 0 and self.stack and self.stack[-1] == ('script', 'html'):
            self.stack.pop()
            self.clear_cdata_mode()
            return _script_end(self.rawdata, end)
        return end

    def parse_endtag(self, i):
        match = _VOID_CANDIDATE.match(self.rawdata, i)
        if match is None or self.plaintext or self.namespace(match[1].lower()) != 'html':
            return super().parse_endtag(i)
        end = _tag_end(self.rawdata, match.end())
        if end is None:
            return len(self.rawdata)
        start = self.source_offset()
        self.omissions.append((start, start + end - i))
        return end

    def handle_endtag(self, tag):
        if self.plaintext:
            return
        tag = self.raw_name()
        if self.stack and self.stack[-1][0] == tag:
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
