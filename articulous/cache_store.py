"""Filesystem adapter for shared and partitioned fingerprint cache storage."""
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack, contextmanager, nullcontext
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re

from .cache_activity import CacheActivity, activity_path, partition_with_queue, retirement_queue
from .cache_usage_index import file_generation, read_usage_index, reusable_usage, save_usage_index
from .filesystem import (
    cache_lock_path, lock_file, open_regular_file, partition_directory_lock, private_directory,
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
    project: Path | None = None

    @property
    def partitioned(self):
        return self.base != self.path


def cache_namespace(base: Path) -> Path:
    return base.with_name(f'{base.name}.articulous-roots')


def _root_path(namespace: Path, root: str) -> Path:
    return namespace / (hashlib.sha256(os.fsencode(root)).hexdigest() + '.json')


def partition_path(base: Path, destination: Path) -> Path:
    return _root_path(cache_namespace(base), str(destination.resolve()))


def select_cache(base: Path, destination: Path, project: Path | None = None) -> CacheSelection:
    project = project or base.parent.resolve()
    base = base.resolve()
    namespace = cache_namespace(base)
    if not os.path.lexists(namespace):
        CacheActivity(base, base).validate(str(destination.resolve()))
        return CacheSelection(base, base, project)
    validate_output_path(namespace)
    marker = namespace / _LAYOUT_MARKER
    validate_output_path(marker)
    if not marker.is_file():
        raise ValueError(f'Unrecognized fingerprint cache directory: {namespace}')
    active = partition_path(base, destination)
    CacheActivity(active, base).validate(str(destination.resolve()))
    validate_output_path(active)
    state = validate_regular_file(active)
    if state is not None and state.st_nlink != 1:
        raise ValueError(f'Fingerprint cache file has multiple hardlinks: {active}')
    return CacheSelection(base, active, project)


@contextmanager
def lock_selected_cache(base: Path, destination: Path,
                        locked: Callable[[Path], AbstractContextManager], *, project=None):
    while True:
        selected = select_cache(base, destination, project)
        with ExitStack() as owners:
            admission = partition_directory_lock(selected.path.parent) if selected.partitioned else nullcontext()
            with admission:
                owners.enter_context(locked(selected.path))
            # Activation publishes the directory while holding the old cache lock.
            if selected.partitioned or not os.path.lexists(cache_namespace(selected.base)):
                yield selected
                return


def partitioned_payload(roots: dict) -> dict:
    records = {}
    for root, record in roots.items():
        if last_used(record) is None:
            records[root] = record
        else:
            header = {key: record[key] for key in (LAST_USED_KEY, '__generation__') if key in record}
            records[root] = {**header, **record}
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


def _has_pending_journal(base: Path, project: Path) -> bool:
    def failed(error):
        raise error

    for folder, dirs, _ in os.walk(project, onerror=failed):
        for name in tuple(dirs):
            if name.startswith('.') and name.endswith(('.articulous-transaction', '.articulous-transaction-retired')):
                dirs.remove(name)
                if _pending_journal(Path(folder) / name, base):
                    return True
    return False


def _admitted_root(root: str, project: Path) -> bool:
    path = Path(root)
    if not path.is_absolute() or not path.is_relative_to(project) or ".." in path.parts or "\0" in root:
        return False
    try:
        validate_output_path(path)
    except (OSError, ValueError):
        return False
    return True


def _migration_records(base, project):
    stored = load_cache(base)
    return {
        root: record for root, record in output_cache_roots(stored).items()
        if isinstance(record, dict) and _admitted_root(root, project)
    }


def _activate_namespace(base: Path, project: Path) -> None:
    if _has_pending_journal(base, project):
        logging.warning('Fingerprint cache partitioning pending recovery of publication journals in %s', project)
        return
    with private_directory(base.parent) as staging:
        for root, record in _migration_records(base, project).items():
            target = _root_path(staging, root)
            write_text_atomic(target, json.dumps(partitioned_payload({root: record}), indent=2))
        (staging / _LAYOUT_MARKER).touch(exist_ok=False)
        staging.rename(cache_namespace(base))
    write_text_atomic(base, json.dumps({CACHE_ROOTS_KEY: {}}))


def _read_usage(path: Path, project):
    with open_regular_file(path) as source:
        metadata = os.fstat(source.fileno())
        if metadata.st_nlink != 1:
            raise ValueError('Fingerprint cache file has multiple hardlinks')
        generation = file_generation(metadata)
        source.readline(4)
        source.readline(64)
        root_line = source.readline(_ROOT_LINE_LIMIT).strip()
        usage_line = source.readline(128).strip().rstrip(b',')
        generation_line = source.readline(128).strip().rstrip(b',')
        if generation != file_generation(os.fstat(source.fileno())):
            raise ValueError('Fingerprint cache file changed during usage read')
    root = json.loads(root_line.removesuffix(b': {'))
    if not _usage_root_matches(root, path, project):
        raise ValueError('Fingerprint cache root does not match its file')
    if not usage_line.startswith(b'"' + LAST_USED_KEY.encode() + b'":'):
        return root, None, generation, None
    token = None
    if generation_line.startswith(b'"__generation__":'):
        token = json.loads(b'{' + generation_line + b'}')['__generation__']
    return root, last_used(json.loads(b'{' + usage_line + b'}')), generation, token


def _usage_root_matches(root, path, project):
    return (isinstance(root, str) and _admitted_root(root, project)
            and _root_path(path.parent, root) == path)


def _dated_usage(path, project):
    try:
        return _read_usage(path, project)
    except (OSError, ValueError, RecursionError):
        return None


def _is_expired(used, cutoff):
    return used is not None and (cutoff is None or used <= cutoff)


def _prune_root(path, cutoff, project, base):
    try:
        with partition_directory_lock(path.parent, pruning=True), lock_file(cache_lock_path(path)):
            activity = CacheActivity(path, base)
            usage = _locked_usage(path, project, activity)
            if usage is not None and _eligible_for_pruning(usage, cutoff):
                activity.retire(usage[0])
                activity.prepare_retirement()
                path.unlink()
                activity.recover(project, {})
                return True
    except FileExistsError:
        pass
    return False


def _locked_usage(path, project, activity):
    usage = _dated_usage(path, project)
    if usage is None:
        return None
    root, used, generation, token = usage
    if not os.path.lexists(activity_path(activity.base, root)):
        return usage
    record = {LAST_USED_KEY: used, '__generation__': token}
    if token is None:
        record = output_cache_roots(load_cache(path)).get(root)
    return root, activity.inactive(root, record), generation, token


def _eligible_for_pruning(usage, cutoff):
    root, used, _, _ = usage
    return _is_expired(used, cutoff) and not os.path.lexists(transaction_path(Path(root)))


def _partition_usage(candidate, cutoff, cached, project, base):
    hint = reusable_usage(candidate, cached)
    if hint is None:
        usage = _dated_usage(Path(candidate.path), project)
        if usage is None:
            return None
        _, used, generation, _ = usage
        hint = [*generation, used]
    if _is_expired(hint[-1], cutoff) and _prune_root(Path(candidate.path), cutoff, project, base):
        return None
    return hint


def _recover_partition_queue(path, project, base):
    try:
        with partition_directory_lock(path.parent, pruning=True), lock_file(cache_lock_path(path)):
            CacheActivity(path, base).recover(project)
    except FileExistsError:
        pass


def _partition_entries(active, current, cutoff, project, base):
    with os.scandir(active.parent) as directory:
        for candidate in directory:
            name = candidate.name
            if name == active.name:
                yield name, current.get(name)
            elif _ROOT_FILE.fullmatch(name) and candidate.is_file(follow_symlinks=False):
                yield name, _partition_usage(candidate, cutoff, current.get(name), project, base)
            elif (path := partition_with_queue(candidate)) is not None and path != active:
                _recover_partition_queue(path, project, base)


def _expire_partitions(active: Path, retention_days: int, project: Path, base: Path) -> None:
    cutoff = cutoff_for(retention_days)
    index = active.parent / 'expiry-v1'
    current = read_usage_index(index)
    save_usage_index(index, current, _partition_entries(active, current, cutoff, project, base))


def _recover_shared_activity(selected, project, roots):
    if os.path.lexists(retirement_queue(selected.path)) and not _has_pending_journal(selected.path, project):
        CacheActivity(selected.path, selected.base).recover(project, roots)


def finish_cache_update(selected: CacheSelection, retention_days: int, partition: bool, *, roots=None) -> None:
    project = selected.project or selected.base.parent
    try:
        if selected.partitioned:
            CacheActivity(selected.path, selected.base).recover(project, roots)
            _expire_partitions(selected.path, retention_days, project, selected.base)
        else:
            _recover_shared_activity(selected, project, roots)
            if partition:
                _activate_namespace(selected.base, project)
    except (OSError, ValueError, RecursionError) as error:
        logging.warning('Fingerprint cache maintenance failed: %s', error)
