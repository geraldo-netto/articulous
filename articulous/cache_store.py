"""Filesystem adapter for shared and partitioned fingerprint cache storage."""
from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re

from .cache_usage_index import file_generation, read_usage_index, reusable_usage, save_usage_index
from .filesystem import (
    cache_lock_path, lock_file, open_regular_file, private_directory,
    validate_output_path, validate_regular_file, write_text_atomic,
)
from .output_cache import CACHE_ROOTS_KEY, LAST_USED_KEY, cutoff_for, last_used, output_cache_roots
from .publication_paths import transaction_path
from .runtime import load_cache

_LAYOUT_MARKER = 'layout-v1'
_ROOT_FILE = re.compile(r'[0-9a-f]{64}\.json')
# The serialized root can contain escaped bytes from a filesystem path.
_ROOT_LINE_LIMIT = 65536


@dataclass(frozen=True)
class CacheSelection:
    base: Path
    path: Path

    @property
    def partitioned(self):
        return self.base != self.path


def cache_namespace(base: Path) -> Path:
    return base.with_name(f'{base.name}.articulous-roots')


def _root_path(namespace: Path, root: str) -> Path:
    return namespace / (hashlib.sha256(os.fsencode(root)).hexdigest() + '.json')


def partition_path(base: Path, destination: Path) -> Path:
    return _root_path(cache_namespace(base), str(destination.resolve()))


def select_cache(base: Path, destination: Path) -> CacheSelection:
    namespace = cache_namespace(base)
    if not os.path.lexists(namespace):
        return CacheSelection(base, base)
    validate_output_path(namespace)
    marker = namespace / _LAYOUT_MARKER
    validate_output_path(marker)
    if not marker.is_file():
        raise ValueError(f'Unrecognized fingerprint cache directory: {namespace}')
    active = partition_path(base, destination)
    validate_output_path(active)
    state = validate_regular_file(active)
    if state is not None and state.st_nlink != 1:
        raise ValueError(f'Fingerprint cache file has multiple hardlinks: {active}')
    return CacheSelection(base, active)


@contextmanager
def lock_selected_cache(base: Path, destination: Path,
                        locked: Callable[[Path], AbstractContextManager]):
    while True:
        selected = select_cache(base, destination)
        with locked(selected.path):
            # Activation publishes the directory while holding the old cache lock.
            if selected.partitioned or not os.path.lexists(cache_namespace(base)):
                yield selected
                return


def partitioned_payload(roots: dict) -> dict:
    records = {}
    for root, record in roots.items():
        timestamp = last_used(record)
        records[root] = record if timestamp is None else {LAST_USED_KEY: timestamp, **record}
    return {CACHE_ROOTS_KEY: records}


def cache_payload(selected: CacheSelection, roots: dict) -> dict:
    return partitioned_payload(roots) if selected.partitioned else {CACHE_ROOTS_KEY: roots}


def selected_roots(stored: dict, root: str, partitioned: bool) -> dict:
    roots = output_cache_roots(stored)
    if partitioned:
        return {root: roots[root]} if root in roots else {}
    return roots


def _pending_journal(path: Path, base: Path) -> bool:
    validate_output_path(path)
    try:
        with open_regular_file(path / 'journal.json') as source:
            data = json.load(source)
    except (OSError, ValueError, RecursionError):
        return True
    owner = data.get('cache') if isinstance(data, dict) else None
    return not isinstance(owner, str) or not Path(owner).is_absolute() or owner == str(base)


def _has_pending_journal(base: Path) -> bool:
    def failed(error):
        raise error

    for folder, dirs, _ in os.walk(base.parent, onerror=failed):
        for name in tuple(dirs):
            if name.startswith('.') and name.endswith(('.articulous-transaction', '.articulous-transaction-retired')):
                dirs.remove(name)
                if _pending_journal(Path(folder) / name, base):
                    return True
    return False


def _admitted_root(root: str, project: Path) -> bool:
    path = Path(root)
    try:
        return path.is_absolute() and path.is_relative_to(project) and path.resolve() == path
    except (OSError, ValueError):
        return False


def _migration_records(base, destination):
    stored = load_cache(base)
    if CACHE_ROOTS_KEY not in stored:
        return {str(destination): stored} if stored else {}
    return {
        root: record for root, record in output_cache_roots(stored).items()
        if isinstance(record, dict) and _admitted_root(root, base.parent)
    }


def _activate_namespace(base: Path, destination: Path) -> None:
    if _has_pending_journal(base):
        logging.warning('Fingerprint cache partitioning pending recovery of publication journals in %s', base.parent)
        return
    with private_directory(base.parent) as staging:
        for root, record in _migration_records(base, destination).items():
            target = _root_path(staging, root)
            write_text_atomic(target, json.dumps(partitioned_payload({root: record}), indent=2))
        (staging / _LAYOUT_MARKER).touch(exist_ok=False)
        staging.rename(cache_namespace(base))
    write_text_atomic(base, json.dumps({CACHE_ROOTS_KEY: {}}))


def _read_usage(path: Path):
    with open_regular_file(path) as source:
        metadata = os.fstat(source.fileno())
        if metadata.st_nlink != 1:
            raise ValueError('Fingerprint cache file has multiple hardlinks')
        generation = file_generation(metadata)
        source.readline(4)
        source.readline(64)
        root_line = source.readline(_ROOT_LINE_LIMIT).strip()
        usage_line = source.readline(128).strip().rstrip(b',')
        if generation != file_generation(os.fstat(source.fileno())):
            raise ValueError('Fingerprint cache file changed during usage read')
    root = json.loads(root_line.removesuffix(b': {'))
    if not _usage_root_matches(root, path):
        raise ValueError('Fingerprint cache root does not match its file')
    if not usage_line.startswith(b'"' + LAST_USED_KEY.encode() + b'":'):
        return root, None, generation
    return root, last_used(json.loads(b'{' + usage_line + b'}')), generation


def _usage_root_matches(root, path):
    return (isinstance(root, str) and _admitted_root(root, path.parent.parent)
            and _root_path(path.parent, root) == path)


def _dated_usage(path):
    try:
        return _read_usage(path)
    except (OSError, ValueError):
        return None


def _is_expired(used, cutoff):
    return used is not None and (cutoff is None or used <= cutoff)


def _prune_root(path, cutoff):
    try:
        with lock_file(cache_lock_path(path)):
            usage = _dated_usage(path)
            if _eligible_for_pruning(usage, cutoff):
                path.unlink()
                return True
    except FileExistsError:
        pass
    return False


def _eligible_for_pruning(usage, cutoff):
    if usage is None:
        return False
    root, used, _ = usage
    return _is_expired(used, cutoff) and not os.path.lexists(transaction_path(Path(root)))


def _partition_usage(candidate, cutoff, cached):
    hint = reusable_usage(candidate, cached)
    if hint is None:
        usage = _dated_usage(Path(candidate.path))
        if usage is None:
            return None
        _, used, generation = usage
        hint = [*generation, used]
    if _is_expired(hint[-1], cutoff) and _prune_root(Path(candidate.path), cutoff):
        return None
    return hint


def _partition_entries(active, current, cutoff):
    with os.scandir(active.parent) as directory:
        for candidate in directory:
            name = candidate.name
            if name == active.name:
                yield name, current.get(name)
            elif _ROOT_FILE.fullmatch(name) and candidate.is_file(follow_symlinks=False):
                yield name, _partition_usage(candidate, cutoff, current.get(name))


def _expire_partitions(active: Path, retention_days: int) -> None:
    cutoff = cutoff_for(retention_days)
    index = active.parent / 'expiry-v1'
    current = read_usage_index(index)
    save_usage_index(index, current, _partition_entries(active, current, cutoff))


def finish_cache_update(selected: CacheSelection, destination: Path, retention_days: int,
                        partition: bool) -> None:
    try:
        if selected.partitioned:
            _expire_partitions(selected.path, retention_days)
        elif partition:
            _activate_namespace(selected.base, destination)
    except (OSError, ValueError) as error:
        logging.warning('Fingerprint cache maintenance failed: %s', error)
