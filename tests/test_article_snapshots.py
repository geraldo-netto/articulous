"""Publication uses the same article bytes that supplied validated metadata."""
import dataclasses
import hashlib
import json
import os
import tracemalloc

import lxml.etree as etree
import pytest

import articulous.pipeline as pipeline
from articulous.articles import ArticleSnapshot, parse_article_xml
from articulous.cli import CliOptions, parse_cli_args
from articulous.config import apply_cli_overrides, load_or_create_config
from articulous.filesystem import TempWorkspace
from articulous.engines import LxmlEngine, SaxonCEngine


def _site_config(root):
    cli = CliOptions(parse_cli_args([]))
    config = load_or_create_config(root / "config.json")
    apply_cli_overrides(config, cli, root)
    return cli, config


def _change_article(source, kind):
    if kind == "private":
        content = source.read_text().replace("Inaugural article.", "Unchecked private content")
        source.write_text(content.replace("</article>", "<status>private</status></article>"))
    else:
        source.unlink()
        if kind == "fifo":
            os.mkfifo(source)


def _change_after_parse(source, kind, original):
    def stream(*args, **kwargs):
        for article in original(*args, **kwargs):
            if article.source_path == source:
                _change_article(source, kind)
            yield article
    return stream


@pytest.mark.parametrize("kind", ["private", "deleted", "fifo"])
@pytest.mark.parametrize("stage", ["parsed", "planned"])
def test_concurrent_source_changes_never_publish_unchecked_bytes(site_root, monkeypatch, kind, stage):
    cli, config = _site_config(site_root)
    source = site_root / "content/en/first-post.xml"
    captured = source.read_bytes()
    original_run = pipeline._run_plan

    def change_before_workers(plan, ctx):
        _change_article(source, kind)
        return original_run(plan, ctx)

    with monkeypatch.context() as patch:
        if stage == "parsed":
            patch.setattr(pipeline, "iter_articles", _change_after_parse(source, kind, pipeline.iter_articles))
        else:
            patch.setattr(pipeline, "_run_plan", change_before_workers)
        pipeline.run_build(cli, config, site_root)
    page = site_root / "output/en/articles/first-post/index.html"
    assert "Inaugural article." in page.read_text()
    assert "Unchecked private content" not in page.read_text()
    roots = json.loads((site_root / ".build-cache.json").read_text())["__output_roots__"]
    assert roots[str(site_root / "output")]["article:en:first-post"][0] == hashlib.sha256(captured).hexdigest()
    pipeline.run_build(cli, config, site_root)
    assert not page.exists()
    assert "first-post" not in (site_root / "output/search.json").read_text()


def test_direct_article_builder_uses_parser_snapshot(site_root):
    _, config = _site_config(site_root)
    source = site_root / "content/en/first-post.xml"
    article = parse_article_xml(source)
    assert article is not None
    assert article.source_xml == source.read_bytes()
    source.unlink()
    ctx = pipeline.build_ctx_from_config(config, False)
    for task in pipeline.build_articles_section([article], ctx, {}):
        task()
    assert "Inaugural article." in (ctx.output_dir / "en/articles/first-post/index.html").read_text()


def test_article_source_move_invalidates_base_uri_fingerprint(site_root):
    cli, config = _site_config(site_root)
    pipeline.run_build(cli, config, site_root)
    cache = site_root / ".build-cache.json"
    root = str(site_root / "output")
    before = json.loads(cache.read_text())["__output_roots__"][root]["article:en:first-post"]
    source = site_root / "content/en/first-post.xml"
    moved = source.with_name("renamed.xml")
    source.rename(moved)
    pipeline.run_build(cli, config, site_root)
    after = json.loads(cache.read_text())["__output_roots__"][root]["article:en:first-post"]
    assert before[:-1] == after[:-1]
    assert before[-1] == source.as_uri()
    assert after[-1] == moved.as_uri()


@pytest.mark.parametrize("xml_base", ["", "media/"])
def test_lxml_snapshot_preserves_effective_document_base(tmp_path, xml_base):
    namespace = etree.FunctionNamespace("urn:article-base-test")
    namespace["read"] = lambda context: context.context_node.base
    stylesheet = tmp_path / "base.xsl"
    stylesheet.write_text(
        '<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform" '
        'xmlns:b="urn:article-base-test"><xsl:output method="text"/>'
        '<xsl:template match="/root"><xsl:value-of select="b:read()"/></xsl:template></xsl:stylesheet>'
    )
    output = tmp_path / "base.txt"
    document_uri = (tmp_path / "article.xml").as_uri()
    try:
        LxmlEngine().run(f'<root xml:base="{xml_base}"/>'.encode(), stylesheet, output,
                         xml_base_uri=document_uri)
    finally:
        del namespace["read"]
    expected = (tmp_path / "media").as_uri() + "/" if xml_base else document_uri
    assert output.read_text() == expected


@pytest.mark.parametrize("xml_base", ["", "media/"])
def test_saxon_snapshot_materializes_effective_document_base(site_root, monkeypatch, xml_base):
    source = site_root / "content/en/first-post.xml"
    captured = source.read_bytes().replace(b"<article>", f'<article xml:base="{xml_base}">'.encode())
    source.unlink()
    expected = (source.parent / "media").as_uri() + "/" if xml_base else source.as_uri()
    observed = []

    def inspect_transform(command, check, pass_fds):
        xml_path = next(argument[3:] for argument in command if argument.startswith("-s:"))
        root = etree.parse(xml_path).getroot()
        observed.append(root.base)
        assert root.attrib["{http://www.w3.org/XML/1998/namespace}base"] == expected
        assert root.findtext("description") == "Inaugural article."

    monkeypatch.setattr("articulous.engines.subprocess.run", inspect_transform)
    SaxonCEngine(site_root / "Transform").run(
        captured, site_root / "xsl/pages/article.xsl", site_root / "output/article.html",
        xml_base_uri=source.as_uri(),
    )
    assert observed == [expected]


def test_article_snapshot_spool_rejects_tampering(site_root):
    article = parse_article_xml(site_root / "content/en/first-post.xml")
    assert article is not None
    with TempWorkspace() as workspace:
        store = pipeline.ArticleStore(workspace)
        try:
            store.append("en", article)
            stored = next(store.iter_lang("en"))
            assert isinstance(stored.source_xml, ArticleSnapshot)
            stored.source_xml.path.write_bytes(b"unchecked")
            with pytest.raises(ValueError, match="snapshot changed or truncated"):
                pipeline._article_input(stored)
        finally:
            store.close()


def test_sorting_article_snapshots_keeps_bodies_on_disk(site_root):
    article = parse_article_xml(site_root / "content/en/first-post.xml")
    assert article is not None
    with TempWorkspace() as workspace:
        store = pipeline.ArticleStore(workspace)
        tracemalloc.start()
        try:
            for index in range(128):
                body = b"x" * 262144 + str(index).encode()
                store.append("en", dataclasses.replace(article, source_xml=body))
            ordered = store.sorted("en")
            assert len(ordered) == 128
            assert all(isinstance(item.source_xml, ArticleSnapshot) for item in ordered)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            store.close()
            tracemalloc.stop()
    assert peak < 8_000_000
