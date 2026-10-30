"""Native safe-XML adapter; readers close before returning the owned source view."""
from functools import partial
from lxml import etree
from .engines import safe_xml_parser
from .filesystem import open_regular_file
from .xml_contracts import XmlSource


def read_source(path):
    with open_regular_file(path) as stream:
        content = stream.read()
    base_uri = path.resolve().as_uri()
    root = etree.fromstring(content, parser=safe_xml_parser(), base_url=base_uri)
    serialize = partial(etree.tostring, root.getroottree(), encoding='utf-8', xml_declaration=True)
    return XmlSource(content, base_uri, root, serialize)
