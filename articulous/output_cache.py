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


def _expired_roots(roots, active_root, cutoff, activity):
    for root, record in roots.items():
        used = last_used(record)
        if root != active_root and _is_expired(used, cutoff):
            if _is_expired(activity.inactive(root, record), cutoff):
                yield root


def _is_expired(used, cutoff):
    return used is not None and (cutoff is None or used <= cutoff)


def refresh_output_cache(roots, active_root, cache, retention_days, activity):
    now = _now()
    previous = roots.get(active_root)
    used = activity.used(active_root, previous)
    expired = list(_expired_roots(roots, active_root, _cutoff(now, retention_days), activity))
    if cache_changed(cache) or expired:
        cache[LAST_USED_KEY] = max(now, used or 0)
        roots[active_root] = dict(cache)
        for root in expired:
            del roots[root]
            activity.retire(root)
        return True
    if used is not None and now > used:
        activity.touch(active_root, previous, now)
    return False
