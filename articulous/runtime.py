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
import threading
import time
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable


# ================================================================
# Filesystem helpers
# ================================================================

def _ensure_parent_dir(path: Path, dry_run: bool = False) -> None:
    parent = path.parent
    if not parent.exists() and not dry_run:
        parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data, dry_run: bool = False) -> None:
    if dry_run:
        logging.debug(f"[DRY RUN] Would write JSON: {path}")
        return
    _ensure_parent_dir(path)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ================================================================
# Content-addressed cache
# ================================================================

_cache_lock = threading.Lock()


def file_hash(path: Path) -> str:
    """
    SHA-256 hex digest of ``path``. Raises :class:`FileNotFoundError`
    if the path does not exist.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
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
            return data
    except json.JSONDecodeError as e:
        logging.warning(f"Failed to load cache: {e}")
    logging.debug("Cache invalid — starting fresh")
    return {}


def save_cache(cache_path: Path, cache: dict) -> None:
    """Save the build cache to disk."""
    try:
        cache_path.write_text(json.dumps(cache, indent=2))
        logging.debug("Cache saved successfully")
    except OSError as e:
        logging.error(f"Failed to save cache: {e}")


def should_rebuild(key: str, cache: dict, new_hashes: tuple, force: bool) -> bool:
    """Decide whether a page should be rebuilt."""
    if force:
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


def run_parallel_tasks(tasks, max_workers="auto"):
    """
    Run a list of callables in parallel.

    On failure: cancel any tasks that have not yet started, drain the
    rest, log every error, and re-raise. Raises the original exception
    when only one task failed, or an :class:`ExceptionGroup` if more.
    """
    if max_workers == "auto":
        max_workers = max(4, os.cpu_count() or 4)

    results = []
    errors = []
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {pool.submit(fn): fn for fn in tasks}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except CancelledError:
                # Cancellations are how we react to a failure; the real
                # error is already captured. Don't double-count.
                continue
            except Exception as e:
                logging.error(f"Task failed: {e}")
                errors.append(e)
                for other in futures:
                    if not other.done():
                        other.cancel()
    finally:
        pool.shutdown(wait=True)

    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise ExceptionGroup("parallel task failures", errors)
    return results
