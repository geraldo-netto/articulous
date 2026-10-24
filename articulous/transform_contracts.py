"""Transform inputs, synchronous engine interface and provider-neutral failures."""
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

XmlInput = Path | bytes
TransformParameters = Mapping[str, str]


@dataclass(frozen=True)
class ExecutionCapabilities:
    external_process: bool = False

    def __post_init__(self):
        if type(self.external_process) is not bool:
            raise ValueError('Engine execution capability must be boolean')


class TransformFailure(ValueError):
    def __init__(self, operation: str, detail: str, returncode: int | None = None):
        self.operation = operation
        self.detail = detail
        self.returncode = returncode
        super().__init__(f'{operation}: {detail}')


def require_parameters(value):
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError('Transform parameters must be a string mapping')
    for key, item in value.items():
        if not isinstance(key, str) or not key or not isinstance(item, str):
            raise ValueError('Transform parameters require nonempty string names and string values')


@runtime_checkable
class TransformEngine(Protocol):
    @property
    def name(self) -> str:
        ...

    @property
    def cache_identity(self) -> str:
        ...

    @property
    def capabilities(self) -> ExecutionCapabilities:
        ...

    def prepare_stylesheet(self, path: Path) -> str:
        """Capture the stylesheet/dependencies and return its opaque revision token."""
        ...

    def resolve_stylesheet_fingerprint(self, path: Path, fingerprint: str) -> str:
        ...

    def run(self, xml_input: XmlInput, xsl_path: Path, output_path: Path,
            dry_run: bool = False, stylesheet_fingerprint: str | None = None,
            xml_base_uri: str | None = None, parameters: TransformParameters | None = None) -> None:
        """Borrow stable inputs until synchronous settlement; return None.

        Dry runs publish nothing. TransformFailure preserves prior output.
        Revision tokens identify captured stylesheets; parameter values are literal strings.
        Native work settles before publication. Uncertain cleanup raises
        process_contracts.NativeCleanupError and retains private inputs for recovery.
        """
        ...


def require_transform(value: object) -> TransformEngine:
    if not isinstance(value, TransformEngine):
        raise TransformFailure('admission', 'Incomplete transform engine contract')
    return value
