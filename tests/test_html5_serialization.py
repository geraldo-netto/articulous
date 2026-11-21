"""HTML5-001 / Morpha REV-197: native HTML output uses HTML5 void syntax."""
import lxml.etree as etree
import pytest
from articulous.engines import LxmlEngine


def render(tmp_path, body, output='method="html" encoding="UTF-8"'):
    source = ('<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">'
              f'<xsl:output {output}/><xsl:template match="/">{body}</xsl:template></xsl:stylesheet>')
    stylesheet = tmp_path / 'style.xsl'
    stylesheet.write_text(source)
    destination = tmp_path / 'output'
    LxmlEngine().run(b'<input/>', stylesheet, destination)
    return destination.read_bytes()


@pytest.mark.parametrize('tag', ['source', 'track', 'wbr', 'embed', 'SOURCE'])
def test_html5_001_native_void_elements_have_no_end_tag(tmp_path, tag):
    output = render(tmp_path, f'<html><body><{tag} title="é"/><p>after</p></body></html>')
    assert f'</{tag}>'.encode() not in output
    assert f'<{tag} title="'.encode() in output
    assert b'<p>after</p>' in output


@pytest.mark.parametrize('encoding', ['UTF-8', 'ISO-8859-1', 'UTF-16', 'UTF-16BE', 'UTF-32'])
def test_html5_001_encoding_and_non_ascii_content_survive(tmp_path, encoding):
    output = render(tmp_path, '<html><body><source/><p>ação — è</p></body></html>',
                    f'method="html" encoding="{encoding}"')
    decoded = output.decode(encoding)
    assert '</source>' not in decoded
    assert 'a' in decoded
    parsed = etree.HTML(output, parser=etree.HTMLParser(encoding=encoding))
    assert parsed.xpath('string(//p)') == 'ação — è'


@pytest.mark.parametrize('method', ['xml', 'text'])
def test_html5_001_other_output_methods_stay_exact(tmp_path, method):
    body = '<html><source/><xsl:text>&lt;/source&gt;</xsl:text></html>'
    actual = render(tmp_path, body, f'method="{method}" encoding="UTF-8"')
    stylesheet = etree.parse(str(tmp_path / 'style.xsl'))
    expected = bytes(etree.XSLT(stylesheet)(etree.XML('<input/>')))
    assert actual == expected


def test_html5_001_literal_text_comments_and_foreign_elements_survive(tmp_path):
    body = ('<html><body><source/>'
            '<script>const text = "&lt;/source&gt;";</script>'
            '<style>p::before {content:"&lt;/source&gt;"}</style>'
            '<textarea>&lt;/source&gt;</textarea>'
            '<xsl:comment>&lt;/source&gt;</xsl:comment>'
            '<svg xmlns="http://www.w3.org/2000/svg"><source>foreign</source>'
            '<foreignObject><source xmlns=""/></foreignObject></svg>'
            '</body></html>')
    output = render(tmp_path, body).decode()
    assert '<source></source>' not in output
    assert 'const text = "</source>";' in output
    assert 'content:"</source>"' in output
    assert '<textarea>&lt;/source&gt;</textarea>' in output
    assert '<!--</source>-->' in output
    assert '<source>foreign</source>' in output


def test_html5_001_implicit_html_method_and_cache_identity(tmp_path):
    assert b'</source>' not in render(tmp_path, '<html><source/></html>', 'encoding="UTF-8"')
    assert 'serialization=v5' in LxmlEngine().cache_identity


@pytest.mark.parametrize('body', ['<xsl:text>only text</xsl:text>',
                                 '<xsl:text>prefix</xsl:text><html><source/></html>',
                                 '<root><source/></root>'])
def test_html5_001_non_html_implicit_output_stays_native(tmp_path, body):
    actual = render(tmp_path, body, 'encoding="UTF-8"')
    expected = bytes(etree.XSLT(etree.parse(str(tmp_path / 'style.xsl')))(etree.XML('<input/>')))
    assert actual == expected


@pytest.mark.parametrize('kind', ['include', 'import'])
def test_html5_001_explicit_dependency_method_prevents_html_inference(tmp_path, kind):
    common = tmp_path / 'common.xsl'
    common.write_text('<xsl:transform xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">'
                      '<xsl:output method="xml" omit-xml-declaration="yes"/></xsl:transform>')
    root = tmp_path / 'root.xsl'
    root.write_text('<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">'
                    f'<xsl:{kind} href="common.xsl"/>'
                    '<xsl:template match="/"><html><source/></html></xsl:template></xsl:stylesheet>')
    target = tmp_path / 'output'
    LxmlEngine().run(b'<input/>', root, target)
    assert target.read_bytes() == b'<html><source/></html>\n'


def test_html5_001_serialization_failure_keeps_prior_output(tmp_path, monkeypatch):
    from articulous.backends import lxml_output
    from articulous.transform_contracts import TransformFailure
    render(tmp_path, '<html><p>previous</p></html>')
    output = tmp_path / 'output'
    previous = output.read_bytes()

    def rejected(_source):
        raise ValueError('injected serialization rejection')

    monkeypatch.setattr(lxml_output, 'void_omissions', rejected)
    with pytest.raises(TransformFailure, match='serialization rejection'):
        render(tmp_path, '<html><source/></html>')
    assert output.read_bytes() == previous


@pytest.mark.parametrize(('source', 'expected'), [
    ('<p><linK a="1"></linK></p>', '<p><linK a="1"></linK></p>'),
    ('<p><lİnk></lİnk></p>', '<p><lİnk></lİnk></p>'),
    ('<p><BR></BR></p>', '<p><BR></p>'),
    ('<p><br></br\t></p>', '<p><br></p>'),
    ('<svg><linK><br></br></linK></svg>', '<svg><linK><br></br></linK></svg>'),
])
def test_rel03_void_tag_membership_uses_ascii_folding(source, expected):
    from articulous.html_serialization import html5_void_ends

    assert html5_void_ends(source) == expected


@pytest.mark.parametrize('encoding', ['UTF-8', 'UTF-16'])
def test_rel03_native_html_preserves_non_ascii_end_tag(tmp_path, encoding):
    body = ('<html><body><xsl:element name="linK"><xsl:text>inside</xsl:text>'
            '</xsl:element><p>after</p></body></html>')
    output = render(tmp_path, body, f'method="html" encoding="{encoding}"').decode(encoding)
    assert '<linK>inside</linK>' in output
    assert '<p>after</p>' in output


def test_rel41_quoted_greater_than_ends_with_the_full_token():
    from articulous.html_serialization import html5_void_ends

    assert html5_void_ends('<p>before</br a=">">after</p>') == '<p>beforeafter</p>'


@pytest.mark.parametrize('void', ['', '<source/>'])
@pytest.mark.parametrize('encoding', ['EUC-JP', 'windows-874', 'utf-8-sig'])
def test_review28_02_unmodified_native_bytes_survive(tmp_path, encoding, void):
    body = f'<html><p>10時～12時</p>{void}</html>'
    actual = render(tmp_path, body, f'method="html" encoding="{encoding}"')
    native = bytes(etree.XSLT(etree.parse(str(tmp_path / 'style.xsl')))(etree.XML('<input/>')))
    assert actual == native.replace(b'</source>', b'')


@pytest.mark.parametrize('tag', ['colgroup', 'metadata', 'basefont'])
def test_review28_03_void_prefix_skips_parser(tag):
    from articulous.html_serialization import html5_void_ends
    source = f'<{tag}></{tag}>'
    assert html5_void_ends(source) is source


def test_review28_01_stylesheet_entity_rejected(tmp_path):
    from articulous.transform_contracts import TransformFailure
    style = tmp_path / 'style.xsl'
    style.write_text('<!DOCTYPE xsl:stylesheet [<!ENTITY word "example">]>'
                     '<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">'
                     '<xsl:template match="/"><p>before &word; after</p></xsl:template></xsl:stylesheet>')
    with pytest.raises(TransformFailure, match='entity reference'):
        LxmlEngine().run(b'<root/>', style, tmp_path / 'page')


def test_review28_02_unavailable_codec_fails_at_adapter_boundary(tmp_path, monkeypatch):
    from articulous.backends import lxml_output
    from articulous.transform_contracts import TransformFailure
    project = lxml_output._project_html
    monkeypatch.setattr(lxml_output, '_project_html', lambda content, _: project(content, 'nonexistent-codec'))
    with pytest.raises(TransformFailure, match='Unsupported HTML output encoding'):
        render(tmp_path, '<html><source/></html>')


def test_review28_02_unaddressable_multichar_boundary_fails_closed():
    from articulous.backends.lxml_output import _native_spans
    data = b'+ADwALwBiAHIAPg-'
    assert data.decode('utf-7') == '</br>'
    with pytest.raises(ValueError, match='Cannot locate HTML tag boundaries'):
        list(_native_spans(data, 'utf-7', [(1, 4)]))
