"""THEME-001: installed resource provenance and neutral Articulous rendering."""
import hashlib
from importlib.resources import files
import lxml.html as html
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


def test_theme001_neutral_sanitized_rendering(tmp_path):
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
    output = tmp_path / 'neutral.html'
    LxmlEngine().run(b'<root><p onclick="bad()">Safe</p><p><div>Block</div></p><script>bad()</script><a href="javascript:bad()">Link</a><pre><code>\n  exact &amp; text<br/>next\n</code></pre></root>', stylesheet, output)
    document = html.parse(str(output))
    assert not document.xpath('//script | //@onclick | //a/@href')
    assert document.xpath('string(//pre)') == '  exact & text\nnext\n'
    assert document.xpath('//pre/@data-prismjs-copy') == ['Copiar']
    assert document.xpath('//div/@class') == ['paragraph ']
