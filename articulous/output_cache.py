"""Retention of per-output fingerprints in the existing locked cache."""
import time

from .runtime import cache_changed


CACHE_ROOTS_KEY = "__output_roots__"
LAST_USED_KEY = "__last_used__"
_SECONDS_PER_DAY = 86_400


def output_cache_roots(stored: dict) -> dict:
    roots = stored.get(CACHE_ROOTS_KEY)
    return roots if isinstance(roots, dict) else {}


def last_used(record: object) -> int | None:
    value = record.get(LAST_USED_KEY) if isinstance(record, dict) else None
    return value if type(value) is int and value >= 0 else None


def _now() -> int:
    return time.time_ns() // 1_000_000_000


def _cutoff(now: int, retention_days: int) -> int | None:
    return now - retention_days * _SECONDS_PER_DAY if retention_days else None


def cutoff_for(retention_days: int) -> int | None:
    return _cutoff(_now(), retention_days)


def _expired_roots(roots: dict, active_root: str, cutoff: int | None):
    for root, record in roots.items():
        if root != active_root:
            used = last_used(record)
            if used is not None and (cutoff is None or used <= cutoff):
                yield root


def refresh_output_cache(roots: dict, active_root: str, cache: dict, retention_days: int) -> bool:
    now = _now()
    cache[LAST_USED_KEY] = max(now, last_used(roots.get(active_root)) or 0)
    cutoff = _cutoff(now, retention_days)
    expired = list(_expired_roots(roots, active_root, cutoff))
    for root in expired:
        del roots[root]
    changed = cache_changed(cache)
    if changed:
        roots[active_root] = dict(cache)
    return changed or bool(expired)
