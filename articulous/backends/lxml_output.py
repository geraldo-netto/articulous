"""Native result adapter; XML/text keep their exact libxslt serialization.

libxslt HTML result documents expose no XML version, including explicit HTML
versions. Inferred HTML also requires the stylesheet graph to omit an explicit
method and the result to start with an unqualified html element. Native regression
controls bind both signals.
The transform owns the result tree; this synchronous call retains no native view.
HTML decoding, token spans and output add O(serialized length) temporary storage.
"""
from ..html_serialization import html5_void_ends


def automatic_html(result):
    if result.getroot().tag.lower() != 'html':
        return False
    leading = result.xpath('/text()[not(preceding-sibling::*)]')
    return not any(text.strip() for text in leading)


def serialized_result(result, *, infer_html=False):
    content = bytes(result)
    if result.getroot() is None:
        return content
    html = result.docinfo.xml_version is None or infer_html and automatic_html(result)
    if not html:
        return content
    encoding = result.docinfo.encoding or 'UTF-8'
    return html5_void_ends(content.decode(encoding)).encode(encoding)
