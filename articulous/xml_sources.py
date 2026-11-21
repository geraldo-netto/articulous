"""Native safe-XML adapter; readers close before returning the owned source view."""
from functools import partial
import lxml.etree as etree
from .engines import reject_entity_references, safe_xml_parser
from .filesystem import open_regular_file
from .xml_contracts import XmlSource


def read_source(path):
    with open_regular_file(path) as stream:
        content = stream.read()
    base_uri = path.resolve().as_uri()
    root = etree.fromstring(content, parser=safe_xml_parser(), base_url=base_uri)
    reject_entity_references(root)
    serialize = partial(etree.tostring, root.getroottree(), encoding='utf-8', xml_declaration=True)
    return XmlSource(content, base_uri, root, serialize)
