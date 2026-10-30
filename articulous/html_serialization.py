"""HTML5 void-end projection over one caller-owned finite serialized document.

Only end-tag spans in HTML context are removed. Other bytes, including raw text,
comments and foreign markup, retain their order. One call owns its parser, stack,
line offsets and spans (O(document length)); nothing survives return/rejection.
"""
from html.parser import HTMLParser
import re

VOID = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
RAW = frozenset('textarea title xmp iframe noembed noframes'.split())
MATH_TEXT = frozenset('mi mo mn ms mtext'.split())


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

    def handle_endtag(self, tag):
        if self.plaintext:
            return
        if self.namespace(tag) == 'html' and tag in VOID:
            line, column = self.getpos()
            start = self.lines[line - 1] + column
            self.omissions.append((start, self.source.index('>', start) + 1))
        elif self.stack and self.stack[-1][0] == tag:
            self.stack.pop()


def html5_void_ends(source):
    if not isinstance(source, str):
        raise ValueError('Serialized HTML must be text')
    parser = _VoidEnds(source)
    parser.feed(source)
    parser.close()
    parts = []
    position = 0
    for start, end in parser.omissions:
        parts.append(source[position:start])
        position = end
    parts.append(source[position:])
    return ''.join(parts)
