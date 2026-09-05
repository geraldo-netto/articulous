"""Persistent output ownership, independent of disposable fingerprints."""
import json
from dataclasses import dataclass
from pathlib import Path

from .filesystem import open_regular_file, write_text_atomic


@dataclass(frozen=True)
class Ownership:
    paths: dict[str, str]
    pending: bool = False


def ownership_path(output_dir: Path) -> Path:
    output = output_dir.resolve()
    return output.parent / f".{output.name}.articulous-ownership.json"


def _valid_output_path(value) -> bool:
    if not isinstance(value, str):
        return False
    path = Path(value)
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts and path.parts[0] != "assets"


def _validate_outputs(outputs, *, path_keys: bool = False) -> dict:
    if not isinstance(outputs, dict) or not all(
        isinstance(value if path_keys else key, str) and _valid_output_path(key if path_keys else value)
        for key, value in outputs.items()
    ):
        raise ValueError("Invalid output ownership entries; restore ownership or use an empty output tree")
    return outputs


def _legacy_ownership(output_dir: Path, legacy) -> dict:
    if legacy is not None:
        return _validate_outputs(legacy)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Output ownership unavailable; restore ownership or use an empty output tree")
    return {}


def _file_identity(path: Path) -> list[int] | None:
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return None
    return [metadata.st_dev, metadata.st_ino]


def _valid_identity(identity) -> bool:
    return identity is None or (
        isinstance(identity, list) and len(identity) == 2 and all(type(value) is int for value in identity)
    )


def _published_paths(output_dir: Path, paths: dict, existing) -> dict:
    if not isinstance(existing, dict) or not all(
        path in paths and _valid_identity(identity) for path, identity in existing.items()
    ):
        raise ValueError("Invalid output ownership publication identities")
    untouched = {
        path for path, identity in existing.items()
        if identity is not None and _file_identity(output_dir / path) == identity
    }
    return {path: key for path, key in paths.items() if path not in untouched}


def _decode_ownership(output_dir: Path, data) -> Ownership:
    if not isinstance(data, dict) or data.get("output_dir") != str(output_dir.resolve()):
        raise ValueError(f"Invalid output ownership identity at {ownership_path(output_dir)}")
    if data.get("version") == 1:
        outputs = _validate_outputs(data.get("outputs"))
        return Ownership({path: key for key, path in outputs.items()})
    if data.get("version") != 2 or not isinstance(data.get("pending", False), bool):
        raise ValueError(f"Invalid output ownership version or recovery flag at {ownership_path(output_dir)}")
    paths = _validate_outputs(data.get("paths"), path_keys=True)
    return Ownership(_published_paths(output_dir, paths, data.get("existing", {})), data.get("pending", False))


def load_ownership(output_dir: Path, legacy=None, *, allow_pending: bool = True) -> Ownership:
    path = ownership_path(output_dir)
    try:
        with open_regular_file(path) as source:
            data = json.loads(source.read().decode("utf-8"))
    except FileNotFoundError:
        outputs = _legacy_ownership(output_dir, legacy)
        return Ownership({path: key for key, path in outputs.items()})
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid output ownership at {path}; restore it before building") from error
    ownership = _decode_ownership(output_dir, data)
    if ownership.pending and not allow_pending:
        raise ValueError("Interrupted build requires a full recovery build without --only, --lang or --slug")
    return ownership


def save_ownership(output_dir: Path, paths: dict, *, pending: bool = False, existing=None) -> None:
    path = ownership_path(output_dir)
    text = json.dumps({"version": 2, "output_dir": str(output_dir.resolve()),
                       "paths": paths, "pending": pending, "existing": existing or {}}, indent=2, sort_keys=True)
    try:
        with open_regular_file(path) as source:
            if source.read() == text.encode("utf-8"):
                return
    except FileNotFoundError:
        pass
    write_text_atomic(path, text)


def journal_ownership(output_dir: Path, previous: dict, planned: dict) -> None:
    existing = {path: _file_identity(output_dir / path) for path in planned.keys() - previous.keys()}
    save_ownership(output_dir, {**previous, **planned}, pending=True, existing=existing)
