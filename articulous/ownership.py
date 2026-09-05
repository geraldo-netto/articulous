"""Persistent output ownership, independent of disposable fingerprints."""
import json
from pathlib import Path

from .filesystem import open_regular_file, write_text_atomic


def ownership_path(output_dir: Path) -> Path:
    output = output_dir.resolve()
    return output.parent / f".{output.name}.articulous-ownership.json"


def _valid_output_path(value) -> bool:
    if not isinstance(value, str):
        return False
    path = Path(value)
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts and path.parts[0] != "assets"


def _validate_outputs(outputs) -> dict:
    if not isinstance(outputs, dict) or not all(
        isinstance(key, str) and _valid_output_path(value) for key, value in outputs.items()
    ):
        raise ValueError("Invalid output ownership entries; restore ownership or use an empty output tree")
    return outputs


def _legacy_ownership(output_dir: Path, legacy) -> dict:
    if legacy is not None:
        return _validate_outputs(legacy)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Output ownership unavailable; restore ownership or use an empty output tree")
    return {}


def load_ownership(output_dir: Path, legacy=None) -> dict:
    path = ownership_path(output_dir)
    try:
        with open_regular_file(path) as source:
            data = json.loads(source.read().decode("utf-8"))
    except FileNotFoundError:
        return _legacy_ownership(output_dir, legacy)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid output ownership at {path}; restore it before building") from error
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("output_dir") != str(output_dir.resolve()):
        raise ValueError(f"Invalid output ownership identity at {path}")
    return _validate_outputs(data.get("outputs"))


def save_ownership(output_dir: Path, outputs: dict) -> None:
    path = ownership_path(output_dir)
    text = json.dumps({"version": 1, "output_dir": str(output_dir.resolve()),
                       "outputs": outputs}, indent=2, sort_keys=True)
    try:
        with open_regular_file(path) as source:
            if source.read() == text.encode("utf-8"):
                return
    except FileNotFoundError:
        pass
    write_text_atomic(path, text)
