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
    assert 'serialization=v3' in LxmlEngine().cache_identity


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

    monkeypatch.setattr(lxml_output, 'html5_void_ends', rejected)
    with pytest.raises(TransformFailure, match='serialization rejection'):
        render(tmp_path, '<html><source/></html>')
    assert output.read_bytes() == previous
