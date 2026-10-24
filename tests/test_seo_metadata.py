"""SEO-01: resolved metadata reaches the production article renderer."""
import os

import pytest
import subprocess
import lxml.etree as etree

from articulous.engines import SaxonCEngine
from articulous.pipeline import run_build



def _metadata_stylesheet(path):
    path.write_text(
        '<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
        '<xsl:param name="articulous-url"/><xsl:param name="articulous-lang"/>'
        '<xsl:param name="articulous-site"/><xsl:template match="/article">'
        '<metadata url="{$articulous-url}" lang="{$articulous-lang}" site="{$articulous-site}">'
        '<xsl:value-of select="description"/></metadata></xsl:template></xsl:stylesheet>'
    )


def test_seo01_metadata_reaches_dispatcher_and_invalidates_cache(site_root, seo_config):
    cli, config = seo_config
    source = site_root / "content/en/first-post.xml"
    source.write_text(source.read_text().replace("<lang>en</lang>", "<lang>unknown</lang>"))
    captured = source.read_bytes()
    _metadata_stylesheet(site_root / "xsl/pages/article.xsl")
    config["urls"]["article"] = "/journal/{lang}/{slug}/"
    page = site_root / "output/journal/en/first-post/index.html"
    for base, name in [("https://example.test/blog", 'A "quoted" & café site'),
                       ("https://example.test/new", "New site")]:
        config["site"].update(base_url=base, site_name=name)
        run_build(cli, config, site_root)
        root = etree.parse(str(page)).getroot()
        assert dict(root.attrib) == {"url": base + "/journal/en/first-post/", "lang": "en", "site": name}
        assert root.text == "Inaugural article."
        assert source.read_bytes() == captured


@pytest.mark.parametrize("value", ["", "café 日本語", "'\" & < >", "$(false) `false` = /tmp/file"])
def test_seo01_saxon_parameters_are_literal_arguments(tmp_path, monkeypatch, value):
    stylesheet = tmp_path / "metadata.xsl"
    _metadata_stylesheet(stylesheet)
    seen = []

    def transform(command, pass_fds):
        seen.extend(command)
        os.write(pass_fds[0], b"<metadata/>")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("articulous.engines.run_transform_command", transform)
    SaxonCEngine(tmp_path / "Transform").run(
        b"<article/>", stylesheet, tmp_path / "page.xml",
        parameters={"articulous-site": value},
    )
    assert "articulous-site=" + value in seen
