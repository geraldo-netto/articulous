"""Native result adapter; XML/text keep their exact libxslt serialization.

libxslt HTML result documents expose no XML version, including explicit HTML
versions. Inferred HTML also requires the stylesheet graph to omit an explicit
method and the result to start with an unqualified html element. Native regression
controls bind both signals.
The transform owns the result tree; this synchronous call retains no native view.
HTML decoding, token spans and output add O(serialized length) temporary storage.
"""
import codecs
from ..html_serialization import omit_spans, void_omissions


def automatic_html(result):
    if result.getroot().tag.lower() != 'html':
        return False
    leading = result.xpath('/text()[not(preceding-sibling::*)]')
    return not any(text.strip() for text in leading)


def _byte_boundaries(content, encoding, positions):
    decoder = codecs.getincrementaldecoder(encoding)(errors='surrogateescape')
    offset = 0
    for end, byte in enumerate(content, 1):
        pending = len(decoder.getstate()[0])
        decoded = decoder.decode(bytes((byte,)))
        if not decoded:
            continue
        if offset in positions:
            positions[offset][0] = end - 1 - pending
        offset += len(decoded)
        if offset in positions:
            positions[offset][1] = end


def _native_spans(content, encoding, spans):
    bounds = {position: [None, None] for span in spans for position in span}
    _byte_boundaries(content, encoding, bounds)
    for start, end in spans:
        first, last = bounds[start][0], bounds[end][1]
        if first is None or last is None:
            raise ValueError(f'Cannot locate HTML tag boundaries in {encoding}')
        yield first, last


def _utf8_spans(source, spans):
    previous = offset = 0
    for start, end in spans:
        offset += len(source[previous:start].encode('utf-8', 'surrogateescape'))
        size = len(source[start:end].encode('utf-8', 'surrogateescape'))
        yield offset, offset + size
        previous, offset = end, offset + size


def _project_html(content, encoding):
    if encoding.lower() == 'windows-874':
        encoding = 'cp874'
    try:
        source = content.decode(encoding, errors='surrogateescape')
    except LookupError as error:
        raise ValueError(f'Unsupported HTML output encoding: {encoding}') from error
    spans = void_omissions(source)
    if not spans:
        return content
    if encoding.lower() in ('utf-8', 'utf8'):
        return omit_spans(content, _utf8_spans(source, spans))
    return omit_spans(content, _native_spans(content, encoding, spans))


def serialized_result(result, *, infer_html=False):
    content = bytes(result)
    if result.getroot() is None:
        return content
    html = result.docinfo.xml_version is None or infer_html and automatic_html(result)
    if not html:
        return content
    encoding = result.docinfo.encoding or 'UTF-8'
    return _project_html(content, encoding)
