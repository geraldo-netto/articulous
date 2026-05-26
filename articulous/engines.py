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
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, Optional

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

class TransformEngine(ABC):
    """
    Abstract base class for XSLT transformation engines.

    Subclasses implement ``_do_transform``; ``run`` owns the dry-run
    guard, path coercion, and parent-dir creation so every engine
    behaves identically at the call site.
    """
    # ``name`` is the strategy-registry key (see :func:`make_engine`) and
    # also identifies the engine in the dry-run debug log.
    name: ClassVar[str]

    def run(
        self,
        xml_path: Path,
        xsl_path: Path,
        output_path: Path,
        dry_run: bool = False,
    ) -> None:
        xml_path = Path(xml_path)
        xsl_path = Path(xsl_path)
        output_path = Path(output_path)

        if dry_run:
            logging.debug(
                f"[DRY RUN] {self.name}: {xml_path} -> {output_path}"
            )
            return

        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._do_transform(xml_path, xsl_path, output_path)

    @abstractmethod
    def _do_transform(self, xml_path: Path, xsl_path: Path, output_path: Path) -> None:
        ...


class LxmlEngine(TransformEngine):
    name = "lxml"

    def _do_transform(self, xml_path, xsl_path, output_path):
        logging.debug(f"Running lxml transform: {xml_path} -> {output_path}")
        try:
            dom = etree.parse(str(xml_path), parser=safe_xml_parser())
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

    def _do_transform(self, xml_path, xsl_path, output_path):
        cmd = [
            str(self.saxonc_bin),
            f"-s:{xml_path}",
            f"-xsl:{xsl_path}",
            f"-o:{output_path}",
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
