"""
Transform engines and the dependency-check machinery that backs them.

Engines follow a strategy pattern: each concrete engine subclasses
:class:`TransformEngine` and implements ``_do_transform``. The base
class owns the dry-run check so engines never duplicate it.

Section-to-XSL metadata lives in :mod:`articulous.sections` so config,
CLI validation, dependency checks, and the build pipeline cannot drift.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, Optional, Union
from urllib.parse import urljoin, urlsplit
from urllib.request import url2pathname

from lxml import etree  # type: ignore[attr-defined]

from .filesystem import atomic_output
from .sections import REQUIRED_XSL_FILES, SECTION_XSL

__all__ = [
    "LxmlEngine",
    "NativeEngine",
    "REQUIRED_XSL_FILES",
    "SECTION_XSL",
    "SaxonCEngine",
    "TransformEngine",
    "check_dependencies",
    "configure_saxonc",
    "make_engine",
    "safe_xml_parser",
    "safe_xslt_access_control",
    "stylesheet_hash",
    "validate_engines",
]

VALID_ENGINES = {"saxonc", "lxml", "native"}
NATIVE_SECTIONS = {"sitemap", "search"}
_XSL_NAMESPACE = {"xsl": "http://www.w3.org/1999/XSL/Transform"}


def safe_xml_parser() -> etree.XMLParser:
    """
    XXE-safe parser used by every XML read in the project.

    Disables external entity resolution, network access, and DTD loading
    so untrusted article XML cannot exfiltrate files or hit internal
    endpoints (SonarQube python:S2755).
    """
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
    )


def safe_xslt_access_control() -> etree.XSLTAccessControl:
    return etree.XSLTAccessControl(
        read_file=False,
        write_file=False,
        create_dir=False,
        read_network=False,
        write_network=False,
    )


def _stylesheet_dependency(node) -> Path:
    uri = urlsplit(urljoin(node.base, node.attrib["href"]))
    if uri.scheme != "file" or uri.netloc not in ("", "localhost"):
        raise ValueError("Stylesheet dependencies must use local file URIs")
    if uri.query or uri.fragment:
        raise ValueError("Stylesheet dependency URIs cannot include queries or fragments")
    return Path(url2pathname(uri.path))


def _update_stylesheet_hash(path: Path, digest, seen: set[Path]) -> None:
    resolved = path.resolve()
    if resolved in seen:
        return
    seen.add(resolved)
    content = resolved.read_bytes()
    digest.update(len(content).to_bytes(8, "big"))
    digest.update(content)
    root = etree.fromstring(content, parser=safe_xml_parser(), base_url=resolved.as_uri())
    nodes = root.xpath(
        "//xsl:include[@href] | //xsl:import[@href]",
        namespaces=_XSL_NAMESPACE,
    )
    for node in nodes:
        _update_stylesheet_hash(_stylesheet_dependency(node), digest, seen)


def stylesheet_hash(path: Path) -> str:
    digest = hashlib.sha256()
    _update_stylesheet_hash(path, digest, set())
    return digest.hexdigest()


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

    @property
    @abstractmethod
    def cache_identity(self) -> str:
        ...

    def run(
        self,
        xml_input: XmlInput,
        xsl_path: Path,
        output_path: Path,
        dry_run: bool = False,
        stylesheet_fingerprint: Optional[str] = None,
    ) -> None:
        """Run the transform unless dry-run is set; returns ``None``."""
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
        self._do_transform(
            normalised, xsl_path, output_path, stylesheet_fingerprint
        )

    @abstractmethod
    def _do_transform(
        self,
        xml_input: XmlInput,
        xsl_path: Path,
        output_path: Path,
        stylesheet_fingerprint: Optional[str] = None,
    ) -> None:
        ...


class NativeEngine:
    name = "native"

    @property
    def cache_identity(self) -> str:
        return "native:v3"


class LxmlEngine(TransformEngine):
    name = "lxml"

    def __init__(self):
        self._thread_local = threading.local()

    @property
    def cache_identity(self) -> str:
        return f"{self.name}:libxslt={etree.LIBXSLT_VERSION}:serialization=v2"

    def _stylesheet_cache(self) -> dict:
        cache = getattr(self._thread_local, "stylesheets", None)
        if cache is None:
            cache = {}
            self._thread_local.stylesheets = cache
        return cache

    def _compiled_stylesheet(self, xsl_path: Path, fingerprint: Optional[str]):
        fingerprint = fingerprint or stylesheet_hash(xsl_path)
        key = (xsl_path.resolve(), fingerprint)
        cache = self._stylesheet_cache()
        if key not in cache:
            cache[key] = etree.XSLT(
                etree.parse(str(xsl_path), parser=safe_xml_parser()),
                access_control=safe_xslt_access_control(),
            )
        return cache[key]

    def _do_transform(
        self, xml_input, xsl_path, output_path, stylesheet_fingerprint=None,
    ):
        logging.debug(f"Running lxml transform -> {output_path}")
        try:
            parser = safe_xml_parser()
            if isinstance(xml_input, bytes):
                dom = etree.fromstring(xml_input, parser=parser)
            else:
                dom = etree.parse(str(xml_input), parser=parser)
            xslt = self._compiled_stylesheet(
                xsl_path, stylesheet_fingerprint,
            )
            result = xslt(dom)
        except (etree.XMLSyntaxError, etree.XSLTParseError, etree.XSLTApplyError):
            logging.exception("lxml transform failed")
            raise
        with atomic_output(output_path) as staged:
            staged.write_bytes(bytes(result))


class SaxonCEngine(TransformEngine):
    name = "saxonc"

    def __init__(self, saxonc_bin: Path):
        self.saxonc_bin = saxonc_bin

    @property
    def cache_identity(self) -> str:
        binary = self.saxonc_bin.resolve()
        try:
            stat = binary.stat()
            revision = f"{stat.st_size}:{stat.st_mtime_ns}"
        except OSError:
            revision = "missing"
        return f"{self.name}:{binary}:{revision}:ext=off:xi=off"

    def _do_transform(
        self, xml_input, xsl_path, output_path, stylesheet_fingerprint=None,
    ):
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
        with atomic_output(resolved["output"]) as staged:
            cmd = [
                str(self.saxonc_bin),
                "-ext:off",
                "-xi:off",
                f"-s:{resolved['xml']}",
                f"-xsl:{resolved['xsl']}",
                f"-o:{staged}",
            ]
            logging.debug(f"Running SaxonC: {' '.join(cmd)}")
            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError:
                logging.exception("SaxonC transform failed")
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
        discovered = shutil.which("Transform")
        if discovered:
            logging.info(f"SaxonC detected on PATH: {discovered}")
            return Path(discovered)
        logging.debug("SaxonC home not configured and Transform not on PATH")
        return None

    transform_bin = Path(saxon_home) / "bin" / "Transform"
    if not transform_bin.is_file() or not os.access(transform_bin, os.X_OK):
        logging.warning(f"SaxonC Transform binary not executable at: {transform_bin}")
        return None

    logging.info(f"SaxonC detected at: {transform_bin}")
    return transform_bin


def make_engine(
    name: str, saxonc_bin: Optional[Path],
) -> TransformEngine | NativeEngine:
    """
    Return the engine instance for a configured engine name.

    Unknown engine names raise :class:`ValueError` so a typo in the
    config surfaces at build-context construction rather than as a
    surprising silent fallback. (The same set of names is enforced
    earlier by :func:`validate_engines`; the check here protects
    direct callers.) Requesting ``"saxonc"`` without a usable binary
    still falls back to the lxml engine, matching the historical
    behaviour.
    """
    if name not in VALID_ENGINES:
        raise ValueError(
            f"Unknown engine name {name!r}; "
            f"must be one of {sorted(VALID_ENGINES)}"
        )
    if name == "native":
        return NativeEngine()
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
    invalid_native = sorted(
        section for section, name in config["engines"].items()
        if name == "native" and section not in NATIVE_SECTIONS
    )
    if invalid_native:
        raise ValueError(
            f"Native engine is only supported for "
            f"{sorted(NATIVE_SECTIONS)}; got {invalid_native}"
        )


# ------------------------------------------------------------
# Dependency check
# ------------------------------------------------------------

def check_dependencies(config, project_root: Path) -> None:
    """
    Ensure required *input* directories and XSL files exist. Raises
    :class:`FileNotFoundError` on anything missing. The output directory
    is intentionally not checked here — :func:`run_build` creates it.
    """
    paths = config["paths"]
    content_dir = project_root / paths["content_dir"]
    xsl_dir = project_root / paths["xsl_dir"]

    for d, name in [
        (content_dir, "content_dir"),
        (xsl_dir, "xsl_dir"),
    ]:
        if not d.is_dir():
            raise FileNotFoundError(
                f"Required directory '{name}' not found: {d}"
            )

    pages_dir = xsl_dir / "pages"
    if not pages_dir.is_dir():
        raise FileNotFoundError(f"Missing XSL pages directory: {pages_dir}")

    configured = config.get("engines")
    required_xsl = REQUIRED_XSL_FILES
    if isinstance(configured, dict):
        required_xsl = sorted(
            SECTION_XSL[section]
            for section, name in configured.items()
            if name != "native"
        )
    for fname in required_xsl:
        f = pages_dir / fname
        if not f.is_file():
            raise FileNotFoundError(f"Missing required XSL file: {f}")

    logging.debug("All dependencies verified successfully.")
