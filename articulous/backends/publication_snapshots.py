"""Private, verified publication rollback data."""
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
import re

from ..filesystem import atomic_output, open_regular_file, validate_output_path, write_text_atomic
from ..output_cache import CACHE_ROOTS_KEY, output_cache_roots


def _transfer(source, target=None):
    digest = hashlib.sha256()
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
        if target is not None:
            target.write(chunk)
    return digest.hexdigest()


def _single_link(source):
    status = os.fstat(source.fileno())
    if status.st_nlink != 1:
        raise ValueError('Publication state must have one hardlink')
    return status.st_dev, status.st_ino


def snapshot(path, target):
    validate_output_path(path)
    with ExitStack() as owner:
        try:
            source = owner.enter_context(open_regular_file(path))
        except FileNotFoundError:
            return None
        _single_link(source)
        with target.open('xb') as out:
            digest = _transfer(source, out)
            return [*_single_link(out), digest]


def require_digest(digest):
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('Invalid publication digest')


def validate_claim(claim):
    if claim is None:
        return
    if not isinstance(claim, list) or len(claim) != 3:
        raise ValueError('Invalid publication snapshot claim')
    if any(type(field) is not int or field < 0 for field in claim[:2]):
        raise ValueError('Invalid publication snapshot identity')
    require_digest(claim[2])


@contextmanager
def _snapshot_source(path, claim):
    with open_regular_file(path) as source:
        if list(_single_link(source)) != claim[:2]:
            raise ValueError('Publication snapshot identity changed')
        yield source


def verify_snapshot(path, claim):
    if claim is None:
        return
    with _snapshot_source(path, claim) as source:
        if _transfer(source) != claim[2]:
            raise ValueError('Publication snapshot bytes changed')


def restore_snapshot(path, saved, claim):
    validate_output_path(path)
    if claim is None:
        path.unlink(missing_ok=True)
        return
    with _snapshot_source(saved, claim) as source, atomic_output(path, generated=True) as staged:
        with staged.open('wb') as target:
            if _transfer(source, target) != claim[2]:
                raise ValueError('Publication snapshot bytes changed')


def install_state(path, state):
    with open_regular_file(state.path) as source, atomic_output(path) as target:
        with target.open('wb') as output:
            if _transfer(source, output) != state.digest:
                raise ValueError('Staged publication state changed')


def _current_digest(path):
    try:
        with open_regular_file(path) as source:
            _single_link(source)
            return _transfer(source)
    except FileNotFoundError:
        return None


def _root_entries(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid shared cache during publication recovery')
    return output_cache_roots(data)


def _read_roots(path):
    with open_regular_file(path) as source:
        _single_link(source)
        return _root_entries(json.load(source))


def _saved_roots(path, claim):
    if claim is None:
        return {}
    with _snapshot_source(path, claim) as source:
        data = source.read()
    if hashlib.sha256(data).hexdigest() != claim[2]:
        raise ValueError('Publication snapshot bytes changed')
    return _root_entries(json.loads(data))


def _restore_active_cache(path, saved, claim, active):
    current = _read_roots(path)
    previous = _saved_roots(saved, claim)
    if active in previous:
        if active in current and current[active] == previous[active]:
            return
        current[active] = previous[active]
    elif active in current:
        del current[active]
    else:
        return
    write_text_atomic(path, json.dumps({CACHE_ROOTS_KEY: current}, indent=2))


def restore_cache(path, backup, claim, installed_digest, active):
    prior = claim[2] if claim is not None else None
    current = _current_digest(path)
    if current is None or current in (prior, installed_digest):
        restore_snapshot(path, backup, claim)
    else:
        _restore_active_cache(path, backup, claim, active)
