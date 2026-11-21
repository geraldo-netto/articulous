"""Transform inputs, synchronous engine interface and provider-neutral failures."""
from collections.abc import Mapping
from pathlib import Path
import re
from typing import Protocol, runtime_checkable

XmlInput = Path | bytes
TransformParameters = Mapping[str, str]

# XML 1.0 (Fifth Edition) productions 4 and 4a, with colon reserved for the namespace separator.
_NAME_START = (r'A-Z_a-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff'
               r'\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf'
               r'\ufdf0-\ufffd\U00010000-\U000effff')
_NCNAME = rf'[{_NAME_START}][{_NAME_START}0-9.\u00b7\u0300-\u036f\u203f-\u2040-]*'
_PARAMETER_NAME = re.compile(rf'{_NCNAME}(?::{_NCNAME})?')


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
        if not isinstance(key, str) or not _PARAMETER_NAME.fullmatch(key) or not isinstance(item, str):
            raise ValueError('Transform parameters require XML QName names and string values')


@runtime_checkable
class TransformEngine(Protocol):
    @property
    def name(self) -> str:
        ...

    @property
    def cache_identity(self) -> str:
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
