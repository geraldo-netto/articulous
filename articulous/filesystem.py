"""Filesystem primitives shared across build layers."""
from __future__ import annotations

import fcntl
import json
import logging
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


def _stale_lock_reason(text: str, stale_after: float) -> str:
    if not text:
        return ""
    try:
        data = json.loads(text)
        age = time.time() - float(data.get("created", 0))
        if age > stale_after:
            return "expired"
        if not _pid_alive(int(data.get("pid", 0))):
            return "dead process"
        return ""
    except (OSError, ValueError, TypeError):
        return "malformed"


def _read_lock(fd: int) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    return os.read(fd, 65536).decode("utf-8", errors="replace")


def _write_lock(fd: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, _lock_payload().encode("utf-8"))
    os.fsync(fd)


def _acquire_lock(path: Path, stale_after: float) -> int:
    ensure_parent_dir(path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as e:
        os.close(fd)
        raise FileExistsError(path) from e

    reason = _stale_lock_reason(_read_lock(fd), stale_after)
    if reason:
        logging.warning(f"Recovering {reason} build lock: {path}")
    _write_lock(fd)
    return fd


@contextmanager
def lock_file(path: Path, stale_after: float = 3600):
    fd = _acquire_lock(path, stale_after)
    try:
        yield
    finally:
        try:
            Path(path).unlink(missing_ok=True)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


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
