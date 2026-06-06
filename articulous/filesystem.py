"""Filesystem primitives shared across build layers."""
from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


def ensure_parent_dir(path: Path, dry_run: bool = False) -> None:
    parent = path.parent
    if not parent.exists() and not dry_run:
        parent.mkdir(parents=True, exist_ok=True)


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    ensure_parent_dir(path)
    with tempfile.NamedTemporaryFile(
        "w", encoding=encoding, dir=path.parent, delete=False,
    ) as f:
        f.write(text)
        tmp_path = Path(f.name)
    try:
        tmp_path.replace(path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise


def _pid_alive(pid: int) -> bool:
    if pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _lock_payload() -> str:
    data = {"pid": os.getpid(), "created": time.time()}
    return json.dumps(data, sort_keys=True)


def _stale_lock(path: Path, stale_after: float) -> bool:
    try:
        data = json.loads(path.read_text())
        age = time.time() - float(data.get("created", 0))
        return age > stale_after or not _pid_alive(int(data.get("pid", 0)))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return True


def _acquire_lock(path: Path, stale_after: float) -> int:
    ensure_parent_dir(path)
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if not _stale_lock(path, stale_after):
                raise
            path.unlink(missing_ok=True)
            continue
        os.write(fd, _lock_payload().encode("utf-8"))
        return fd


@contextmanager
def lock_file(path: Path, stale_after: float = 3600):
    fd = _acquire_lock(path, stale_after)
    try:
        yield
    finally:
        os.close(fd)
        Path(path).unlink(missing_ok=True)


class TempWorkspace:
    def __init__(self):
        self._paths: list[Path] = []

    def named_file(self, mode: str = "w+", encoding: str = "utf-8", suffix: str = ""):
        encoding_arg = None if "b" in mode else encoding
        f = tempfile.NamedTemporaryFile(
            mode, encoding=encoding_arg, suffix=suffix, delete=False,
        )
        self._paths.append(Path(f.name))
        return f

    def add(self, path: Path) -> Path:
        self._paths.append(path)
        return path

    def cleanup(self) -> None:
        for path in self._paths:
            path.unlink(missing_ok=True)
        self._paths.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.cleanup()
