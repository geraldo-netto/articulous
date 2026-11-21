"""Small per-root inactivity updates, protected by the selected fingerprint cache lock."""
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re

from .filesystem import atomic_output, open_regular_file, validate_output_path
from .output_cache import CACHE_ROOTS_KEY, last_used
from .publication_paths import retirement_path, transaction_path


_PREFIX = '.articulous-activity-'
_FILE = re.compile(r'\.articulous-activity-(?:retire-s?)?[0-9a-f]{64}')
_PARTITION = re.compile(r'[0-9a-f]{64}\.json')
_PENDING = re.compile(r'\.articulous-activity-retire-([0-9a-f]{64})')
_MAX_BYTES = 512


def activity_path(cache: Path, root: str) -> Path:
    key = sha256(os.fsencode(cache.name) + b'\0' + os.fsencode(root)).hexdigest()
    return cache.with_name(_PREFIX + key)


def retirement_queue(cache):
    token = cache.stem if _PARTITION.fullmatch(cache.name) else 's' + sha256(os.fsencode(cache.name)).hexdigest()
    return cache.with_name('.articulous-activity-retire-' + token)


def partition_with_queue(entry):
    match = _PENDING.fullmatch(entry.name)
    return Path(entry.path).with_name(match[1] + '.json') if match else None


def reserved_activity_path(path: Path, directory: Path) -> bool:
    if not path.is_relative_to(directory):
        return False
    parts = path.relative_to(directory).parts
    return bool(parts and _FILE.fullmatch(parts[0]))


def _read_regular(path, limit=-1):
    validate_output_path(path)
    try:
        with open_regular_file(path) as source:
            if os.fstat(source.fileno()).st_nlink != 1:
                raise ValueError(f'Fingerprint cache activity file has multiple hardlinks: {path}')
            return source.read(limit)
    except FileNotFoundError:
        return None


def _read_stamp(path):
    data = _read_regular(path, _MAX_BYTES + 1)
    if data is None:
        return None
    if len(data) > _MAX_BYTES:
        raise ValueError(f'Oversized cache activity file: {path}')
    value = json.loads(data)
    if not _valid_stamp(value, path.name):
        raise ValueError(f'Invalid cache activity file: {path}')
    return value


def _valid_stamp(value, name):
    return (isinstance(value, list) and len(value) == 4 and value[0] == name
            and isinstance(value[1], str) and type(value[2]) is int
            and type(value[3]) is int and 0 <= value[2] <= value[3])


class CacheActivity:
    def __init__(self, cache: Path, base: Path):
        self.cache = cache
        self.base = base
        self.queue = retirement_queue(cache)
        self._observed: dict[str, list] = {}
        self._retired: dict[str, list] = {}

    def validate(self, root):
        _read_stamp(activity_path(self.base, root))
        if os.path.lexists(self.queue):
            self._queued()

    def used(self, root, record):
        checkpoint = last_used(record)
        if checkpoint is None:
            return None
        stamp = _read_stamp(activity_path(self.base, root))
        if stamp is not None:
            self._observed[root] = stamp
            if stamp[1:3] == [record.get('__generation__'), checkpoint]:
                return stamp[3]
        return checkpoint

    def inactive(self, root, record):
        try:
            return self.used(root, record)
        except (ValueError, OSError, RecursionError) as error:
            logging.warning('Preserving cache with unreadable activity: %s', error)
            return None

    def touch(self, root, record, now):
        path = activity_path(self.base, root)
        value = [path.name, record['__generation__'], last_used(record), now]
        with atomic_output(path, generated=True) as target:
            target.write_text(json.dumps(value), encoding='ascii')

    def retire(self, root):
        if root in self._observed:
            self._retired[root] = self._observed[root]

    def _queued(self):
        data = _read_regular(self.queue)
        if data is None:
            return {}
        pending = json.loads(data)
        if not isinstance(pending, dict) or not pending or not all(
            _valid_stamp(stamp, activity_path(self.base, root).name) for root, stamp in pending.items()
        ):
            raise ValueError(f'Invalid cache activity retirement queue: {self.queue}')
        return pending

    def prepare_retirement(self):
        if self._retired:
            self._write_queue({**self._queued(), **self._retired})

    def _write_queue(self, pending):
        if pending:
            with atomic_output(self.queue, generated=True) as target:
                target.write_text(json.dumps(pending), encoding='ascii')
        else:
            self.queue.unlink(missing_ok=True)

    def _release(self, root, stamp, record, project):
        destination = Path(root)
        if not destination.is_relative_to(project) or '..' in destination.parts:
            raise ValueError(f'Invalid activity retirement root: {root}')
        transaction = transaction_path(destination)
        if os.path.lexists(transaction) or os.path.lexists(retirement_path(transaction)):
            return False
        if isinstance(record, dict) and stamp[1:3] == [record.get('__generation__'), last_used(record)]:
            return True
        path = activity_path(self.base, root)
        if _read_stamp(path) == stamp:
            path.unlink(missing_ok=True)
        return True

    def recover(self, project, roots=None):
        if not os.path.lexists(self.queue):
            return
        pending = self._queued()
        if roots is None:
            data = _read_regular(self.cache)
            envelope = {CACHE_ROOTS_KEY: {}} if data is None else json.loads(data)
            roots = envelope.get(CACHE_ROOTS_KEY) if isinstance(envelope, dict) else None
        if not isinstance(roots, dict):
            raise ValueError('Invalid cache roots during activity retirement')
        remaining = {root: stamp for root, stamp in pending.items()
                     if not self._release(root, stamp, roots.get(root), project)}
        if len(remaining) != len(pending):
            self._write_queue(remaining)
