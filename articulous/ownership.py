"""Persistent output ownership, independent of disposable fingerprints."""
import json
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .filesystem import open_regular_file, write_text_atomic, validate_output_path, validate_regular_file
from .composition_contracts import Route


@dataclass(frozen=True)
class Ownership:
    paths: dict[str, str]
    pending: bool = False
    routes: dict[str, Route] = field(default_factory=dict)


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
    except (FileNotFoundError, NotADirectoryError):
        return None
    return [metadata.st_dev, metadata.st_ino] if stat.S_ISREG(metadata.st_mode) else None


def _valid_identity(identity) -> bool:
    return identity is None or (
        isinstance(identity, list) and len(identity) == 2
        and all(type(value) is int and value >= 0 for value in identity)
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
    if type(data.get('version')) is not int or data['version'] not in (1, 2):
        raise ValueError(f"Invalid output ownership version at {ownership_path(output_dir)}")
    if data.get("version") == 1:
        outputs = _validate_outputs(data.get("outputs"))
        return Ownership({path: key for key, path in outputs.items()})
    if not isinstance(data.get("pending", False), bool):
        raise ValueError(f"Invalid output ownership version or recovery flag at {ownership_path(output_dir)}")
    paths = _validate_outputs(data.get("paths"), path_keys=True)
    return _current_ownership(output_dir, data, paths)


def _decode_routes(values, paths):
    if not isinstance(values, dict):
        raise ValueError('Invalid output route metadata')
    routes = {}
    for key, value in values.items():
        try:
            route = Route(**value)
        except (TypeError, ValueError) as error:
            raise ValueError('Invalid output route metadata') from error
        if route.key != key or paths.get(route.output_path) != key:
            raise ValueError('Output route metadata does not match ownership')
        routes[key] = route
    return routes


def _current_ownership(output_dir, data, paths):
    published = _published_paths(output_dir, paths, data.get('existing', {}))
    routes = _decode_routes(data.get('routes', {}), paths)
    retained = {key: route for key, route in routes.items() if route.output_path in published}
    return Ownership(published, data.get('pending', False), retained)


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


def save_ownership(output_dir: Path, paths: dict, *, pending: bool = False, existing=None, routes=None) -> None:
    path = ownership_path(output_dir)
    text = json.dumps({"version": 2, "output_dir": str(output_dir.resolve()),
                       "paths": paths, "pending": pending, "existing": existing or {},
                       "routes": {key: asdict(route) for key, route in (routes or {}).items()}}, indent=2, sort_keys=True)
    try:
        with open_regular_file(path) as source:
            if source.read() == text.encode("utf-8"):
                return
    except FileNotFoundError:
        pass
    write_text_atomic(path, text)


def journal_ownership(output_dir: Path, previous: dict, planned: dict, *, routes=None) -> None:
    existing = {path: _file_identity(output_dir / path) for path in planned.keys() - previous.keys()}
    save_ownership(output_dir, {**previous, **planned}, pending=True, existing=existing, routes=routes)


def _validate_owned_entry(path, destination, allowed, parents):
    validate_output_path(path)
    relative = path.relative_to(destination)
    if relative.parts[0] == 'assets':
        return
    if relative in allowed:
        validate_regular_file(path)
        return
    if path.is_dir() and relative in parents:
        return
    raise ValueError(f'Refusing to replace unowned output: {relative}')


def validate_owned_output(destination):
    validate_output_path(destination)
    if destination.exists() and not destination.is_dir():
        raise ValueError('Publication output must remain a directory')
    ownership = load_ownership(destination)
    allowed = {Path(path) for path in ownership.paths}
    parents = {parent for path in allowed for parent in path.parents}
    for path in destination.rglob('*'):
        _validate_owned_entry(path, destination, allowed, parents)

    return ownership
