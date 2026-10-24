"""CC-004: independent attribute-policy cases retained across template splits."""
from importlib.resources import files
import itertools
import random

from lxml import etree  # type: ignore[attr-defined]
import pytest

from articulous.engines import safe_xml_parser, safe_xslt_access_control

XSL = '{http://www.w3.org/1999/XSL/Transform}'
URL_NAMES = ('href', 'src', 'action', 'formaction', 'poster')
URL_VALUES = (
    ('https://example.test/a', True), ('http://example.test/a', True), ('/relative', True),
    ('#local', True), ('', True), ('JaVaScRiPt:alert(1)', False),
    (' j a v a s c r i p t : alert(1)', False), ('VB\tScript:run', False),
    ('data:text/html;base64,WA==', False),
)
DIMENSIONS = (('0', True), ('12', True), ('00012', True), ('', False), ('-1', False),
              ('1.0', False), ('100%', False), (' 2 ', False), ('１２', False), ('2\n', False))


def stylesheet_source():
    root = etree.fromstring(files('articulous').joinpath('theme_assets/xsl/content.xsl').read_bytes(),
                            parser=safe_xml_parser())
    entry = etree.SubElement(root, XSL + 'template', match='/')
    output = etree.SubElement(entry, 'out')
    etree.SubElement(output, XSL + 'apply-templates', select='root/node()', mode='content')
    return etree.tostring(root)


@pytest.fixture
def render():
    return etree.XSLT(etree.fromstring(stylesheet_source(), parser=safe_xml_parser()),
                      access_control=safe_xslt_access_control())


def rendered_attributes(render, parent, attribute, value):
    root = etree.Element('root')
    child = etree.SubElement(root, parent)
    child.set(attribute, value)
    result = render(root)
    return dict(result.getroot()[0].attrib)


@pytest.mark.parametrize('name', URL_NAMES)
@pytest.mark.parametrize('value,allowed', URL_VALUES)
def test_cc004_url_protocol_contract(render, name, value, allowed):
    result = rendered_attributes(render, 'a', name, value)
    assert (name in result) is allowed


@pytest.mark.parametrize('name', ['OnClick', 'ONLOAD', 'onfocus', 'style', 'Style', 'srcdoc', 'SRCDOC', '{urn:attrs}onclick'])
def test_cc004_active_attributes_are_rejected(render, name):
    assert not rendered_attributes(render, 'div', name, 'text')


@pytest.mark.parametrize('parent', ['img', 'IMG', 'div', '{urn:svg}img'])
@pytest.mark.parametrize('name', ['width', 'height', 'Width', '{urn:attrs}width'])
@pytest.mark.parametrize('value,valid_digits', DIMENSIONS)
def test_cc004_dimension_context_and_ascii_boundaries(render, parent, name, value, valid_digits):
    allowed = valid_digits and parent in ('img', 'IMG') and not name.startswith('{')
    assert (name in rendered_attributes(render, parent, name, value)) is allowed


@pytest.mark.parametrize('parent', ['img', 'IMG', 'div', '{urn:svg}img'])
@pytest.mark.parametrize('name', ['src', 'SRC', 'href', '{urn:attrs}src'])
def test_cc004_data_images_keep_original_context_contract(render, parent, name):
    allowed = parent in ('img', 'IMG', '{urn:svg}img') and name != 'href'
    value = 'DaTa:image/png;base64,WA=='
    assert (name in rendered_attributes(render, parent, name, value)) is allowed


@pytest.mark.parametrize('name', ['title', 'class', 'data-note', 'alt', '{urn:attrs}title'])
def test_cc004_unrelated_attributes_keep_literal_values(render, name):
    value = 'javascript: is text here'
    assert rendered_attributes(render, 'div', name, value) == {name: value}


def test_cc004_bounded_attribute_value_property(render):
    randomizer = random.Random(4004)
    for _ in range(64):
        number = str(randomizer.randrange(0, 2**63))
        parent = randomizer.choice(('img', 'IMG'))
        attribute = randomizer.choice(('width', 'height'))
        assert rendered_attributes(render, parent, attribute, number) == {attribute: number}
        invalid = number + randomizer.choice(('%', '-', 'x', 'é', '\t', ' '))
        assert not rendered_attributes(render, parent, attribute, invalid)


def native_packet():
    root = etree.Element('root')
    cases = itertools.product(('img', 'div'), URL_NAMES, URL_VALUES)
    for index, (parent, name, (value, _)) in enumerate(cases):
        child = etree.SubElement(root, parent, {'data-case': str(index), name: value})
        child.text = 'case'
    return etree.tostring(root)


def test_cc004_batch_preserves_element_order_and_identity(render):
    source = etree.fromstring(native_packet(), parser=safe_xml_parser())
    output = render(source).getroot()
    assert [node.get('data-case') for node in output] == [node.get('data-case') for node in source]
