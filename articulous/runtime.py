"""
Build runtime primitives: fingerprint cache, hashing, parallel execution
and per-task timing.

Everything here is independent of the build pipeline — it operates on
paths, dicts, and callables, with no knowledge of articles, models, or
transform engines. This is the layer the pipeline composes on top of.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, CancelledError, ThreadPoolExecutor, wait
from itertools import islice
from pathlib import Path
from typing import Callable, Union

from .filesystem import (
    open_regular_file, validate_output_path, validate_regular_file, write_text_atomic,
)

WorkerCount = Union[int, str]  # int or the sentinel "auto"


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
    with open_regular_file(path) as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_cache(cache_path: Path) -> dict:
    """Load regular cache files; reject special files, recover missing/invalid data."""
    if not cache_path.exists():
        logging.debug("Cache file not found — starting with empty cache")
        return TrackedCache()
    try:
        with open_regular_file(cache_path.resolve()) as source:
            data = json.loads(source.read().decode("utf-8"))
        if isinstance(data, dict):
            logging.debug("Cache loaded successfully")
            return TrackedCache(data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
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
    if output_path is not None and (force or cache.get(key) == list(new_hashes)):
        validate_output_path(output_path)
        validate_regular_file(output_path)
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


def _collect_one(fut, results: list | None, errors: list, futures) -> None:
    try:
        result = fut.result()
        if results is not None:
            results.append(result)
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


def _fill_pending(pool, pending: set, tasks, limit: int) -> None:
    for task in islice(tasks, limit - len(pending)):
        pending.add(pool.submit(task))


def _drain_tasks(pool, pending: set, tasks, limit: int, results, errors) -> None:
    _fill_pending(pool, pending, tasks, limit)
    while pending:
        done, _ = wait(pending, return_when=FIRST_COMPLETED)
        pending.difference_update(done)
        for future in done:
            _collect_one(future, results, errors, pending)
        if not errors:
            _fill_pending(pool, pending, tasks, limit)


def run_parallel_tasks(
    tasks, max_workers: WorkerCount = "auto", *, collect_results: bool = True,
) -> list:
    """
    Consume callables with at most twice the worker count in flight.

    Set ``collect_results=False`` for tasks whose return values are unused.

    ``max_workers`` accepts either a positive ``int`` or the sentinel
    string ``"auto"`` (resolves to ``max(4, os.cpu_count() or 4)``).

    Ordinary task or producer failures cancel pending work and drain
    submitted tasks. Task failures are logged; one error is re-raised
    directly and multiple errors form an :class:`ExceptionGroup`.
    """
    workers: int = (
        max(4, os.cpu_count() or 4) if max_workers == "auto" else int(max_workers)
    )

    results: list = []
    errors: list = []
    pool = ThreadPoolExecutor(max_workers=workers)
    pending: set = set()
    try:
        _drain_tasks(
            pool, pending, iter(tasks), 2 * workers,
            results if collect_results else None, errors,
        )
    except BaseException as error:
        _cancel_pending(pending)
        for future in pending:
            _collect_one(future, results if collect_results else None, errors, pending)
        if isinstance(error, Exception):
            errors.insert(0, error)
            _raise_if_errors(errors)
        raise
    finally:
        pool.shutdown(wait=True)

    _raise_if_errors(errors)
    return results
