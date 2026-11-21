"""Write JSON object members incrementally into a private publication file."""
from collections.abc import Generator
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from .publication_contracts import StagedStateFile


@dataclass(frozen=True)
class ObjectMembers:
    entries: Generator


def _object_chunks(entries, level, sorted_keys):
    pad = '  ' * level
    separator = '{'
    for key, value in entries:
        if not isinstance(key, str):
            raise TypeError('Publication JSON object keys must be strings')
        yield separator + '\n' + pad + '  ' + json.dumps(key) + ': '
        yield from _chunks(value, level + 1, sorted_keys)
        separator = ','
    yield '{}' if separator == '{' else '\n' + pad + '}'


def _chunks(value, level, sorted_keys):
    if isinstance(value, ObjectMembers):
        with closing(value.entries) as entries:
            yield from _object_chunks(entries, level, sorted_keys)
    elif isinstance(value, dict):
        entries = sorted(value.items()) if sorted_keys else value.items()
        yield from _object_chunks(entries, level, sorted_keys)
    elif isinstance(value, (list, tuple)):
        padding = '\n' + '  ' * level
        for chunk in json.JSONEncoder(indent=2, sort_keys=sorted_keys).iterencode(value):
            yield chunk.replace('\n', padding)
    else:
        yield json.dumps(value)


def stage_json(path: Path, data, *, sorted_keys=False):
    digest = sha256()
    with path.open('xb') as output, closing(_chunks(data, 0, sorted_keys)) as chunks:
        for chunk in chunks:
            encoded = chunk.encode('utf-8')
            output.write(encoded)
            digest.update(encoded)
    return StagedStateFile(path, digest.hexdigest())
