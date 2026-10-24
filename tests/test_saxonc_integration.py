"""Opt-in checks against the pinned SaxonC executable used by CI."""
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from lxml import etree  # type: ignore[attr-defined]

from articulous.cli import CliOptions, parse_cli_args
from articulous.config import apply_cli_overrides, load_or_create_config
from articulous.engines import SaxonCEngine
from articulous.transform_contracts import TransformFailure
from articulous.pipeline import run_build


@pytest.fixture
def saxonc_home():
    home = os.environ.get("ARTICULOUS_SAXONC_HOME")
    if home is None:
        pytest.skip("Set ARTICULOUS_SAXONC_HOME to run real SaxonC integration tests")
    path = Path(home)
    assert os.access(path / "bin/Transform", os.X_OK), "Configured SaxonC executable is unavailable"
    return path


@pytest.fixture
def saxonc_engine(saxonc_home):
    return SaxonCEngine(saxonc_home / "bin/Transform")


@pytest.fixture
def external_resource(tmp_path):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<secret>private-marker</secret>")

        def log_message(self, format: str, *args) -> None:
            pass

    private = tmp_path / "private.xml"
    private.write_bytes(b"<secret>private-marker</secret>")
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield {"file": private.as_uri(), "http": f"http://127.0.0.1:{server.server_port}/private.xml"}, requests
        finally:
            server.shutdown()
            thread.join(timeout=5)


def _stylesheet(path, body):
    path.write_text(
        '<xsl:stylesheet version="3.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
        f'<xsl:template match="/"><out>{body}</out></xsl:template></xsl:stylesheet>',
    )
    return path


def test_real_saxonc_version(saxonc_engine):
    result = subprocess.run([str(saxonc_engine.saxonc_bin), "-?"], capture_output=True, text=True, check=True)
    assert "SaxonC-HE 12.10" in result.stdout + result.stderr


def test_seo01_real_saxonc_receives_literal_metadata(tmp_path, saxonc_engine):
    stylesheet = tmp_path / "metadata.xsl"
    stylesheet.write_text(
        '<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
        '<xsl:param name="articulous-site"/><xsl:template match="/">'
        '<site><xsl:value-of select="$articulous-site"/></site>'
        '</xsl:template></xsl:stylesheet>'
    )
    output = tmp_path / "metadata.xml"
    value = 'Unicode café 日本語 & "quotes" <markup> = literal'
    saxonc_engine.run(b"<article/>", stylesheet, output, parameters={"articulous-site": value})
    assert etree.parse(str(output)).getroot().text == value


def test_seo06_real_saxonc_renders_reciprocal_alternates(site_root, seo_config, saxonc_home):
    cli, config = seo_config
    config["saxonc"]["home"] = str(saxonc_home)
    config["engines"]["articles"] = "saxonc"
    for relative in ["en/first-post.xml", "fr/premier.xml"]:
        path = site_root / "content" / relative
        path.write_text(path.read_text().replace("</article>", "<translation>pair</translation></article>"))
    run_build(cli, config, site_root)
    for relative in ["en/articles/first-post/index.html", "fr/articles/premier-article/index.html"]:
        root = etree.HTML((site_root / "output" / relative).read_bytes())
        assert root.xpath("head/link[@rel='alternate']/@hreflang") == ["en", "fr"]


def test_seo10_real_saxonc_serializes_safe_jsonld(site_root, seo_config, saxonc_home):
    cli, config = seo_config
    config["saxonc"]["home"] = str(saxonc_home)
    config["engines"]["articles"] = "saxonc"
    source = site_root / "content/en/first-post.xml"
    source.write_text(source.read_text().replace(
        "</article>", '<structured-data>Article</structured-data><author>&lt;/script&gt; 日本語</author></article>',
    ))
    run_build(cli, config, site_root)
    root = etree.HTML((site_root / "output/en/articles/first-post/index.html").read_bytes())
    assert len(root.xpath("//script")) == 1
    data = json.loads(root.xpath("string(head/script)"))
    assert data["author"]["name"] == "</script> 日本語"


def test_seo10_real_saxonc_handles_large_jsonld(site_root, seo_config, saxonc_home):
    cli, config = seo_config
    config["saxonc"]["home"] = str(saxonc_home)
    config["engines"]["articles"] = "saxonc"
    source = site_root / "content/en/first-post.xml"
    description = ("Quoted ' café " * 12000).strip()
    text = source.read_text().replace("Inaugural article.", description)
    source.write_text(text.replace("</article>", "<structured-data>Article</structured-data></article>"))
    run_build(cli, config, site_root)
    root = etree.HTML((site_root / "output/en/articles/first-post/index.html").read_bytes())
    data = json.loads(root.xpath("string(head/script)"))
    assert data["description"] == description


def test_real_saxonc_builds_all_sections_and_reuses_cache(site_root, saxonc_home):
    cli = CliOptions(parse_cli_args([]))
    config = load_or_create_config(site_root / "config.json")
    config["saxonc"]["home"] = str(saxonc_home)
    config["engines"] = dict.fromkeys(config["engines"], "saxonc")
    apply_cli_overrides(config, cli, site_root)
    run_build(cli, config, site_root)
    output = site_root / "output"
    article = etree.HTML((output / "en/articles/first-post/index.html").read_bytes())
    assert article.xpath("string(//h1)") == "First Post"
    assert (output / "en/page/1/index.html").is_file()
    assert (output / "en/tags/intro/index.html").is_file()
    assert etree.parse(str(output / "rss.xml")).xpath("/rss/channel/item/title/text()")
    sitemap = etree.parse(str(output / "sitemap.xml"))
    assert sitemap.xpath("//*[local-name()='loc']/text()")
    assert json.loads((output / "search.json").read_text())
    before = {path: path.stat().st_mtime_ns for path in output.rglob("*") if path.is_file()}
    run_build(cli, config, site_root)
    assert before == {path: path.stat().st_mtime_ns for path in before}


@pytest.mark.parametrize("protocol", ["file", "http"])
@pytest.mark.parametrize("function", ["document", "unparsed-text"])
def test_real_saxonc_denies_external_reads(tmp_path, saxonc_engine, external_resource, capfd, protocol, function):
    resources, requests = external_resource
    stylesheet = _stylesheet(tmp_path / "read.xsl", f'<xsl:value-of select="{function}(\'{resources[protocol]}\')"/>')
    output = tmp_path / "output.xml"
    output.write_bytes(b"previous")
    with pytest.raises(TransformFailure) as failure:
        saxonc_engine.run(b"<root/>", stylesheet, output)
    assert failure.value.returncode != 0
    captured = capfd.readouterr()
    assert "prohibited" in captured.out + captured.err
    assert output.read_bytes() == b"previous"
    assert requests == []


def test_real_saxonc_denies_secondary_writes(tmp_path, saxonc_engine, capfd):
    private = tmp_path / "private.xml"
    private.write_bytes(b"keep")
    stylesheet = _stylesheet(
        tmp_path / "write.xsl", f'<xsl:result-document href="{private.as_uri()}"><bad/></xsl:result-document>',
    )
    output = tmp_path / "output.xml"
    output.write_bytes(b"previous")
    with pytest.raises(TransformFailure):
        saxonc_engine.run(b"<root/>", stylesheet, output)
    captured = capfd.readouterr()
    assert "disabled" in captured.out + captured.err
    assert private.read_bytes() == b"keep"
    assert output.read_bytes() == b"previous"


@pytest.mark.parametrize("protocol", ["file", "http"])
def test_real_saxonc_does_not_expand_xinclude(tmp_path, saxonc_engine, external_resource, protocol):
    resources, requests = external_resource
    xml = f'<root xmlns:xi="http://www.w3.org/2001/XInclude"><xi:include href="{resources[protocol]}"/></root>'
    stylesheet = _stylesheet(tmp_path / "include.xsl", '<xsl:copy-of select="root/*"/>')
    output = tmp_path / "output.xml"
    saxonc_engine.run(xml.encode(), stylesheet, output)
    result = etree.parse(str(output))
    assert result.xpath("count(//*[local-name()='include'])") == 1
    assert b"private-marker" not in output.read_bytes()
    assert requests == []


@pytest.mark.parametrize("protocol", ["file", "http"])
def test_real_saxonc_denies_external_entities(tmp_path, saxonc_engine, external_resource, capfd, protocol):
    resources, requests = external_resource
    xml = f'<!DOCTYPE root [<!ENTITY secret SYSTEM "{resources[protocol]}">]><root>&secret;</root>'
    stylesheet = _stylesheet(tmp_path / "entity.xsl", '<xsl:value-of select="root"/>')
    output = tmp_path / "output.xml"
    with pytest.raises(TransformFailure):
        saxonc_engine.run(xml.encode(), stylesheet, output)
    captured = capfd.readouterr()
    assert "prohibited" in captured.out + captured.err
    assert not output.exists()
    assert requests == []


def test_real_saxonc_compile_failure_preserves_output(tmp_path, saxonc_engine, capfd):
    stylesheet = _stylesheet(tmp_path / "invalid.xsl", '<xsl:value-of select="("/>')
    output = tmp_path / "output.xml"
    output.write_bytes(b"previous")
    with pytest.raises(TransformFailure):
        saxonc_engine.run(b"<root/>", stylesheet, output)
    captured = capfd.readouterr()
    assert "XPST0003" in captured.out + captured.err
    assert output.read_bytes() == b"previous"
    assert list(tmp_path.glob(".output.xml.*")) == []
