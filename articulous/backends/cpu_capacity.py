"""CPU availability as observed by this process."""
import os
from pathlib import Path
import sys


_CGROUP_ROOT = Path('/sys/fs/cgroup')
_CGROUP_MEMBERSHIP = Path('/proc/self/cgroup')


def _affinity_count() -> int | None:
    try:
        return len(os.sched_getaffinity(0)) or None
    except OSError:
        return None


def _bandwidth(path: Path) -> int | None:
    try:
        quota, period = path.read_text().split()
        if quota == 'max':
            return None
        quota, period = int(quota), int(period)
    except (OSError, ValueError):
        return None
    if quota <= 0 or period <= 0:
        return None
    return (quota + period - 1) // period


def _cgroup_path(membership: Path) -> Path | None:
    try:
        lines = membership.read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith('0::/'):
            path = Path(line[4:])
            if not path.is_absolute() and '..' not in path.parts:
                return path
    return None


def _cgroup_count(root: Path, membership: Path) -> int | None:
    path = _cgroup_path(membership)
    if path is None:
        return None
    groups = (path, *path.parents)
    limits = (_bandwidth(root / group / 'cpu.max') for group in groups)
    return min((limit for limit in limits if limit is not None), default=None)


def available_cpus() -> int:
    host = os.cpu_count() or 4
    if sys.platform != 'linux':
        return host
    affinity = _affinity_count()
    bandwidth = _cgroup_count(_CGROUP_ROOT, _CGROUP_MEMBERSHIP)
    return min(host, affinity or host, bandwidth or host)
