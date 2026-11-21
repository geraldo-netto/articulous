"""Linux-validated directory publication with rollback and a recovery journal."""
import base64
import hashlib
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import shutil

from ..cache_store import partition_path
from ..filesystem import (
    _directory_handle, atomic_output, cache_lock_path, lock_file, open_regular_file,
    private_directory, validate_output_path, write_text_atomic,
)
from ..ownership import ownership_path, save_ownership, validate_owned_output
from . import publication_capabilities
from . import publication_snapshots as snapshots
from ..publication_contracts import PublicationInput
from ..publication_paths import retirement_path, transaction_path, validate_publication_paths


def _validate_journal_header(data, destination, cache):
    fields = {'version', 'destination', 'cache', 'phase', 'previous', 'new',
              'stage', 'stage_identity', 'cache_before', 'ownership_before'}
    if _journal_version(data) == 2:
        fields.add('cache_after')
    if set(data) != fields:
        raise ValueError('Invalid journal fields')
    if data['destination'] != str(destination) or data['cache'] != str(cache):
        raise ValueError('Wrong journal identity')


def _retired_cache_identity(data, destination, cache):
    if data['phase'] not in ('committed', 'rolled_back', 'capturing'):
        raise ValueError('Unsettled journal in retirement directory')
    original = Path(data['cache'])
    return original if partition_path(original, destination) == cache else cache


def _journal_version(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid journal fields')
    version = data.get('version')
    if type(version) is not int or version not in (1, 2):
        raise ValueError('Wrong journal version')
    return version


def _validate_identity_part(part):
    if type(part) is not int or part < 0:
        raise ValueError('Invalid journal file identity')


def _validate_phase(data):
    if data['phase'] == 'capturing':
        if data['version'] != 2 or any(data[key] is not None for key in ('cache_before', 'ownership_before')):
            raise ValueError('Invalid snapshot capture phase')
    elif data['phase'] not in ('prepared', 'old_moved', 'installed', 'committed', 'rolled_back'):
        raise ValueError('Invalid journal phase')


def _identity(path):
    validate_output_path(path)
    if not path.exists():
        return None
    metadata = path.stat()
    return [metadata.st_dev, metadata.st_ino]


def _restore_file(path, saved):
    validate_output_path(path)
    if saved is None:
        path.unlink(missing_ok=True)
        return
    content = base64.b64decode(saved, validate=True)
    with atomic_output(path, generated=True) as staged:
        with staged.open('wb') as target:
            target.write(content)


def _remove_tree(path):
    validate_output_path(path)
    with _directory_handle(path.parent) as parent:
        shutil.rmtree(path.name, dir_fd=parent)


def _validate_saved_state(data):
    if data['version'] == 2:
        snapshots.require_digest(data['cache_after'])
        snapshots.validate_claim(data['cache_before'])
        snapshots.validate_claim(data['ownership_before'])
    else:
        for key in ('cache_before', 'ownership_before'):
            if data[key] is not None:
                base64.b64decode(data[key], validate=True)


def _verify_saved_state(transaction, data):
    if data['version'] == 2 and data['phase'] not in ('committed', 'rolled_back'):
        snapshots.verify_snapshot(transaction / 'cache.before', data['cache_before'])
        snapshots.verify_snapshot(transaction / 'ownership.before', data['ownership_before'])


def _restore_saved_state(transaction, data, destination, cache):
    owners = ownership_path(destination)
    if data['version'] == 1:
        _restore_file(cache, data['cache_before'])
        _restore_file(owners, data['ownership_before'])
    else:
        snapshots.restore_cache(cache, transaction / 'cache.before', data['cache_before'],
                                data['cache_after'], str(destination))
        snapshots.restore_snapshot(owners, transaction / 'ownership.before', data['ownership_before'])


class PosixPublicationBackend:
    def __init__(self):
        self.capabilities = publication_capabilities()
        if not self.capabilities.available:
            raise RuntimeError('Native publication is unsupported on this platform')

    @contextmanager
    def locked(self, destination: Path, cache_path: Path):
        validate_publication_paths(destination, [cache_path])
        output_lock = destination.parent / f'.{destination.name}.articulous.lock'
        if cache_path.resolve() == output_lock.resolve():
            raise ValueError('Cache must not alias output lock')
        with lock_file(cache_lock_path(cache_path)), lock_file(output_lock):
            yield

    def _transaction(self, destination):
        return transaction_path(destination)

    def _rename(self, source, destination):
        validate_output_path(source)
        validate_output_path(destination)
        if destination.exists():
            raise ValueError(f'Publication destination already exists: {destination}')
        with _directory_handle(source.parent) as source_fd:
            with _directory_handle(destination.parent) as target_fd:
                os.rename(source.name, destination.name, src_dir_fd=source_fd, dst_dir_fd=target_fd)

    def _set_phase(self, transaction, data, phase):
        data['phase'] = phase
        write_text_atomic(transaction / 'journal.json', json.dumps(data))

    def _begin(self, publication):
        destination, cache = publication.destination, publication.cache_path
        stage = publication.root.parent
        data = {
            'version': 2, 'destination': str(destination), 'cache': str(cache),
            'previous': _identity(destination), 'new': _identity(publication.root),
            'stage': str(stage), 'stage_identity': _identity(stage),
            'cache_after': hashlib.sha256(publication.cache_text.encode()).hexdigest(),
            'cache_before': None, 'ownership_before': None,
        }
        transaction = self._transaction(destination)
        with private_directory(stage) as intent:
            self._set_phase(intent, data, 'capturing')
            self._rename(intent, transaction)
        try:
            data['cache_before'] = snapshots.snapshot(cache, transaction / 'cache.before')
            data['ownership_before'] = snapshots.snapshot(ownership_path(destination), transaction / 'ownership.before')
            self._set_phase(transaction, data, 'prepared')
        except BaseException:
            self.recover(destination, cache)
            raise
        return transaction, data

    def _write_state(self, publication):
        write_text_atomic(publication.cache_path, publication.cache_text)
        save_ownership(publication.destination, dict(publication.output_owners), routes=publication.output_routes,
                       generation=publication.generation, translations=dict(publication.translations))

    def _install(self, publication, transaction, data):
        destination = publication.destination
        self._expect(publication.root, data['new'])
        self._rename(publication.root, transaction / 'new')
        self._expect(destination, data['previous'])
        if data['previous'] is not None:
            self._rename(destination, transaction / 'previous')
        self._set_phase(transaction, data, 'old_moved')
        self._rename(transaction / 'new', destination)
        self._set_phase(transaction, data, 'installed')
        self._write_state(publication)
        self._set_phase(transaction, data, 'committed')

    def publish(self, publication: PublicationInput):
        validate_publication_paths(publication.destination, [publication.cache_path])
        publication.verify()
        validate_owned_output(publication.destination)
        transaction, data = self._begin(publication)
        try:
            self._install(publication, transaction, data)
        except BaseException:
            try:
                self.recover(publication.destination, publication.cache_path)
            except BaseException as error:
                raise RuntimeError(f'Publication needs recovery at {transaction}') from error
            raise
        try:
            self._cleanup(transaction, data)
        except (OSError, ValueError):
            logging.warning(f'Publication committed; cleanup pending at {transaction}', exc_info=True)

    def _read_journal(self, transaction, destination, cache, *, retired=False):
        try:
            with open_regular_file(transaction / 'journal.json') as source:
                data = json.load(source)
            if retired:
                cache = _retired_cache_identity(data, destination, cache)
            self._validate_journal(data, destination, cache)
            _verify_saved_state(transaction, data)
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
            raise ValueError(f'Invalid publication journal at {transaction}; preserve it for recovery') from error
        return data

    def _validate_journal(self, data, destination, cache):
        _validate_journal_header(data, destination, cache)
        _validate_phase(data)
        stage = Path(data['stage'])
        if stage.parent != destination.parent or not stage.name.startswith('.articulous-stage-'):
            raise ValueError('Invalid journal staging path')
        self._validate_identity(data['previous'], optional=True)
        for key in ('new', 'stage_identity'):
            self._validate_identity(data[key])
        _validate_saved_state(data)

    def _validate_identity(self, value, *, optional=False):
        if value is None and optional:
            return
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError('Invalid journal file identity')
        for part in value:
            _validate_identity_part(part)

    def _expect(self, path, identity):
        if _identity(path) != identity:
            raise ValueError(f'Publication path changed; preserve recovery data: {path}')

    def _rollback(self, transaction, data, destination, cache):
        previous = transaction / 'previous'
        if previous.exists():
            self._expect(previous, data['previous'])
            if destination.exists():
                self._expect(destination, data['new'])
                self._rename(destination, transaction / 'discard')
            self._rename(previous, destination)
        elif data['previous'] is None and destination.exists():
            self._expect(destination, data['new'])
            self._rename(destination, transaction / 'discard')
        self._expect(destination, data['previous'])
        _restore_saved_state(transaction, data, destination, cache)

    def _cleanup(self, transaction, data):
        stage = Path(data['stage'])
        if stage.exists():
            self._expect(stage, data['stage_identity'])
            _remove_tree(stage)
        self._retire_transaction(transaction, data)

    def _retire_transaction(self, transaction, data):
        for child in transaction.iterdir():
            if child.name == 'journal.json':
                continue
            if child.is_dir():
                _remove_tree(child)
            else:
                child.unlink()
        retired = retirement_path(transaction)
        self._rename(transaction, retired)
        self._finish_retirement(retired, Path(data['destination']), Path(data['cache']))

    def _finish_retirement(self, retired, destination, cache):
        validate_output_path(retired)
        if retired.exists():
            journal = retired / 'journal.json'
            if any(entry != journal for entry in retired.iterdir()):
                raise ValueError(f'Unexpected files in publication retirement directory: {retired}')
            if journal.exists():
                self._read_journal(retired, destination, cache, retired=True)
                journal.unlink()
            retired.rmdir()

    def recover(self, destination, cache_path):
        validate_publication_paths(destination, [cache_path])
        validate_output_path(destination)
        transaction = self._transaction(destination)
        validate_output_path(transaction)
        self._finish_retirement(retirement_path(transaction), destination, cache_path)
        if not transaction.exists():
            return
        data = self._read_journal(transaction, destination, cache_path)
        if data['phase'] == 'committed':
            self._expect(destination, data['new'])
        elif data['phase'] in ('capturing', 'rolled_back'):
            self._expect(destination, data['previous'])
        else:
            self._rollback(transaction, data, destination, cache_path)
            self._set_phase(transaction, data, 'rolled_back')
        self._cleanup(transaction, data)
