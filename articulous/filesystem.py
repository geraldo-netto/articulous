"""Filesystem primitives shared across build layers."""
from __future__ import annotations

import errno
import fcntl
import json
import logging
import os
import secrets
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


def ensure_parent_dir(path: Path, dry_run: bool = False) -> None:
    parent = path.parent
    if not parent.exists() and not dry_run:
        parent.mkdir(parents=True, exist_ok=True)


def assert_disjoint_trees(source: Path, output: Path) -> None:
    source = source.resolve()
    output = output.resolve()
    if source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError(f"Source and output trees overlap: {source} <-> {output}")


def cache_lock_path(cache_path: Path) -> Path:
    cache = cache_path.resolve()
    return cache.with_name(f".{cache.name}.articulous.lock")


def _path_limits(path: Path) -> tuple[int, int]:
    parent = path.parent
    while True:
        try:
            return os.pathconf(parent, "PC_NAME_MAX"), os.pathconf(parent, "PC_PATH_MAX")
        except OSError as error:
            if error.errno not in {errno.ENOENT, errno.ENOTDIR, errno.ENAMETOOLONG} or parent == parent.parent:
                raise
            parent = parent.parent


def validate_path_length(path: Path) -> None:
    path = path.absolute()
    name_max, path_max = _path_limits(path)
    if path_max >= 0 and len(os.fsencode(path)) >= path_max:
        raise ValueError(f"Generated output path exceeds filesystem limit ({path_max} bytes): {path}")
    for part in path.parts:
        if name_max >= 0 and len(os.fsencode(part)) > name_max:
            raise ValueError(f"Generated output component exceeds filesystem limit ({name_max} bytes): {part}")


def validate_regular_file(path: Path) -> os.stat_result | None:
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"Path must be a regular file: {path}")
    return metadata


def regular_file_opener(path: str | Path, flags: int) -> int:
    validate_regular_file(Path(path))
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o666)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"Opened path must be a regular file: {path}")
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextmanager
def open_regular_file(path: Path):
    with open(path, "rb", opener=regular_file_opener) as source:
        yield source


def validate_output_path(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"Generated output path contains a symlink: {component}")


@contextmanager
def _generated_staging_file(path: Path, directory_fd: int):
    name = f".articulous-{secrets.token_hex(16)}"
    fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600, dir_fd=directory_fd)
    try:
        yield path.parent / name, fd
    finally:
        os.close(fd)
        try:
            os.unlink(name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


@contextmanager
def _generated_output(path: Path):
    validate_output_path(path)
    ensure_parent_dir(path)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with _generated_staging_file(path, directory_fd) as (staged, fd):
            yield staged
            validate_output_path(path)
            current = path.parent.stat()
            original = os.fstat(directory_fd)
            if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
                raise ValueError(f"Generated output directory changed during rendering: {path.parent}")
            os.fchmod(fd, mode)
            os.replace(staged.name, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    finally:
        os.close(directory_fd)


@contextmanager
def atomic_output(path: Path, *, generated: bool = False):
    if generated:
        with _generated_output(path) as staged:
            yield staged
        return
    ensure_parent_dir(path)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, name = tempfile.mkstemp(dir=path.parent)
    tmp_path = Path(name)
    try:
        os.close(fd)
        yield tmp_path
        tmp_path.chmod(mode)
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    with atomic_output(path) as tmp_path:
        tmp_path.write_text(text, encoding=encoding)


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
        if not isinstance(data, dict):
            return "malformed"
        age = time.time() - float(data.get("created", 0))
        if age > stale_after:
            return "expired"
        if not _pid_alive(int(data.get("pid", 0))):
            return "dead process"
        return ""
    except (OSError, ValueError, TypeError, OverflowError):
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
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError(f"Build lock must be a regular file with one link: {path}")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise FileExistsError(path) from e
        reason = _stale_lock_reason(_read_lock(fd), stale_after)
        if reason:
            logging.warning(f"Recovering {reason} build lock: {path}")
        _write_lock(fd)
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def lock_file(path: Path, stale_after: float = 3600):
    fd = _acquire_lock(path, stale_after)
    try:
        yield
        os.ftruncate(fd, 0)
        os.fsync(fd)
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
