"""Read or replace one scalar field in a caller-owned XML tree."""
import lxml.etree as etree


def _require_scalar(element):
    if any(child.tag is not etree.Comment for child in element):
        raise ValueError(f'<{element.tag}> must contain text only')


def scalar_text(element):
    if not len(element):
        return element.text or ''
    _require_scalar(element)
    return ''.join(element.itertext())


def set_scalar_text(element, value):
    _require_scalar(element)
    element.text = value
    for comment in element:
        comment.tail = None
