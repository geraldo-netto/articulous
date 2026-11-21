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
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Union

from .backends.cpu_capacity import available_cpus
from .filesystem import (
    open_regular_file, validate_output_path, validate_regular_file, write_text_atomic,
)

WorkerCount = Union[int, str]  # int or the sentinel "auto"


# ================================================================
# Content-addressed cache
# ================================================================

_cache_lock = threading.Lock()


class TrackedCache(dict):
    def __init__(self, entries=()):
        super().__init__(entries)
        self.dirty = False

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
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def load_cache(cache_path: Path) -> dict:
    """Load regular cache files; reject special files, recover missing/invalid data."""
    if not cache_path.exists():
        logging.debug("Cache file not found — starting with empty cache")
        return TrackedCache()
    try:
        with open_regular_file(cache_path.resolve()) as source:
            payload = source.read()
        try:
            data = json.loads(payload.decode("utf-8"))
        except (ValueError, RecursionError) as error:
            logging.warning("Failed to load cache: %s", error)
            return TrackedCache()
        if isinstance(data, dict):
            logging.debug("Cache loaded successfully")
            return TrackedCache(data)
    except OSError as e:
        logging.warning(f"Failed to load cache: {e}")
    logging.debug("Cache invalid — starting fresh")
    return TrackedCache()


def save_cache(cache_path: Path, cache: dict) -> bool:
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
        return True
    except (OSError, TypeError):
        logging.exception("Failed to save cache")
        return False


def should_rebuild(
    key: str,
    cache: dict,
    new_hashes: tuple,
    force: bool,
    output_path: Path | None = None,
) -> bool:
    """Decide whether a page should be rebuilt."""
    if output_path is not None:
        validate_output_path(output_path)
    return _admitted_rebuild(key, cache, new_hashes, force, output_path)


def _admitted_rebuild(key, cache, new_hashes, force, output_path):
    if output_path is not None and validate_regular_file(output_path) is None:
        return True
    old = cache.get(key)
    return force or not old or old != list(new_hashes)


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
    if fut.cancelled():
        return
    try:
        result = fut.result()
        if results is not None:
            results.append(result)
    except Exception as e:
        logging.exception("Task failed")
        errors.append(e)
        _cancel_pending(futures)


def _raise_if_errors(errors: list) -> None:
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise ExceptionGroup("parallel task failures", errors)


@dataclass(frozen=True)
class WeightedTask:
    charge: int
    run: Callable

    def __post_init__(self):
        if type(self.charge) is not int or self.charge < 0:
            raise ValueError("Task input charge must be a nonnegative integer")

    def __call__(self):
        return self.run()


_EXHAUSTED = object()


class _TaskAdmission:
    def __init__(self, tasks, limit, budget):
        if budget is not None and (type(budget) is not int or budget < 1):
            raise ValueError("In-flight input budget must be a positive integer")
        self.tasks = tasks
        self.limit = limit
        self.budget = budget
        self.pending = {}
        self.cost = 0
        self.deferred = _EXHAUSTED

    def _next(self):
        task = self.deferred
        if task is _EXHAUSTED:
            return next(self.tasks, _EXHAUSTED)
        self.deferred = _EXHAUSTED
        return task

    def _fits(self, charge):
        return not self.pending or self.budget is None or self.cost + charge <= self.budget

    def fill(self, pool):
        for _ in range(min(self.limit - len(self.pending), sys.maxsize)):
            task = self._next()
            if task is _EXHAUSTED:
                return
            charge = task.charge if isinstance(task, WeightedTask) else 0
            if not self._fits(charge):
                self.deferred = task
                return
            self.pending[pool.submit(task)] = charge
            self.cost += charge

    def settle(self, done):
        for future in done:
            self.cost -= self.pending.pop(future)


def _drain_tasks(pool, admission, results, errors) -> None:
    admission.tasks = iter(admission.tasks)
    admission.fill(pool)
    while admission.pending:
        done, _ = wait(admission.pending, return_when=FIRST_COMPLETED)
        admission.settle(done)
        for future in done:
            _collect_one(future, results, errors, admission.pending)
        if not errors:
            admission.fill(pool)


def _worker_count(value: WorkerCount) -> int:
    if value == "auto":
        return min(2, available_cpus())
    if type(value) is not int or value < 1:
        raise ValueError("max_workers must be a positive integer or auto")
    return value


def run_parallel_tasks(
    tasks, max_workers: WorkerCount = "auto", *, collect_results: bool = True,
    max_inflight_bytes: int | None = None,
) -> list:
    """
    Consume callables with at most twice the worker count in flight.

    Set ``collect_results=False`` for tasks whose return values are unused.
    A positive byte budget limits admitted weighted tasks. A task larger than
    the budget is admitted by itself.

    ``max_workers`` accepts either a positive ``int`` or the sentinel
    string ``"auto"`` (up to two workers within the effective CPU limit).

    Ordinary task or producer failures cancel pending work and drain
    submitted tasks. Task failures are logged; one error is re-raised
    directly and multiple errors form an :class:`ExceptionGroup`.
    """
    workers = _worker_count(max_workers)

    results: list = []
    errors: list = []
    admission = _TaskAdmission(tasks, 2 * workers, max_inflight_bytes)
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        _drain_tasks(
            pool, admission, results if collect_results else None, errors,
        )
    except BaseException as error:
        _cancel_pending(admission.pending)
        for future in admission.pending:
            _collect_one(future, results if collect_results else None, errors, admission.pending)
        if isinstance(error, Exception):
            errors.insert(0, error)
            _raise_if_errors(errors)
        raise
    finally:
        pool.shutdown(wait=True)

    _raise_if_errors(errors)
    return results
