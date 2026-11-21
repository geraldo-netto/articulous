"""Rebuildable cache-usage observations keyed by file generation."""
from hashlib import sha256
from itertools import islice
import json
import os

from .filesystem import atomic_output, file_generation, open_regular_file, validate_output_path

_MAX_ENTRIES = 65_536
_MAX_FILE_BYTES = 16 * 1024 * 1024


def _timestamp_is_valid(timestamp):
    return timestamp is None or type(timestamp) is int and timestamp >= 0


def reusable_usage(entry, stored):
    if not isinstance(stored, list) or len(stored) != 6 or not _timestamp_is_valid(stored[-1]):
        return None
    try:
        metadata = entry.stat(follow_symlinks=False)
    except OSError:
        return None
    if metadata.st_nlink == 1 and stored[:5] == file_generation(metadata):
        return stored
    return None


def _load_index(path):
    validate_output_path(path)
    with open_regular_file(path) as source:
        metadata = os.fstat(source.fileno())
        if metadata.st_nlink != 1 or metadata.st_size > _MAX_FILE_BYTES:
            return {}
        data = source.read(metadata.st_size + 1)
    return _decode_index(data) if len(data) == metadata.st_size else {}


def _decode_index(data):
    digest, _, payload = data.partition(b'\n')
    if digest != sha256(payload).hexdigest().encode():
        return {}
    return json.loads(payload)


def read_usage_index(path):
    try:
        data = _load_index(path)
        return data if isinstance(data, dict) and len(data) <= _MAX_ENTRIES else {}
    except (OSError, RecursionError, ValueError):
        return {}


def _write_index(path, entries):
    payload = json.dumps(entries, separators=(',', ':')).encode()
    message = sha256(payload).hexdigest().encode() + b'\n' + payload
    if len(message) > _MAX_FILE_BYTES:
        return
    with atomic_output(path, generated=True) as target:
        target.write_bytes(message)


def save_usage_index(path, previous, candidates):
    entries = ((key, hint) for key, hint in candidates if hint is not None)
    observed = dict(islice(entries, _MAX_ENTRIES))
    # Every candidate still needs retention processing when the advisory index is full.
    for _ in entries:
        pass
    if observed != previous:
        try:
            _write_index(path, observed)
        except (OSError, RecursionError, ValueError):
            pass
