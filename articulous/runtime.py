"""
Build runtime primitives: content-addressed cache, parallel executor,
filesystem I/O helpers, and per-task timing.

Everything here is independent of the build pipeline — it operates on
paths, dicts, and callables, with no knowledge of articles, models, or
transform engines. This is the layer the pipeline composes on top of.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Union

WorkerCount = Union[int, str]  # int or the sentinel "auto"


# ================================================================
# Filesystem helpers
# ================================================================

def _ensure_parent_dir(path: Path, dry_run: bool = False) -> None:
    parent = path.parent
    if not parent.exists() and not dry_run:
        parent.mkdir(parents=True, exist_ok=True)


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    _ensure_parent_dir(path)
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


def write_json(path: Path, data, dry_run: bool = False) -> None:
    if dry_run:
        logging.debug(f"[DRY RUN] Would write JSON: {path}")
        return
    write_text_atomic(path, json.dumps(data, indent=2))


# ================================================================
# Content-addressed cache
# ================================================================

_cache_lock = threading.Lock()


class TrackedCache(dict):
    def __init__(self, *args, dirty: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.dirty = dirty

    def mark_clean(self) -> None:
        self.dirty = False

    def __setitem__(self, key, value) -> None:
        if self.get(key) != value:
            self.dirty = True
        super().__setitem__(key, value)

    def pop(self, key, default=None):
        if key in self:
            self.dirty = True
        return super().pop(key, default)

    def clear(self) -> None:
        if self:
            self.dirty = True
        super().clear()

    def update(self, *args, **kwargs) -> None:
        for key, value in dict(*args, **kwargs).items():
            self[key] = value


def cache_changed(cache: dict) -> bool:
    return bool(getattr(cache, "dirty", True))


def file_hash(path: Path) -> str:
    """
    SHA-256 hex digest of ``path``. Raises :class:`FileNotFoundError`
    if the path does not exist, or :class:`ValueError` if the path
    points at a directory (programmer error — file_hash is only
    meaningful for regular files).
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except IsADirectoryError as e:
        raise ValueError(
            f"file_hash requires a regular file, got directory: {path}"
        ) from e
    return h.hexdigest()


def load_cache(cache_path: Path) -> dict:
    """Load the build cache from disk; empty dict if missing/invalid."""
    if not cache_path.exists():
        logging.debug("Cache file not found — starting with empty cache")
        return {}
    try:
        data = json.loads(cache_path.read_text())
        if isinstance(data, dict):
            logging.debug("Cache loaded successfully")
            return TrackedCache(data)
    except json.JSONDecodeError as e:
        logging.warning(f"Failed to load cache: {e}")
    logging.debug("Cache invalid — starting fresh")
    return TrackedCache()


def save_cache(cache_path: Path, cache: dict) -> None:
    """
    Save the build cache to disk. Logs and swallows both I/O errors
    (``OSError``) and serialisation errors (``TypeError`` when a cache
    value sneaks in that ``json.dumps`` can't handle); a broken cache
    write should never crash the build.
    """
    try:
        write_text_atomic(cache_path, json.dumps(cache, indent=2))
        if isinstance(cache, TrackedCache):
            cache.mark_clean()
        logging.debug("Cache saved successfully")
    except (OSError, TypeError):
        logging.exception("Failed to save cache")


def should_rebuild(
    key: str,
    cache: dict,
    new_hashes: tuple,
    force: bool,
    output_path: Path | None = None,
) -> bool:
    """Decide whether a page should be rebuilt."""
    if force:
        return True
    if output_path is not None and not output_path.exists():
        return True
    old = cache.get(key)
    if not old:
        return True
    return old != list(new_hashes)


def update_cache(cache: dict, key: str, new_hashes: tuple) -> None:
    """Thread-safe cache write. Workers commit their own entries on success."""
    with _cache_lock:
        cache[key] = list(new_hashes)


@contextmanager
def lock_file(path: Path):
    _ensure_parent_dir(path)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(fd)
        Path(path).unlink(missing_ok=True)


# ================================================================
# Parallel executor + per-task timing
# ================================================================

def timed(label: str, fn: Callable) -> Callable:
    """Wrap ``fn`` so every invocation logs its wall-clock duration at DEBUG."""
    def wrapped():
        t0 = time.perf_counter()
        try:
            return fn()
        finally:
            logging.debug(f"task {label} took {time.perf_counter() - t0:.3f}s")
    return wrapped


def _cancel_pending(futures) -> None:
    for other in futures:
        if not other.done():
            other.cancel()


def _collect_one(fut, results: list, errors: list, futures) -> None:
    try:
        results.append(fut.result())
    except CancelledError:
        # Cancellations are how we react to a failure; the real
        # error is already captured. Don't double-count.
        return
    except Exception as e:
        logging.exception("Task failed")
        errors.append(e)
        _cancel_pending(futures)


def _raise_if_errors(errors: list) -> None:
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise ExceptionGroup("parallel task failures", errors)


def run_parallel_tasks(tasks, max_workers: WorkerCount = "auto") -> list:
    """
    Run a list of callables in parallel.

    ``max_workers`` accepts either a positive ``int`` or the sentinel
    string ``"auto"`` (resolves to ``max(4, cpu_count())``).

    On failure: cancel any tasks that have not yet started, drain the
    rest, log every error, and re-raise. Raises the original exception
    when only one task failed, or an :class:`ExceptionGroup` if more.
    """
    workers: int = (
        max(4, os.cpu_count() or 4) if max_workers == "auto" else int(max_workers)
    )

    results: list = []
    errors: list = []
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {pool.submit(fn): fn for fn in tasks}
        for fut in as_completed(futures):
            _collect_one(fut, results, errors, futures)
    finally:
        pool.shutdown(wait=True)

    _raise_if_errors(errors)
    return results
