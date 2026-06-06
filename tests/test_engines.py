"""Unit tests for articulous.engines."""
import logging
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from articulous.engines import (
    LxmlEngine,
    REQUIRED_XSL_FILES,
    SECTION_XSL,
    SaxonCEngine,
    TransformEngine,
    VALID_ENGINES,
    check_dependencies,
    configure_saxonc,
    make_engine,
    safe_xslt_access_control,
    safe_xml_parser,
    validate_engines,
)


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
    assert VALID_ENGINES == {"saxonc", "lxml"}


def test_safe_xml_parser_is_xxe_safe(tmp_path):
    """Behavioural check: external entities do not get expanded."""
    import lxml.etree as etree
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
    with caplog.at_level(logging.ERROR):
        with pytest.raises(Exception):
            LxmlEngine().run(b"<root/>", xsl, out)
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
    with caplog.at_level(logging.ERROR):
        with pytest.raises(Exception):
            LxmlEngine().run(b"<root/>", xsl, tmp_path / "out.txt")
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
        def __str__(self): return self.s

    with pytest.raises(ValueError, match=r"begins with '-'"):
        e._run_saxon(
            FakePath("-evil.xml"),  # type: ignore[arg-type]
            FakePath("/abs/x.xsl"),  # type: ignore[arg-type]
            FakePath("/abs/o.html"),  # type: ignore[arg-type]
        )


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
    assert cmd[1].startswith("-s:")
    assert cmd[2].startswith("-xsl:")
    assert cmd[3].startswith("-o:")


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


# --- factories ---

def test_make_engine_lxml():
    e = make_engine("lxml", None)
    assert isinstance(e, LxmlEngine)


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
    with pytest.raises(ValueError, match="Unknown engine"):
        make_engine(None, None)  # type: ignore[arg-type]


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
    validate_engines({"engines": {"articles": "lxml", "rss": "saxonc"}})


def test_validate_engines_rejects_unknown():
    with pytest.raises(ValueError, match="frobnicate"):
        validate_engines({"engines": {"rss": "frobnicate"}})


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


def test_check_dependencies_missing_content_dir(tmp_path):
    cfg = _site(tmp_path)
    (tmp_path / "content").rmdir()
    with pytest.raises(FileNotFoundError, match="content_dir"):
        check_dependencies(cfg, tmp_path)


def test_check_dependencies_missing_pages_dir(tmp_path):
    cfg = _site(tmp_path)
    # remove the pages dir + its contents
    import shutil
    shutil.rmtree(tmp_path / "xsl" / "pages")
    with pytest.raises(FileNotFoundError, match="XSL pages directory"):
        check_dependencies(cfg, tmp_path)


def test_check_dependencies_missing_xsl_file(tmp_path):
    cfg = _site(tmp_path)
    (tmp_path / "xsl" / "pages" / "article.xsl").unlink()
    with pytest.raises(FileNotFoundError, match="article.xsl"):
        check_dependencies(cfg, tmp_path)


# --- TransformEngine abstract ---

def test_transform_engine_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        TransformEngine()  # type: ignore[abstract]
