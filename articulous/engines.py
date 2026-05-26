"""
Transform engines and the dependency-check machinery that backs them.

Engines follow a strategy pattern: each concrete engine subclasses
:class:`TransformEngine` and implements ``_do_transform``. The base
class owns the dry-run check so engines never duplicate it.

The module also owns the SECTION_XSL map (section name -> XSL file
basename) so the dependency checker and the build pipeline cannot
drift apart on which XSL files matter.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, Optional, Union

from lxml import etree


SECTION_XSL = {
    "articles": "article.xsl",
    "index": "index.xsl",
    "tags": "tags.xsl",
    "rss": "rss.xsl",
    "sitemap": "sitemap.xsl",
    "search": "search.xsl",
}

REQUIRED_XSL_FILES = sorted(set(SECTION_XSL.values()))

VALID_ENGINES = {"saxonc", "lxml"}


def safe_xml_parser() -> etree.XMLParser:
    """XXE-safe parser used by every XML read in the project."""
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)


# ------------------------------------------------------------
# Engine strategy
# ------------------------------------------------------------

XmlInput = Union[Path, bytes]


class TransformEngine(ABC):
    """
    Abstract base class for XSLT transformation engines.

    Subclasses implement ``_do_transform``; ``run`` owns the dry-run
    guard, path coercion, and parent-dir creation so every engine
    behaves identically at the call site.

    ``xml_input`` may be a :class:`Path` (existing file on disk) or
    :class:`bytes` (an in-memory XML document). The latter lets the
    pipeline hand a freshly-synthesised model XML to lxml without the
    write-temp-then-re-read round-trip; engines that need a real path
    (SaxonC) materialise the bytes themselves.
    """
    # ``name`` is the strategy-registry key (see :func:`make_engine`) and
    # also identifies the engine in the dry-run debug log.
    name: ClassVar[str]

    def run(
        self,
        xml_input: XmlInput,
        xsl_path: Path,
        output_path: Path,
        dry_run: bool = False,
    ) -> None:
        xsl_path = Path(xsl_path)
        output_path = Path(output_path)
        normalised: XmlInput = (
            xml_input if isinstance(xml_input, bytes) else Path(xml_input)
        )

        if dry_run:
            label = "<bytes>" if isinstance(normalised, bytes) else normalised
            logging.debug(f"[DRY RUN] {self.name}: {label} -> {output_path}")
            return

        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._do_transform(normalised, xsl_path, output_path)

    @abstractmethod
    def _do_transform(
        self, xml_input: XmlInput, xsl_path: Path, output_path: Path,
    ) -> None:
        ...


class LxmlEngine(TransformEngine):
    name = "lxml"

    def _do_transform(self, xml_input, xsl_path, output_path):
        logging.debug(f"Running lxml transform -> {output_path}")
        try:
            if isinstance(xml_input, bytes):
                dom = etree.fromstring(xml_input, parser=safe_xml_parser())
            else:
                dom = etree.parse(str(xml_input), parser=safe_xml_parser())
            xslt = etree.XSLT(
                etree.parse(str(xsl_path), parser=safe_xml_parser())
            )
            result = xslt(dom)
        except (etree.XMLSyntaxError, etree.XSLTParseError, etree.XSLTApplyError) as e:
            logging.error(f"lxml transform failed: {e}")
            raise
        output_path.write_text(str(result), encoding="utf-8")


class SaxonCEngine(TransformEngine):
    name = "saxonc"

    def __init__(self, saxonc_bin: Path):
        self.saxonc_bin = saxonc_bin

    def _do_transform(self, xml_input, xsl_path, output_path):
        if isinstance(xml_input, bytes):
            # SaxonC CLI needs a real path. Materialise to a transient
            # temp file, clean up afterwards regardless of outcome.
            with tempfile.NamedTemporaryFile(
                suffix=".xml", delete=False,
            ) as f:
                f.write(xml_input)
                tmp_path = Path(f.name)
            try:
                self._run_saxon(tmp_path, xsl_path, output_path)
            finally:
                tmp_path.unlink(missing_ok=True)
        else:
            self._run_saxon(xml_input, xsl_path, output_path)

    def _run_saxon(self, xml_path: Path, xsl_path: Path, output_path: Path):
        # SEC-05 hardening:
        # 1. Pre-resolve to absolute paths. On every supported platform
        #    an absolute path starts with a path separator (POSIX) or a
        #    drive letter (Windows), neither of which can be confused
        #    with a CLI flag.
        # 2. Defence-in-depth: explicitly reject any path that, after
        #    resolution, still begins with '-'. Saxon's "-s:VAL" form
        #    already consumes the leading dash so this is unreachable
        #    in practice, but the assertion documents the boundary.
        resolved = {
            "xml": xml_path.resolve(),
            "xsl": xsl_path.resolve(),
            "output": output_path.resolve(),
        }
        for label, p in resolved.items():
            if str(p).startswith("-"):
                raise ValueError(
                    f"SaxonC {label} path begins with '-', which can be "
                    f"misparsed by the Saxon CLI: {p}"
                )
        cmd = [
            str(self.saxonc_bin),
            f"-s:{resolved['xml']}",
            f"-xsl:{resolved['xsl']}",
            f"-o:{resolved['output']}",
        ]
        logging.debug(f"Running SaxonC: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            logging.error(f"SaxonC transform failed: {e}")
            raise


# ------------------------------------------------------------
# Engine factories + validation
# ------------------------------------------------------------

def configure_saxonc(config) -> Optional[Path]:
    """
    Validate SaxonC installation and return the path to the Transform
    binary, or ``None`` (the system falls back to lxml).
    """
    saxon_home = config["saxonc"].get("home")
    if not saxon_home:
        logging.debug("SaxonC home not configured — using lxml engine")
        return None

    transform_bin = Path(saxon_home) / "bin" / "Transform"
    if not transform_bin.exists():
        logging.warning(f"SaxonC Transform binary not found at: {transform_bin}")
        return None

    logging.info(f"SaxonC detected at: {transform_bin}")
    return transform_bin


def make_engine(name: str, saxonc_bin: Optional[Path]) -> TransformEngine:
    """
    Return the engine instance for a configured engine name.

    Requesting "saxonc" without a usable binary falls back to the
    lxml engine, matching the historical behaviour.
    """
    if name == "saxonc" and saxonc_bin is not None:
        return SaxonCEngine(saxonc_bin)
    return LxmlEngine()


def validate_engines(config) -> None:
    """
    Raise :class:`ValueError` if any per-section engine name in the
    config is not one we know how to run.
    """
    bad = {
        section: name
        for section, name in config["engines"].items()
        if name not in VALID_ENGINES
    }
    if bad:
        raise ValueError(
            f"Unknown engine(s) configured: {bad}. "
            f"Valid engines: {sorted(VALID_ENGINES)}"
        )


# ------------------------------------------------------------
# Dependency check
# ------------------------------------------------------------

def check_dependencies(config, project_root: Path) -> None:
    """
    Ensure required directories and XSL files exist. Raises
    :class:`FileNotFoundError` on anything missing.
    """
    paths = config["paths"]
    content_dir = project_root / paths["content_dir"]
    xsl_dir = project_root / paths["xsl_dir"]
    output_dir = project_root / paths["output_dir"]

    for d, name in [
        (content_dir, "content_dir"),
        (xsl_dir, "xsl_dir"),
        (output_dir, "output_dir"),
    ]:
        if not d.exists():
            raise FileNotFoundError(
                f"Required directory '{name}' not found: {d}"
            )

    pages_dir = xsl_dir / "pages"
    if not pages_dir.exists():
        raise FileNotFoundError(f"Missing XSL pages directory: {pages_dir}")

    for fname in REQUIRED_XSL_FILES:
        f = pages_dir / fname
        if not f.exists():
            raise FileNotFoundError(f"Missing required XSL file: {f}")

    logging.debug("All dependencies verified successfully.")
