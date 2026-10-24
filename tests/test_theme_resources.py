"""THEME-001: installed resource provenance and neutral Articulous rendering."""
import hashlib
import re
import random
from importlib.resources import files
import lxml.etree as etree
import lxml.html as html
import pytest
from articulous.engines import LxmlEngine
from articulous.theme_resources import code_resources, prism_provenance


def test_theme001_one_owner_and_pinned_dependency_bytes():
    root = files('articulous').joinpath('theme_assets')
    manifest = prism_provenance()
    assert manifest['version'] == '1.30.0'
    assert manifest['approved_dependency_boundary']
    for name, expected in manifest['files'].items():
        assert hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest() == expected
    assert root.joinpath(manifest['patch']).read_text().startswith('--- prismjs-1.30.0/')
    resources = tuple(code_resources())
    assert len({entry.path for entry in resources}) == len(resources)
    assert any(entry.path.endswith('content.xsl') for entry in resources)
    assert root.joinpath('contracts/code-blocks.d.ts').read_text().find('CodeBlockController') >= 0


def neutral_stylesheet(tmp_path):
    for resource in code_resources():
        target = tmp_path / resource.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(resource.content)
    stylesheet = tmp_path / 'neutral.xsl'
    stylesheet.write_text('''<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
<xsl:include href="xsl/components/articulous/content.xsl"/>
<xsl:template match="/"><html><body><xsl:apply-templates select="root/node()" mode="content"/></body></html></xsl:template>
<xsl:template match="pre" mode="content"><xsl:call-template name="render-code-block"><xsl:with-param name="copy-label" select="'Copiar'"/><xsl:with-param name="success-label" select="'Listo'"/><xsl:with-param name="error-label" select="'Error'"/></xsl:call-template></xsl:template>
<xsl:template match="p" mode="content"><xsl:call-template name="render-paragraph"><xsl:with-param name="paragraph-class" select="'paragraph'"/></xsl:call-template></xsl:template>
</xsl:stylesheet>''')
    return stylesheet


def test_theme001_neutral_sanitized_rendering(tmp_path):
    stylesheet = neutral_stylesheet(tmp_path)
    output = tmp_path / 'neutral.html'
    LxmlEngine().run(b'<root><p onclick="bad()">Safe</p><p><div>Block</div></p><script>bad()</script><a href="javascript:bad()">Link</a><pre><code>\n  exact &amp; text<br/>next\n</code></pre></root>', stylesheet, output)
    document = html.parse(str(output))
    assert not document.xpath('//script | //@onclick | //a/@href')
    assert document.xpath('string(//pre)') == '  exact & text\nnext\n'
    assert document.xpath('//pre/@data-prismjs-copy') == ['Copiar']
    assert document.xpath('//div/@class') == ['paragraph ']


@pytest.mark.parametrize('text', ['', ' \t', '\n', ' \n\t\n  exact\n',
                                 '\n' * 5000 + '  example\n', ' \t\n' * 5000,
                                 '\n' + '日本😀' * 65536],
                         ids=['empty', 'spaces', 'newline', 'mixed', 'many-lines', 'all-blank', 'wide-unicode'])
def test_review006_leading_lines_have_bounded_recursion(tmp_path, text):
    root = etree.Element('root')
    etree.SubElement(root, 'pre').text = text
    output = tmp_path / 'rendered.html'
    LxmlEngine().run(etree.tostring(root), neutral_stylesheet(tmp_path), output)
    document = html.parse(str(output), parser=html.HTMLParser(encoding='utf-8'))
    assert document.xpath('string(//pre)') == re.sub(r'^(?:[ \t\r]*\n)+', '', text)


def test_review006_wide_markup_preserves_nodes_without_linear_recursion(tmp_path):
    root = etree.Element('root')
    pre = etree.SubElement(root, 'pre')
    for number in range(4096):
        etree.SubElement(pre, 'span', id=f'line-{number}').text = '\n'
    etree.SubElement(pre, 'b').text = '  code & text\n'
    output = tmp_path / 'rendered.html'
    LxmlEngine().run(etree.tostring(root), neutral_stylesheet(tmp_path), output)
    document = html.parse(str(output))
    assert document.xpath('string(//pre)') == '  code & text\n'
    assert document.xpath('//pre/span/@id') == [f'line-{number}' for number in range(4096)]
    assert document.xpath('string(//pre/b)') == '  code & text\n'


def test_review006_seeded_text_and_markup_boundaries(tmp_path):
    rng = random.Random(6006)
    stylesheet = neutral_stylesheet(tmp_path)
    engine = LxmlEngine()
    output = tmp_path / 'rendered.html'
    for _ in range(128):
        text = ''.join(rng.choice(' \t\r\n') for _ in range(rng.randrange(70)))
        text += rng.choice(('', '  code\n next', '\t世界😀\n', '\r\n '))
        root = etree.Element('root')
        code = etree.SubElement(etree.SubElement(root, 'pre'), 'code')
        for offset in range(0, len(text), 3):
            etree.SubElement(code, 'span', title=str(offset)).text = text[offset:offset + 3]
        engine.run(etree.tostring(root), stylesheet, output)
        document = html.parse(str(output), parser=html.HTMLParser(encoding='utf-8'))
        expected = re.sub(r'^(?:[ \t\r]*\n)+', '', text)
        assert document.xpath('string(//pre)') == expected.replace('\r\n', '\n').replace('\r', '\n')
        assert document.xpath('//span/@title') == list(map(str, range(0, len(text), 3)))
