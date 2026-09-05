"""Unit tests for articulous.engines."""
import logging
import os
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import cast
from unittest import mock

import lxml.etree as etree
import pytest

from articulous.engines import (
    LxmlEngine,
    NativeEngine,
    REQUIRED_XSL_FILES,
    SECTION_XSL,
    SaxonCEngine,
    TransformEngine,
    VALID_ENGINES,
    _SnapshotResolver,
    _snapshot_stylesheet,
    check_dependencies,
    configure_saxonc,
    make_engine,
    safe_xslt_access_control,
    safe_xml_parser,
    stylesheet_hash,
    validate_engines,
)
from articulous.filesystem import TempWorkspace


MINIMAL_XSLT = (
    '<xsl:stylesheet version="1.0" '
    'xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
    '<xsl:template match="/"><out/></xsl:template>'
    "</xsl:stylesheet>"
)


# --- module-level constants ---

def test_required_xsl_files_match_section_xsl():
    assert set(REQUIRED_XSL_FILES) == set(SECTION_XSL.values())


def test_valid_engines_set():
    assert VALID_ENGINES == {"saxonc", "lxml", "native"}


def test_stylesheet_hash_tracks_transitive_includes(tmp_path):
    included = tmp_path / "included.xsl"
    included.write_text(MINIMAL_XSLT)
    main = tmp_path / "main.xsl"
    main.write_text(
        MINIMAL_XSLT.replace(
            "<xsl:template",
            '<xsl:include href="included.xsl"/><xsl:template',
            1,
        )
    )
    first = stylesheet_hash(main)
    included.write_text(MINIMAL_XSLT.replace("<out/>", "<changed/>"))
    assert stylesheet_hash(main) != first


def test_stylesheet_hash_handles_repeated_dependency(tmp_path):
    included = tmp_path / "included.xsl"
    included.write_text(MINIMAL_XSLT)
    main = tmp_path / "main.xsl"
    main.write_text(
        MINIMAL_XSLT.replace(
            "<xsl:template",
            '<xsl:include href="included.xsl"/>'
            '<xsl:include href="included.xsl"/>'
            "<xsl:template",
            1,
        )
    )
    assert len(stylesheet_hash(main)) == 64


@pytest.mark.parametrize("kind", ["fifo", "device"])
def test_stylesheet_hash_rejects_special_dependencies(tmp_path, kind):
    dependency = tmp_path / "included.xsl"
    if kind == "fifo":
        os.mkfifo(dependency)
    else:
        dependency.symlink_to("/dev/null")
    main = tmp_path / "main.xsl"
    main.write_text(MINIMAL_XSLT.replace(
        "<xsl:template", '<xsl:include href="included.xsl"/><xsl:template', 1,
    ))
    result = subprocess.run(
        [sys.executable, "-c", "from pathlib import Path; import sys; "
         "from articulous.engines import stylesheet_hash; stylesheet_hash(Path(sys.argv[1]))",
         str(main)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=5,
    )
    assert result.returncode != 0
    assert b"Path must be a regular file" in result.stderr


def test_stylesheet_hash_rejects_dependency_swapped_during_open(tmp_path, monkeypatch):
    dependency = tmp_path / "included.xsl"
    dependency.write_text(MINIMAL_XSLT)
    main = tmp_path / "main.xsl"
    main.write_text(MINIMAL_XSLT.replace(
        "<xsl:template", '<xsl:include href="included.xsl"/><xsl:template', 1,
    ))
    original_open = os.open

    def swap_before_open(path, flags, mode=0o777):
        if Path(path) == dependency:
            dependency.unlink()
            os.mkfifo(dependency)
        return original_open(path, flags, mode)

    monkeypatch.setattr(os, "open", swap_before_open)
    with pytest.raises(ValueError, match="Opened path must be a regular file"):
        stylesheet_hash(main)


def test_engine_cache_identities_include_runtime(tmp_path):
    binary = tmp_path / "Transform"
    binary.write_text("binary")
    assert "libxslt=" in LxmlEngine().cache_identity
    assert str(binary.resolve()) in SaxonCEngine(binary).cache_identity
    assert "missing" in SaxonCEngine(tmp_path / "missing").cache_identity


@pytest.mark.parametrize("absolute", [False, True])
def test_stylesheet_dependencies_respect_uris_and_xml_base(tmp_path, absolute):
    included = tmp_path / "includes/common file.xsl"
    included.parent.mkdir()
    included.write_text(MINIMAL_XSLT)
    href = included.as_uri() if absolute else "common%20file.xsl"
    main = tmp_path / "main.xsl"
    main.write_text(
        '<xsl:stylesheet version="1.0" xml:base="includes/" '
        'xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
        f'<xsl:include href="{href}"/></xsl:stylesheet>'
    )
    output = tmp_path / "page.xml"
    engine = LxmlEngine()
    engine.run(b"<root/>", main, output)
    assert etree.parse(str(output)).getroot().tag == "out"
    included.write_text(MINIMAL_XSLT.replace("<out/>", "<changed/>"))
    engine.run(b"<root/>", main, output)
    assert etree.parse(str(output)).getroot().tag == "changed"


def _including_stylesheet(href, xml_base=""):
    return (
        '<xsl:stylesheet version="1.0" '
        'xmlns:xsl="http://www.w3.org/1999/XSL/Transform" '
        f'xml:base="{xml_base}"><xsl:include href="{href}"/></xsl:stylesheet>'
    )


@pytest.mark.parametrize("xml_base", ["", "shared/"])
def test_stylesheet_symlinks_keep_logical_dependency_bases(tmp_path, xml_base):
    pages = tmp_path / "pages"
    templates = tmp_path / "templates"
    library = tmp_path / "library"
    for directory in (pages / xml_base, templates / xml_base, library):
        directory.mkdir(parents=True)
    physical = templates / "main.xsl"
    physical.write_text(_including_stylesheet("common.xsl", xml_base))
    main = pages / "main.xsl"
    main.symlink_to(physical)
    common = library / "common.xsl"
    common.write_text(_including_stylesheet("leaf.xsl"))
    (pages / xml_base / "common.xsl").symlink_to(common)
    (templates / xml_base / "common.xsl").write_text(MINIMAL_XSLT)
    (library / "leaf.xsl").write_text(MINIMAL_XSLT.replace("<out/>", "<physical/>"))
    logical = pages / xml_base / "leaf.xsl"
    logical.write_text(MINIMAL_XSLT)
    engine = LxmlEngine()
    first = engine.prepare_stylesheet(main)
    output = tmp_path / "page.xml"
    engine.run(b"<root/>", main, output, stylesheet_fingerprint=first)
    assert etree.parse(str(output)).getroot().tag == "out"
    logical.write_text(MINIMAL_XSLT.replace("<out/>", "<logical/>"))
    assert stylesheet_hash(main) != first
    engine.run(b"<root/>", main, output)
    assert etree.parse(str(output)).getroot().tag == "logical"


def test_lxml_compiles_only_captured_stylesheet_bytes(tmp_path, monkeypatch):
    main = tmp_path / "main.xsl"
    main.write_text(_including_stylesheet("included.xsl"))
    included = tmp_path / "included.xsl"
    included.write_text(MINIMAL_XSLT)
    engine = LxmlEngine()
    fingerprint = engine.prepare_stylesheet(main)
    main.unlink()
    included.unlink()

    def unexpected_read(_path):
        pytest.fail("Compilation reopened a stylesheet after capture")

    monkeypatch.setattr("articulous.engines.open_regular_file", unexpected_read)
    output = tmp_path / "page.xml"
    engine.run(b"<root/>", main, output, stylesheet_fingerprint=fingerprint)
    assert etree.parse(str(output)).getroot().tag == "out"


def test_snapshot_resolver_rejects_uncaptured_resources(tmp_path):
    main = tmp_path / "main.xsl"
    main.write_text(MINIMAL_XSLT)
    outside = tmp_path / "outside.xsl"
    outside.write_text(MINIMAL_XSLT)
    resolver = _SnapshotResolver(_snapshot_stylesheet(main))
    with pytest.raises(ValueError, match="outside the captured snapshot"):
        resolver.resolve(outside.as_uri(), None, None)


def test_stylesheet_alias_cycle_is_rejected(tmp_path):
    main = tmp_path / "main.xsl"
    main.write_text(_including_stylesheet("nested/main.xsl"))
    (tmp_path / "nested").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="Circular stylesheet dependency"):
        stylesheet_hash(main)


def test_engine_rejects_uncaptured_mismatched_fingerprint(tmp_path):
    main = tmp_path / "main.xsl"
    main.write_text(MINIMAL_XSLT)
    output = tmp_path / "page.xml"
    output.write_text("keep")
    with pytest.raises(ValueError, match="fingerprint changed since planning"):
        LxmlEngine().run(b"<root/>", main, output, stylesheet_fingerprint="unverified")
    assert output.read_text() == "keep"


@pytest.mark.parametrize("href", [
    "https://example.invalid/style.xsl", "file://remote/style.xsl",
    "style.xsl?query", "style.xsl#fragment",
])
def test_stylesheet_dependency_policy_rejects_unsupported_uris(tmp_path, href):
    path = tmp_path / "main.xsl"
    path.write_text(
        '<xsl:stylesheet version="1.0" '
        'xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
        f'<xsl:include href="{href}"/></xsl:stylesheet>'
    )
    with pytest.raises(ValueError, match="Stylesheet dependenc"):
        stylesheet_hash(path)


def test_safe_xml_parser_is_xxe_safe(tmp_path):
    """Behavioural check: external entities do not get expanded."""
    payload = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<foo>&xxe;</foo>'
    )
    root = etree.fromstring(payload.encode(), parser=safe_xml_parser())
    assert (root.text or "") == ""  # entity not expanded


def test_safe_xslt_access_control_disables_reads():
    access = safe_xslt_access_control()
    assert access is not None


# --- LxmlEngine ---

def test_lxml_engine_runs_with_path(tmp_path):
    xml = tmp_path / "x.xml"
    xml.write_text("<root/>")
    xsl = tmp_path / "x.xsl"
    xsl.write_text(MINIMAL_XSLT)
    out = tmp_path / "out.html"
    LxmlEngine().run(xml, xsl, out)
    assert out.exists()


def test_lxml_engine_runs_with_bytes(tmp_path):
    xsl = tmp_path / "x.xsl"
    xsl.write_text(MINIMAL_XSLT)
    out = tmp_path / "out.html"
    LxmlEngine().run(b"<root/>", xsl, out)
    assert out.exists()


@pytest.mark.parametrize("encoding", ["ISO-8859-1", "UTF-8"])
def test_lxml_html_respects_declared_encoding(tmp_path, encoding):
    xsl = tmp_path / "page.xsl"
    xsl.write_text(
        '<xsl:stylesheet version="1.0" '
        'xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
        f'<xsl:output method="html" encoding="{encoding}"/>'
        '<xsl:template match="/"><html><head><title>café</title></head>'
        '<body>café</body></html></xsl:template></xsl:stylesheet>',
        encoding="utf-8",
    )
    output = tmp_path / "page.html"
    LxmlEngine().run(b"<root/>", xsl, output)
    assert etree.HTML(output.read_bytes()).findtext("body") == "café"


def test_lxml_engine_caches_stylesheet_by_fingerprint(tmp_path):
    xml = tmp_path / "x.xml"
    xml.write_text("<root/>")
    xsl = tmp_path / "x.xsl"
    xsl.write_text(MINIMAL_XSLT)
    out = tmp_path / "out.html"
    engine = LxmlEngine()
    first = engine.prepare_stylesheet(xsl)
    real_xslt = etree.XSLT
    with mock.patch(
        "articulous.engines.etree.XSLT", side_effect=real_xslt,
    ) as compile_xslt:
        engine.run(xml, xsl, out, stylesheet_fingerprint=first)
        engine.run(xml, xsl, out, stylesheet_fingerprint=first)
        xsl.write_text(MINIMAL_XSLT.replace("<out/>", "<changed/>"))
        second = engine.prepare_stylesheet(xsl)
        engine.run(xml, xsl, out, stylesheet_fingerprint=second)
    assert compile_xslt.call_count == 2


def test_lxml_engine_keeps_thread_local_stylesheets(tmp_path):
    xml = tmp_path / "x.xml"
    xml.write_text("<root/>")
    xsl = tmp_path / "x.xsl"
    xsl.write_text(MINIMAL_XSLT)
    out = tmp_path / "out.html"
    engine = LxmlEngine()
    fingerprint = engine.prepare_stylesheet(xsl)
    real_xslt = etree.XSLT

    def transform():
        engine.run(xml, xsl, out, stylesheet_fingerprint=fingerprint)

    with mock.patch(
        "articulous.engines.etree.XSLT", side_effect=real_xslt,
    ) as compile_xslt:
        for _ in range(2):
            thread = threading.Thread(target=transform)
            thread.start()
            thread.join()
    assert compile_xslt.call_count == 2


def test_lxml_engine_dry_run_with_path_label(tmp_path, caplog):
    xsl = tmp_path / "x.xsl"
    xsl.write_text(MINIMAL_XSLT)
    out = tmp_path / "out.html"
    with caplog.at_level(logging.DEBUG):
        LxmlEngine().run(tmp_path / "x.xml", xsl, out, dry_run=True)
    assert not out.exists()
    assert any("[DRY RUN] lxml" in r.message for r in caplog.records)


def test_lxml_engine_dry_run_with_bytes_label(tmp_path, caplog):
    xsl = tmp_path / "x.xsl"
    xsl.write_text(MINIMAL_XSLT)
    out = tmp_path / "out.html"
    with caplog.at_level(logging.DEBUG):
        LxmlEngine().run(b"<root/>", xsl, out, dry_run=True)
    assert any("<bytes>" in r.message for r in caplog.records)


def test_lxml_engine_creates_parent_dir(tmp_path):
    xsl = tmp_path / "x.xsl"
    xsl.write_text(MINIMAL_XSLT)
    out = tmp_path / "deep" / "nested" / "out.html"
    LxmlEngine().run(b"<root/>", xsl, out)
    assert out.exists()


def test_lxml_engine_propagates_xslt_parse_error(tmp_path, caplog):
    xsl = tmp_path / "bad.xsl"
    xsl.write_text("<not-a-stylesheet/>")
    out = tmp_path / "out.html"
    engine = LxmlEngine()
    with caplog.at_level(logging.ERROR):
        with pytest.raises(etree.XSLTParseError):
            engine.run(b"<root/>", xsl, out)
    assert any("lxml transform failed" in r.message for r in caplog.records)


def test_lxml_engine_blocks_xslt_document_reads(tmp_path, caplog):
    xsl = tmp_path / "doc.xsl"
    secret = tmp_path / "secret.xml"
    secret.write_text("<secret>nope</secret>")
    xsl.write_text(
        '<xsl:stylesheet version="1.0" '
        'xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
        '<xsl:template match="/">'
        f'<xsl:value-of select="document({str(secret)!r})/secret"/>'
        "</xsl:template></xsl:stylesheet>"
    )
    engine = LxmlEngine()
    out = tmp_path / "out.txt"
    with caplog.at_level(logging.ERROR):
        with pytest.raises(etree.XSLTApplyError):
            engine.run(b"<root/>", xsl, out)
    assert any("lxml transform failed" in r.message for r in caplog.records)


# --- SaxonCEngine ---

def test_saxon_engine_records_binary_path():
    e = SaxonCEngine(Path("/usr/local/saxon/bin/Transform"))
    assert e.saxonc_bin == Path("/usr/local/saxon/bin/Transform")


def test_saxon_engine_rejects_leading_dash_path(tmp_path):
    e = SaxonCEngine(tmp_path / "Transform")
    # bypass _do_transform's bytes-handling; call _run_saxon directly with
    # a fake Path whose resolved string begins with '-'.
    class FakePath:
        def __init__(self, s): self.s = s
        def resolve(self): return self
        def absolute(self): return self
        def __str__(self): return self.s

    xml_path = cast(Path, FakePath("-evil.xml"))
    xsl_path = cast(Path, FakePath("/abs/x.xsl"))
    output_path = cast(Path, FakePath("/abs/o.html"))
    with pytest.raises(ValueError, match=r"begins with '-'"):
        e._run_saxon(xml_path, xsl_path, output_path)


def test_saxon_engine_invokes_subprocess(tmp_path):
    e = SaxonCEngine(tmp_path / "Transform")
    xml = tmp_path / "x.xml"
    xml.write_text("<r/>")
    xsl = tmp_path / "x.xsl"
    xsl.write_text(MINIMAL_XSLT)
    out = tmp_path / "out.html"
    with mock.patch("articulous.engines.subprocess.run") as run_mock:
        e._do_transform(xml, xsl, out)
    assert run_mock.called
    cmd = run_mock.call_args[0][0]
    assert cmd[0] == str(tmp_path / "Transform")
    assert "-ext:off" in cmd
    assert "-xi:off" in cmd
    assert "--allowedProtocols:#none" in cmd
    assert any(arg.startswith("-s:") for arg in cmd)
    assert any(arg.startswith("-xsl:") for arg in cmd)
    assert any(arg.startswith("-o:") for arg in cmd)


def test_saxon_engine_materialises_bytes_to_tempfile(tmp_path):
    e = SaxonCEngine(tmp_path / "Transform")
    xsl = tmp_path / "x.xsl"
    xsl.write_text(MINIMAL_XSLT)
    out = tmp_path / "out.html"
    captured = {}

    def fake_run(cmd, check):
        # -s:VAL — extract VAL and confirm it exists during the call
        s_arg = [a for a in cmd if a.startswith("-s:")][0]
        captured["tmp"] = Path(s_arg[3:])
        captured["existed_during_run"] = captured["tmp"].exists()
        return mock.Mock(returncode=0)

    with mock.patch("articulous.engines.subprocess.run", side_effect=fake_run):
        e._do_transform(b"<root/>", xsl, out)

    assert captured["existed_during_run"] is True
    # Cleaned up after the subprocess returned
    assert not captured["tmp"].exists()


def test_saxon_uses_captured_stylesheet_and_original_base(tmp_path, monkeypatch):
    xsl = tmp_path / "main.xsl"
    xsl.write_text(MINIMAL_XSLT)
    engine = SaxonCEngine(tmp_path / "Transform")
    fingerprint = engine.prepare_stylesheet(xsl)
    xsl.write_text(MINIMAL_XSLT.replace("<out/>", "<changed/>"))
    captured = []

    def inspect_transform(cmd, check):
        path = Path(next(arg[5:] for arg in cmd if arg.startswith("-xsl:")))
        captured.append(path)
        root = etree.parse(str(path)).getroot()
        assert root.base == xsl.as_uri()
        assert root.find(".//out") is not None
        assert root.find(".//changed") is None

    monkeypatch.setattr("articulous.engines.subprocess.run", inspect_transform)
    engine.run(b"<root/>", xsl, tmp_path / "page.xml", stylesheet_fingerprint=fingerprint)
    assert len(captured) == 1
    assert not captured[0].exists()


def test_saxon_rejects_dependencies_before_subprocess(tmp_path):
    main = tmp_path / "main.xsl"
    main.write_text(_including_stylesheet("included.xsl"))
    (tmp_path / "included.xsl").write_text(MINIMAL_XSLT)
    with mock.patch("articulous.engines.subprocess.run") as run:
        with pytest.raises(ValueError, match="SaxonC stylesheets must be standalone"):
            SaxonCEngine(tmp_path / "Transform").run(b"<root/>", main, tmp_path / "page.xml")
    run.assert_not_called()


@pytest.mark.parametrize("operation", ["write", "close"])
def test_saxon_materialization_failure_cleans_input(tmp_path, monkeypatch, operation):
    allocated = []
    xsl = tmp_path / "stylesheet.xsl"
    xsl.write_text(MINIMAL_XSLT)
    real_named_file = TempWorkspace.named_file

    @contextmanager
    def failing_file(workspace, *args, **kwargs):
        with real_named_file(workspace, *args, **kwargs) as file:
            allocated.append(Path(file.name))
            original_write = file.write
            def fail(data):
                original_write(data)
                raise OSError("materialization failed")
            if operation == "write":
                monkeypatch.setattr(file, "write", fail)
            yield file
        raise OSError("materialization failed")

    monkeypatch.setattr(TempWorkspace, "named_file", failing_file)
    with pytest.raises(OSError, match="materialization failed"):
        SaxonCEngine(tmp_path / "unused").run(b"<root/>", xsl, tmp_path / "out")
    assert len(allocated) == 1
    assert not allocated[0].exists()


def test_saxon_engine_propagates_subprocess_failure(tmp_path, caplog):
    e = SaxonCEngine(tmp_path / "Transform")
    xml = tmp_path / "x.xml"
    xml.write_text("<r/>")
    xsl = tmp_path / "x.xsl"
    xsl.write_text(MINIMAL_XSLT)
    out = tmp_path / "out.html"
    with mock.patch(
        "articulous.engines.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "cmd"),
    ):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(subprocess.CalledProcessError):
                e._do_transform(xml, xsl, out)
    assert any("SaxonC transform failed" in r.message for r in caplog.records)


def test_saxon_partial_failure_preserves_published_output(tmp_path):
    xml = tmp_path / "x.xml"
    xml.write_text("<root/>")
    xsl = tmp_path / "x.xsl"
    xsl.write_text(MINIMAL_XSLT)
    output = tmp_path / "page.html"
    output.write_text("published")

    def fail_transform(cmd, check):
        staged = Path(next(arg[3:] for arg in cmd if arg.startswith("-o:")))
        staged.write_text("partial")
        raise subprocess.CalledProcessError(1, cmd)

    with mock.patch("articulous.engines.subprocess.run", side_effect=fail_transform):
        with pytest.raises(subprocess.CalledProcessError):
            SaxonCEngine(tmp_path / "Transform").run(xml, xsl, output)
    assert output.read_text() == "published"
    assert len(list(tmp_path.iterdir())) == 3


# --- factories ---

def test_make_engine_lxml():
    e = make_engine("lxml", None)
    assert isinstance(e, LxmlEngine)


def test_make_engine_native():
    assert isinstance(make_engine("native", None), NativeEngine)


def test_make_engine_saxon_without_binary_falls_back_to_lxml():
    e = make_engine("saxonc", None)
    assert isinstance(e, LxmlEngine)


def test_make_engine_saxon_with_binary():
    e = make_engine("saxonc", Path("/some/path"))
    assert isinstance(e, SaxonCEngine)


def test_make_engine_rejects_unknown_name():
    with pytest.raises(ValueError, match="Unknown engine"):
        make_engine("frobnicate", None)


def test_make_engine_rejects_none_name():
    invalid_name = cast(str, None)
    with pytest.raises(ValueError, match="Unknown engine"):
        make_engine(invalid_name, None)


def test_configure_saxonc_no_home_returns_none(monkeypatch):
    monkeypatch.setattr("articulous.engines.shutil.which", lambda name: None)
    assert configure_saxonc({"saxonc": {"home": None}}) is None


def test_configure_saxonc_discovers_path_binary(tmp_path, monkeypatch):
    transform = tmp_path / "Transform"
    transform.write_text("#!/bin/sh\n")
    monkeypatch.setattr(
        "articulous.engines.shutil.which", lambda name: str(transform)
    )
    assert configure_saxonc({"saxonc": {"home": None}}) == transform


def test_configure_saxonc_missing_binary_warns(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        result = configure_saxonc({"saxonc": {"home": str(tmp_path)}})
    assert result is None
    assert any("Transform binary not executable" in r.message for r in caplog.records)


def test_configure_saxonc_non_executable_warns(tmp_path, caplog):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    transform = bin_dir / "Transform"
    transform.write_text("#!/bin/sh\n")
    transform.chmod(0o644)
    with caplog.at_level(logging.WARNING):
        result = configure_saxonc({"saxonc": {"home": str(tmp_path)}})
    assert result is None
    assert any("not executable" in r.message for r in caplog.records)


def test_configure_saxonc_finds_binary(tmp_path, caplog):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    transform = bin_dir / "Transform"
    transform.write_text("#!/bin/sh\n")
    transform.chmod(0o755)
    with caplog.at_level(logging.INFO):
        result = configure_saxonc({"saxonc": {"home": str(tmp_path)}})
    assert result == transform
    assert any("SaxonC detected" in r.message for r in caplog.records)


# --- validate_engines ---

def test_validate_engines_accepts_valid():
    validate_engines({
        "engines": {
            "articles": "lxml", "rss": "saxonc", "search": "native",
        },
    })


def test_validate_engines_rejects_unknown():
    with pytest.raises(ValueError, match="frobnicate"):
        validate_engines({"engines": {"rss": "frobnicate"}})


def test_validate_engines_rejects_native_article_renderer():
    with pytest.raises(ValueError, match="only supported"):
        validate_engines({"engines": {"articles": "native"}})


# --- check_dependencies ---

def _site(tmp_path):
    (tmp_path / "content").mkdir()
    pages = tmp_path / "xsl" / "pages"
    pages.mkdir(parents=True)
    for f in REQUIRED_XSL_FILES:
        (pages / f).write_text(MINIMAL_XSLT)
    return {
        "paths": {
            "content_dir": "content",
            "xsl_dir": "xsl",
        },
    }


def test_check_dependencies_passes(tmp_path):
    check_dependencies(_site(tmp_path), tmp_path)


def test_check_dependencies_skips_native_xsl_files(tmp_path):
    cfg = _site(tmp_path)
    cfg["engines"] = {
        section: "lxml" for section in SECTION_XSL
    }
    cfg["engines"].update({"sitemap": "native", "search": "native"})
    for section in ("sitemap", "search"):
        (tmp_path / "xsl" / "pages" / SECTION_XSL[section]).unlink()
    check_dependencies(cfg, tmp_path)


def test_check_dependencies_missing_content_dir(tmp_path):
    cfg = _site(tmp_path)
    (tmp_path / "content").rmdir()
    with pytest.raises(FileNotFoundError, match="content_dir"):
        check_dependencies(cfg, tmp_path)


def test_check_dependencies_rejects_content_file(tmp_path):
    cfg = _site(tmp_path)
    (tmp_path / "content").rmdir()
    (tmp_path / "content").write_text("not a directory")
    with pytest.raises(FileNotFoundError, match="content_dir"):
        check_dependencies(cfg, tmp_path)


def test_check_dependencies_missing_pages_dir(tmp_path):
    cfg = _site(tmp_path)
    shutil.rmtree(tmp_path / "xsl" / "pages")
    with pytest.raises(FileNotFoundError, match="XSL pages directory"):
        check_dependencies(cfg, tmp_path)


def test_check_dependencies_rejects_pages_file(tmp_path):
    cfg = _site(tmp_path)
    shutil.rmtree(tmp_path / "xsl" / "pages")
    (tmp_path / "xsl" / "pages").write_text("not a directory")
    with pytest.raises(FileNotFoundError, match="XSL pages directory"):
        check_dependencies(cfg, tmp_path)


def test_check_dependencies_missing_xsl_file(tmp_path):
    cfg = _site(tmp_path)
    (tmp_path / "xsl" / "pages" / "article.xsl").unlink()
    with pytest.raises(FileNotFoundError, match="article.xsl"):
        check_dependencies(cfg, tmp_path)


def test_check_dependencies_rejects_xsl_directory(tmp_path):
    cfg = _site(tmp_path)
    article_xsl = tmp_path / "xsl" / "pages" / "article.xsl"
    article_xsl.unlink()
    article_xsl.mkdir()
    with pytest.raises(FileNotFoundError, match="article.xsl"):
        check_dependencies(cfg, tmp_path)


# --- TransformEngine abstract ---

def test_transform_engine_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        TransformEngine()  # type: ignore[abstract]
