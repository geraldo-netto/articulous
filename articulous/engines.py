"""
Transform engines and the dependency-check machinery that backs them.

Concrete XSLT adapters share :class:`XsltEngine` snapshot and dry-run machinery.
Consumers depend on the independent structural ``TransformEngine`` contract;
external providers need not inherit implementation storage. NativeEngine
identifies native writers implemented by the build pipeline.

Section-to-XSL metadata lives in :mod:`articulous.sections` so config,
CLI validation, dependency checks, and the build pipeline cannot drift.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Optional
from urllib.parse import urljoin, urlsplit
from urllib.request import url2pathname

from lxml import etree  # type: ignore[attr-defined]

from .filesystem import StagedOutput, TempWorkspace, atomic_output, open_regular_file, validate_output_path
from .sections import REQUIRED_XSL_FILES, SECTION_XSL
from .configuration_contracts import VALID_ENGINES, valid_engine_name
from .transform_contracts import (
    ExecutionCapabilities, TransformEngine, TransformFailure, TransformParameters,
    XmlInput, require_parameters,
)

__all__ = [
    "LxmlEngine",
    "NativeEngine",
    "REQUIRED_XSL_FILES",
    "SECTION_XSL",
    "SaxonCEngine",
    "check_dependencies",
    "configure_saxonc",
    "make_engine",
    "safe_xml_parser",
    "safe_xslt_access_control",
    "stylesheet_hash",
]

_XSL_NAMESPACE = {"xsl": "http://www.w3.org/1999/XSL/Transform"}
_ADAPTER_ERRORS = (ValueError, TypeError, OSError, etree.Error, subprocess.CalledProcessError)
_LOCAL_EXECUTION = ExecutionCapabilities()
_EXTERNAL_EXECUTION = ExecutionCapabilities(True)


def _transform_failure(operation, error):
    return TransformFailure(operation, str(error), getattr(error, 'returncode', None))


def safe_xml_parser() -> etree.XMLParser:
    """
    Parser settings for in-process article and stylesheet XML reads.

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


def _stylesheet_uri_path(value: str) -> Path:
    uri = urlsplit(value)
    if uri.scheme != "file" or uri.netloc not in ("", "localhost"):
        raise ValueError("Stylesheet dependencies must use local file URIs")
    if uri.query or uri.fragment:
        raise ValueError("Stylesheet dependency URIs cannot include queries or fragments")
    return Path(url2pathname(uri.path))


@dataclass(frozen=True)
class _StylesheetSnapshot:
    root_uri: str
    documents: tuple[tuple[str, bytes], ...]
    fingerprint: str


def _collect_stylesheets(path: Path, documents: dict, ancestors: frozenset[Path]) -> None:
    logical = Path(os.path.abspath(path))
    uri = logical.as_uri()
    if uri in documents:
        return
    resolved = logical.resolve()
    if resolved in ancestors:
        raise ValueError(f"Circular stylesheet dependency: {logical}")
    with open_regular_file(resolved) as source:
        content = source.read()
    documents[uri] = content
    root = etree.fromstring(content, parser=safe_xml_parser(), base_url=uri)
    nodes = root.xpath(
        "//xsl:include[@href] | //xsl:import[@href]",
        namespaces=_XSL_NAMESPACE,
    )
    for node in nodes:
        dependency = _stylesheet_uri_path(urljoin(node.base, node.attrib["href"]))
        _collect_stylesheets(dependency, documents, ancestors | {resolved})


def _snapshot_stylesheet(path: Path) -> _StylesheetSnapshot:
    documents: dict[str, bytes] = {}
    _collect_stylesheets(path, documents, frozenset())
    digest = hashlib.sha256()
    for uri, content in documents.items():
        for data in (uri.encode("utf-8"), content):
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
    return _StylesheetSnapshot(next(iter(documents)), tuple(documents.items()), digest.hexdigest())


def stylesheet_hash(path: Path) -> str:
    return _snapshot_stylesheet(path).fingerprint


class _SnapshotResolver(etree.Resolver):
    def __init__(self, snapshot: _StylesheetSnapshot):
        self._documents = dict(snapshot.documents)

    def resolve(self, url, pubid, context):
        uri = Path(os.path.abspath(_stylesheet_uri_path(url))).as_uri()
        if uri not in self._documents:
            raise ValueError(f"Stylesheet resource is outside the captured snapshot: {uri}")
        return self.resolve_string(self._documents[uri], context, base_url=uri)


# ------------------------------------------------------------
# Engine strategy
# ------------------------------------------------------------

class XsltEngine(ABC):
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

    def __init__(self):
        self._snapshots: dict[tuple[str, str], _StylesheetSnapshot] = {}

    def prepare_stylesheet(self, path: Path) -> str:
        try:
            snapshot = _snapshot_stylesheet(path)
        except _ADAPTER_ERRORS as error:
            raise _transform_failure('prepare_stylesheet', error) from error
        self._snapshots[(snapshot.root_uri, snapshot.fingerprint)] = snapshot
        return snapshot.fingerprint

    def resolve_stylesheet_fingerprint(self, path: Path, fingerprint: str) -> str:
        return fingerprint

    def _stylesheet_snapshot(self, path: Path, fingerprint: Optional[str]) -> _StylesheetSnapshot:
        uri = Path(os.path.abspath(path)).as_uri()
        snapshot = self._snapshots.get((uri, fingerprint or ""))
        if snapshot is None:
            snapshot = _snapshot_stylesheet(path)
            if fingerprint is not None and fingerprint != snapshot.fingerprint:
                raise ValueError(f"Stylesheet fingerprint changed since planning: {path}")
        return snapshot

    @property
    @abstractmethod
    def cache_identity(self) -> str:
        ...

    @property
    def capabilities(self) -> ExecutionCapabilities:
        return _LOCAL_EXECUTION

    def run(
        self,
        xml_input: XmlInput,
        xsl_path: Path,
        output_path: Path,
        dry_run: bool = False,
        stylesheet_fingerprint: Optional[str] = None,
        xml_base_uri: Optional[str] = None,
        parameters: TransformParameters | None = None,
    ) -> None:
        """Run the transform unless dry-run is set; returns ``None``."""
        try:
            require_parameters(parameters)
            self._run_transform(xml_input, xsl_path, output_path, dry_run,
                                stylesheet_fingerprint, xml_base_uri, parameters)
        except TransformFailure:
            raise
        except _ADAPTER_ERRORS as error:
            raise _transform_failure('transform', error) from error

    def _run_transform(self, xml_input, xsl_path, output_path, dry_run,
                       stylesheet_fingerprint, xml_base_uri, parameters):
        if type(dry_run) is not bool:
            raise ValueError('Transform dry_run must be boolean')
        xsl_path = Path(xsl_path)
        output_path = Path(output_path)
        normalised: XmlInput = (
            xml_input if isinstance(xml_input, bytes) else Path(xml_input)
        )

        if dry_run:
            label = "<bytes>" if isinstance(normalised, bytes) else normalised
            logging.debug(f"[DRY RUN] {self.name}: {label} -> {output_path}")
            return

        validate_output_path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._do_transform(
            normalised, xsl_path, output_path, stylesheet_fingerprint, xml_base_uri, parameters,
        )

    @abstractmethod
    def _do_transform(
        self,
        xml_input: XmlInput,
        xsl_path: Path,
        output_path: Path,
        stylesheet_fingerprint: Optional[str] = None,
        xml_base_uri: Optional[str] = None,
        parameters: TransformParameters | None = None,
    ) -> None:
        ...


class NativeEngine:
    name = "native"
    capabilities = _LOCAL_EXECUTION

    @property
    def cache_identity(self) -> str:
        return "native:v3"


class StylesheetCapture:
    def __init__(self):
        self._engines = []

    def wrap(self, engine):
        if not isinstance(engine, TransformEngine):
            return engine
        captured = _DeferredEngine(engine)
        self._engines.append(captured)
        return captured

    def freeze(self):
        for engine in self._engines:
            engine.freeze()


class _DeferredEngine(XsltEngine):
    name = 'captured'

    def __init__(self, engine):
        super().__init__()
        self._engine = engine
        self._paths = {}
        self._frozen = False

    @property
    def cache_identity(self):
        return self._engine.cache_identity

    @property
    def capabilities(self):
        return self._engine.capabilities

    def prepare_stylesheet(self, path):
        if self._frozen:
            raise TransformFailure('capture', 'Stylesheet capture is frozen')
        path = Path(path)
        self._paths[path] = ''
        return path.as_posix()

    def freeze(self):
        for path in self._paths:
            self._paths[path] = self._engine.prepare_stylesheet(path)
        self._frozen = True

    def resolve_stylesheet_fingerprint(self, path, fingerprint):
        if not self._frozen:
            raise TransformFailure('capture', 'Stylesheet capture is not frozen')
        try:
            return self._paths[Path(path)]
        except (KeyError, TypeError, ValueError) as error:
            raise TransformFailure('capture', 'Stylesheet was not captured') from error

    def _do_transform(self, xml_input, xsl_path, output_path, stylesheet_fingerprint=None,
                      xml_base_uri=None, parameters=None):
        self._engine.run(xml_input, xsl_path, output_path,
                         stylesheet_fingerprint=self.resolve_stylesheet_fingerprint(xsl_path, ''),
                         xml_base_uri=xml_base_uri, parameters=parameters)


class LxmlEngine(XsltEngine):
    name = "lxml"

    def __init__(self):
        super().__init__()
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
        snapshot = self._stylesheet_snapshot(xsl_path, fingerprint)
        key = (snapshot.root_uri, snapshot.fingerprint)
        cache = self._stylesheet_cache()
        if key not in cache:
            parser = safe_xml_parser()
            parser.resolvers.add(_SnapshotResolver(snapshot))
            cache[key] = etree.XSLT(
                etree.fromstring(snapshot.documents[0][1], parser=parser, base_url=snapshot.root_uri),
                access_control=safe_xslt_access_control(),
            )
        return cache[key]

    def _do_transform(
        self, xml_input, xsl_path, output_path, stylesheet_fingerprint=None, xml_base_uri=None,
        parameters=None,
    ):
        logging.debug(f"Running lxml transform -> {output_path}")
        try:
            parser = safe_xml_parser()
            if isinstance(xml_input, bytes):
                dom = etree.fromstring(xml_input, parser=parser, base_url=xml_base_uri)
            else:
                dom = etree.parse(str(xml_input), parser=parser)
            xslt = self._compiled_stylesheet(
                xsl_path, stylesheet_fingerprint,
            )
            result = xslt(dom, **{key: etree.XSLT.strparam(value) for key, value in (parameters or {}).items()})
        except (etree.XMLSyntaxError, etree.XSLTParseError, etree.XSLTApplyError):
            logging.exception("lxml transform failed")
            raise
        with atomic_output(output_path, generated=True) as staged:
            staged.write_bytes(bytes(result))


def _xml_with_base(content: bytes, base_uri: Optional[str]) -> bytes:
    if base_uri is None:
        return content
    root = etree.fromstring(content, parser=safe_xml_parser(), base_url=base_uri)
    root.set("{http://www.w3.org/XML/1998/namespace}base", root.base)
    return etree.tostring(root)


def _materialize_parameter(root, name: str, value: str) -> None:
    nodes = root.xpath("./xsl:param[@name=$name]", namespaces=_XSL_NAMESPACE, name=name)
    if nodes:
        node = nodes[0]
    else:
        node = etree.Element("{http://www.w3.org/1999/XSL/Transform}param", name=name)
        root.insert(0, node)
    for child in node:
        node.remove(child)
    node.text = None
    node.attrib.pop("required", None)
    node.set("select", "'" + value.replace("'", "''") + "'")


def _saxon_parameters(root, parameters) -> dict[str, str]:
    command_parameters = {}
    for name, value in (parameters or {}).items():
        if len((name + value).encode("utf-8")) < 32768:
            command_parameters[name] = value
        else:
            _materialize_parameter(root, name, value)
    return command_parameters


def _saxon_configuration(workspace):
    payload = (b'<configuration xmlns="http://saxon.sf.net/ns/configuration">'
               b'<global allowedProtocols="#none"/></configuration>')
    with workspace.named_file('w+b', suffix='.xml') as configuration:
        configuration.write(payload)
        return Path(configuration.name)


class SaxonCEngine(XsltEngine):
    name = "saxonc"

    def __init__(self, saxonc_bin: Path):
        super().__init__()
        self.saxonc_bin = saxonc_bin

    @property
    def capabilities(self) -> ExecutionCapabilities:
        return _EXTERNAL_EXECUTION

    @property
    def cache_identity(self) -> str:
        binary = self.saxonc_bin.resolve()
        try:
            stat = binary.stat()
            revision = f"{stat.st_size}:{stat.st_mtime_ns}"
        except OSError:
            revision = "missing"
        return f"{self.name}:{binary}:{revision}:ext=off:xi=off:protocols=none"

    def _do_transform(
        self, xml_input, xsl_path, output_path, stylesheet_fingerprint=None, xml_base_uri=None,
        parameters=None,
    ):
        snapshot = self._stylesheet_snapshot(xsl_path, stylesheet_fingerprint)
        if len(snapshot.documents) != 1:
            raise ValueError("SaxonC stylesheets must be standalone; includes/imports are not supported")
        root = etree.fromstring(
            snapshot.documents[0][1], parser=safe_xml_parser(), base_url=snapshot.root_uri,
        )
        root.set("{http://www.w3.org/XML/1998/namespace}base", root.base)
        parameters = _saxon_parameters(root, parameters)
        with TempWorkspace() as workspace:
            with workspace.named_file("w+b", suffix=".xsl") as stylesheet:
                stylesheet.write(etree.tostring(root))
                captured_xsl = Path(stylesheet.name)
            if isinstance(xml_input, bytes):
                with workspace.named_file("w+b", suffix=".xml") as f:
                    f.write(_xml_with_base(xml_input, xml_base_uri))
                    xml_input = Path(f.name)
            self._run_saxon(xml_input, captured_xsl, output_path, parameters)

    def _run_saxon(self, xml_path: Path, xsl_path: Path, output_path: Path, parameters=None):
        # Absolute paths prevent filenames from being interpreted as CLI flags.
        resolved = {
            "xml": xml_path.resolve(),
            "xsl": xsl_path.resolve(),
            "output": output_path.absolute(),
        }
        for label, p in resolved.items():
            if str(p).startswith("-"):
                raise ValueError(
                    f"SaxonC {label} path begins with '-', which can be "
                    f"misparsed by the Saxon CLI: {p}"
                )
        with TempWorkspace() as workspace, atomic_output(resolved["output"], generated=True) as staged:
            assert isinstance(staged, StagedOutput)
            configuration = _saxon_configuration(workspace)
            cmd = [
                str(self.saxonc_bin),
                "-ext:off",
                "-xi:off",
                f"-config:{configuration}",
                f"-s:{resolved['xml']}",
                f"-xsl:{resolved['xsl']}",
                f"-o:/dev/fd/{staged.fd}",
            ]
            cmd.extend(f"{key}={value}" for key, value in (parameters or {}).items())
            logging.debug(f"Running SaxonC: {' '.join(cmd)}")
            try:
                subprocess.run(cmd, check=True, pass_fds=(staged.fd,))
            except subprocess.CalledProcessError:
                logging.exception("SaxonC transform failed")
                raise


# ------------------------------------------------------------
# Engine factories + validation
# ------------------------------------------------------------

def configure_saxonc(config) -> Optional[Path]:
    """
    Find an executable Transform binary, or return ``None``.
    The engine factory applies lxml fallback to configured SaxonC sections.
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
    name: object, saxonc_bin: Optional[Path],
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
    if not valid_engine_name(name):
        raise ValueError(
            f"Unknown engine name {name!r}; "
            f"must be one of {sorted(VALID_ENGINES)}"
        )
    if name == "native":
        return NativeEngine()
    if name == "saxonc" and saxonc_bin is not None:
        return SaxonCEngine(saxonc_bin)
    return LxmlEngine()


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
