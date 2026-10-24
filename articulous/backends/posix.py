"""Linux-validated directory publication with rollback and a recovery journal."""
import base64
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import shutil

from ..filesystem import (
    _directory_handle, atomic_output, cache_lock_path, lock_file, open_regular_file,
    validate_output_path, write_text_atomic,
)
from ..ownership import ownership_path, save_ownership, validate_owned_output
from . import publication_capabilities
from ..publication_contracts import PublicationInput


def _validate_journal_header(data, destination, cache):
    fields = {'version', 'destination', 'cache', 'phase', 'previous', 'new',
              'stage', 'stage_identity', 'cache_before', 'ownership_before'}
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError('Invalid journal fields')
    if type(data['version']) is not int or data['version'] != 1:
        raise ValueError('Wrong journal version')
    if data['destination'] != str(destination) or data['cache'] != str(cache):
        raise ValueError('Wrong journal identity')


def _validate_identity_part(part):
    if type(part) is not int or part < 0:
        raise ValueError('Invalid journal file identity')


def _identity(path):
    validate_output_path(path)
    if not path.exists():
        return None
    metadata = path.stat()
    return [metadata.st_dev, metadata.st_ino]


def _saved_file(path):
    validate_output_path(path)
    try:
        with open_regular_file(path) as source:
            if os.fstat(source.fileno()).st_nlink != 1:
                raise ValueError('Publication state must have one hardlink')
            return base64.b64encode(source.read()).decode('ascii')
    except FileNotFoundError:
        return None


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


class PosixPublicationBackend:
    def __init__(self):
        self.capabilities = publication_capabilities()
        if not self.capabilities.available:
            raise RuntimeError('Native publication is unsupported on this platform')

    @contextmanager
    def locked(self, destination: Path, cache_path: Path):
        output_lock = destination.parent / f'.{destination.name}.articulous.lock'
        if cache_path.resolve() == output_lock.resolve():
            raise ValueError('Cache must not alias output lock')
        with lock_file(cache_lock_path(cache_path)), lock_file(output_lock):
            yield

    def _transaction(self, destination):
        return destination.parent / f'.{destination.name}.articulous-transaction'

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
            'version': 1, 'destination': str(destination), 'cache': str(cache),
            'previous': _identity(destination), 'new': _identity(publication.root),
            'stage': str(stage), 'stage_identity': _identity(stage),
            'cache_before': _saved_file(cache), 'ownership_before': _saved_file(ownership_path(destination)),
        }
        transaction = self._transaction(destination)
        transaction.mkdir(mode=0o700)
        try:
            self._set_phase(transaction, data, 'prepared')
        except BaseException:
            _remove_tree(transaction)
            raise
        return transaction, data

    def _write_state(self, publication):
        write_text_atomic(publication.cache_path, publication.cache_text)
        save_ownership(publication.destination, dict(publication.output_owners))

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

    def _read_journal(self, transaction, destination, cache):
        try:
            with open_regular_file(transaction / 'journal.json') as source:
                data = json.load(source)
            self._validate_journal(data, destination, cache)
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise ValueError(f'Invalid publication journal at {transaction}; preserve it for recovery') from error
        return data

    def _validate_journal(self, data, destination, cache):
        _validate_journal_header(data, destination, cache)
        if data['phase'] not in ('prepared', 'old_moved', 'installed', 'committed'):
            raise ValueError('Invalid journal phase')
        stage = Path(data['stage'])
        if stage.parent != destination.parent or not stage.name.startswith('.articulous-stage-'):
            raise ValueError('Invalid journal staging path')
        self._validate_identity(data['previous'], optional=True)
        for key in ('new', 'stage_identity'):
            self._validate_identity(data[key])
        for key in ('cache_before', 'ownership_before'):
            if data[key] is not None:
                base64.b64decode(data[key], validate=True)

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
        _restore_file(cache, data['cache_before'])
        _restore_file(ownership_path(destination), data['ownership_before'])

    def _cleanup(self, transaction, data):
        stage = Path(data['stage'])
        if stage.exists():
            self._expect(stage, data['stage_identity'])
            _remove_tree(stage)
        _remove_tree(transaction)

    def recover(self, destination, cache_path):
        validate_output_path(destination)
        transaction = self._transaction(destination)
        validate_output_path(transaction)
        if not transaction.exists():
            return
        data = self._read_journal(transaction, destination, cache_path)
        if data['phase'] == 'committed':
            self._expect(destination, data['new'])
        else:
            self._rollback(transaction, data, destination, cache_path)
        self._cleanup(transaction, data)
