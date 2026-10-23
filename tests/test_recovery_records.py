"""LIFE-002: bounded malformed-record, identity and partial-storage controls."""
from dataclasses import replace
import json
import os
from pathlib import Path
import random
import stat
import sys
from unittest.mock import Mock, patch

import pytest

from articulous.backends import processes, recovery
from articulous.recovery_contracts import (
    ProcessGeneration, RecoveryRecord, WorkspaceClaim, decode_record, encode_record,
)
from articulous.source_files import workspace_identity


@pytest.fixture
def record(tmp_path):
    workspace = tmp_path / 'native'
    workspace.mkdir()
    return RecoveryRecord(recovery.boot_identity(), ProcessGeneration(2**31 - 1, 0),
                          ProcessGeneration(2**31 - 1, 0),
                          (WorkspaceClaim(str(workspace), workspace_identity(workspace)),))


def write(record):
    path = recovery.journal_path(record.workspaces[0].path)
    recovery.write_record(path, record)
    return path


def test_life002_record_roundtrip_and_cli_recovery(record):
    path = write(record)
    assert decode_record(json.loads(path.read_bytes())) == record
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert processes.main([str(path)]) == 0
    assert not path.exists()
    assert not Path(record.workspaces[0].path).exists()


@pytest.mark.parametrize('value', [None, [], {}, {'extra': True}])
def test_life002_record_field_set(value):
    with pytest.raises(ValueError, match='fields'):
        decode_record(value)


@pytest.mark.parametrize('seed', [0, 3, 2026, 0xC0FFEE])
def test_life002_bounded_invalid_record_fuzz(record, seed):
    randomizer = random.Random(seed)
    mutations = [None, [], {}, False, '', 0, -1, 2**80]
    for field in ('version', 'owner', 'process', 'workspaces', 'boot'):
        randomizer.shuffle(mutations)
        for value in mutations:
            payload = encode_record(record)
            payload[field] = value
            with pytest.raises(ValueError):
                decode_record(payload)


@pytest.mark.parametrize('value', [None, [], [1], [1, 2, 3], [True, 0], [-1, 0], [1, '0']])
def test_life002_generation_shapes(record, value):
    payload = encode_record(record)
    payload['owner'] = value
    with pytest.raises(ValueError):
        decode_record(payload)


@pytest.mark.parametrize('pid', [True, -1, 0, 2**31, '1'])
def test_life002_pid_boundaries(pid):
    with pytest.raises(ValueError):
        ProcessGeneration(pid, 0)
    assert ProcessGeneration(1, 0).pid == 1
    assert ProcessGeneration(2**31 - 1, 2**80).started == 2**80


@pytest.mark.parametrize('path', [None, '', '/', 'relative', '/tmp/../other', '/tmp//double', '/tmp/./dot', '/tmp/bad\0path'])
def test_life002_workspace_path_boundaries(path):
    with pytest.raises(ValueError):
        WorkspaceClaim(path, (1, 2, stat.S_IFDIR | 0o700))


@pytest.mark.parametrize('identity', [[1, 2, stat.S_IFDIR], (1,), (1, 2, stat.S_IFREG), (1, False, stat.S_IFDIR)])
def test_life002_workspace_identity_boundaries(identity):
    with pytest.raises(ValueError):
        WorkspaceClaim('/tmp/valid', identity)


@pytest.mark.parametrize('claims', [(), [], (None,)])
def test_life002_claim_collection_boundaries(record, claims):
    with pytest.raises(ValueError):
        replace(record, workspaces=claims)
    with pytest.raises(ValueError, match='Duplicate'):
        replace(record, workspaces=record.workspaces * 2)


@pytest.mark.parametrize('field', ['owner', 'process'])
def test_life002_contract_requires_generations(record, field):
    with pytest.raises(ValueError):
        replace(record, **{field: None})


@pytest.mark.parametrize('value', [None, [], ['only-path'], ['path', [1]], ['path', [1, 2, 3], 'extra']])
def test_life002_malformed_workspace_records(record, value):
    payload = encode_record(record)
    payload['workspaces'] = [value]
    with pytest.raises(ValueError):
        decode_record(payload)


def test_life002_storage_capacity_and_invalid_json(record):
    path = write(record)
    with patch.object(recovery, 'MAX_RECORD_BYTES', 2):
        with pytest.raises(ValueError, match='capacity'):
            recovery.write_record(path, record)
        with pytest.raises(ValueError, match='capacity'):
            processes.recover_orphan(path)
    path.write_bytes(b'{broken')
    with pytest.raises(ValueError):
        processes.recover_orphan(path)
    assert Path(record.workspaces[0].path).exists()


@pytest.mark.parametrize('offset', [-1, 0, 1])
def test_life002_exact_record_capacity_boundary(record, offset, monkeypatch):
    path = write(record)
    monkeypatch.setattr(recovery, 'MAX_RECORD_BYTES', path.stat().st_size + offset)
    if offset < 0:
        with pytest.raises(ValueError, match='capacity'):
            recovery.write_record(path, record)
        with pytest.raises(ValueError, match='capacity'):
            processes.recover_orphan(path)
    else:
        recovery.write_record(path, record)
        processes.recover_orphan(path)
        assert not path.exists()


@pytest.mark.parametrize('kind', ['mode', 'link', 'uid', 'swap'])
def test_life002_journal_identity_controls(record, tmp_path, kind):
    path = write(record)
    with recovery.open_regular_file(path) as source:
        if kind == 'mode':
            path.chmod(0o644)
        if kind == 'link':
            os.link(path, tmp_path / 'alias')
        if kind == 'swap':
            path.rename(tmp_path / 'original')
            path.write_text('replacement')
        with patch.object(recovery.os, 'getuid', return_value=-1 if kind == 'uid' else os.getuid()):
            with pytest.raises(ValueError, match='journal'):
                recovery.require_file_identity(path, source)


def test_life002_journal_location_and_exclusive_claim(record, tmp_path):
    path = write(record)
    with recovery.claim_record(path):
        with pytest.raises(BlockingIOError):
            with recovery.claim_record(path):
                pytest.fail('concurrent recovery admitted')
    alternate = tmp_path / 'other.json'
    path.rename(alternate)
    with pytest.raises(ValueError, match='path'):
        processes.recover_orphan(alternate)


def test_life002_generation_and_live_group_controls(record):
    with patch.object(recovery, 'process_state', return_value=(record.process, 'S')):
        with pytest.raises(RuntimeError, match='live'):
            recovery.require_native_quiet(record, Mock())
    with patch.object(recovery, 'process_state', return_value=(ProcessGeneration(1, 2), 'Z')):
        with pytest.raises(RuntimeError, match='generation changed'):
            recovery.require_native_quiet(record, Mock())
    with patch.object(recovery, 'process_state', return_value=(record.process, 'Z')):
        with pytest.raises(RuntimeError, match='group is still live'):
            recovery.require_native_quiet(record, Mock(return_value=True))
    with patch.object(recovery, 'process_state', return_value=None):
        with pytest.raises(RuntimeError, match='unavailable'):
            recovery.generation(record.process.pid)


def test_life002_reboot_and_zombie_owner_controls(record):
    different_boot = '00000000-0000-0000-0000-000000000000'
    with patch.object(recovery, 'boot_identity', return_value=different_boot):
        recovery.require_owner_lost(record)
        recovery.require_native_quiet(record, Mock(side_effect=AssertionError('no old-boot signals')))
    with patch.object(recovery, 'process_state', return_value=(record.owner, 'Z')):
        recovery.require_owner_lost(record)


def test_life002_replacement_workspace_is_preserved(record, tmp_path):
    path = write(record)
    workspace = Path(record.workspaces[0].path)
    workspace.rename(tmp_path / 'original')
    workspace.mkdir()
    (workspace / 'keep').write_text('replacement')
    with pytest.raises(ValueError, match='identity changed'):
        processes.recover_orphan(path)
    assert path.exists() and (workspace / 'keep').read_text() == 'replacement'


def test_life002_partial_cleanup_retry_and_journal_replacement(record, tmp_path):
    borrowed = tmp_path / 'borrowed'
    borrowed.mkdir()
    record = replace(record, workspaces=(*record.workspaces, WorkspaceClaim(str(borrowed), workspace_identity(borrowed))))
    path = write(record)
    release = recovery.release_claim
    with patch.object(recovery, 'release_claim', side_effect=[None, KeyboardInterrupt]):
        with pytest.raises(KeyboardInterrupt):
            processes.recover_orphan(path)
    assert path.exists()
    release(record.workspaces[0])
    processes.recover_orphan(path)
    assert not borrowed.exists() and not path.exists()


def test_life002_changed_reservation_rejected(record):
    with pytest.raises(ValueError, match='reservation changed'):
        recovery.require_same_reservation(replace(record, owner=ProcessGeneration(1, 1)), record)
    with pytest.raises(ValueError, match='obligations changed'):
        recovery.require_same_reservation(record, replace(record, workspaces=(WorkspaceClaim('/other', (1, 2, stat.S_IFDIR)),)))
    recovery.require_same_reservation(record, record)


def test_life002_unknown_native_evidence_keeps_every_claim(record):
    path = write(record)
    with patch.object(recovery, 'process_state', side_effect=PermissionError('proc evidence unavailable')):
        with pytest.raises(PermissionError):
            processes.recover_orphan(path)
    assert path.exists() and Path(record.workspaces[0].path).exists()


def test_life002_unavailable_native_recovery_remains_unsupported():
    with patch.object(processes.sys, 'platform', 'win32'):
        with pytest.raises(NotImplementedError, match='Linux'):
            processes.recover_orphan('/unopened')


def test_life002_atomic_record_write_failure_retains_local_owner():
    before = set(processes._RETAINED)
    try:
        with patch.object(processes, 'await_group_exit', side_effect=TimeoutError('fence')):
            with patch.object(recovery, 'write_record', side_effect=OSError('storage unavailable')):
                with pytest.raises(RuntimeError, match='recovery') as failure:
                    with processes.open_session([sys.executable, '-c', 'pass']):
                        pass
        token = (set(processes._RETAINED) - before).pop()
        assert isinstance(failure.value.__cause__, OSError)
        assert Path(token.workspace).exists()
        processes.recover_session(token)
        assert token not in processes._RETAINED
    finally:
        for token in set(processes._RETAINED) - before:
            processes.recover_session(token)


def test_life002_failed_fsync_keeps_complete_journal_and_closes_descriptors(record):
    path = recovery.journal_path(record.workspaces[0].path)
    descriptors = len(list(Path('/proc/self/fd').iterdir()))
    with patch.object(recovery.os, 'fsync', side_effect=OSError('storage')):
        with pytest.raises(OSError):
            recovery.write_record(path, record)
    assert not path.exists()
    assert len(list(Path('/proc/self/fd').iterdir())) == descriptors
    assert list(path.parent.glob('.articulous-*')) == []
    write(record)
    processes.recover_orphan(path)


def test_life002_journal_replacement_never_deleted(record, tmp_path):
    path = write(record)
    replacement = tmp_path / 'replacement'
    replacement.write_text('keep')
    native_release = recovery.release_claim

    def swapped_release(claim):
        native_release(claim)
        path.rename(tmp_path / 'original-record')
        replacement.rename(path)

    with patch.object(recovery, 'release_claim', swapped_release):
        with pytest.raises(ValueError, match='identity changed'):
            processes.recover_orphan(path)
    assert path.read_text() == 'keep'


def test_life002_durable_reservation_prevents_scratch_name_reuse(record, tmp_path):
    path = write(record)
    reserved = Path(record.workspaces[0].path)
    reserved.rename(tmp_path / 'original-allocation')
    reserved.mkdir()
    fresh = tmp_path / 'fresh'
    fresh.mkdir()
    with patch.object(processes.tempfile, 'mkdtemp', side_effect=[str(reserved), str(fresh)]):
        with processes.open_session([sys.executable, '-c', 'import os; print(os.environ["TMPDIR"])']) as session:
            assert session.communicate()[0].strip() == str(fresh), 'LIFE-002: a journal reserves its scratch name across partial cleanup'
    assert path.exists()


def test_life002_persistence_cannot_replace_another_reservation(record, tmp_path):
    path = write(record)
    reservation = processes.NativeRecovery(None, Mock(pid=record.process.pid),
        processes.WorkspaceReservation(Path(record.workspaces[0].path), record.workspaces[0].identity),
        record=replace(record, owner=ProcessGeneration(1, 1)))
    with pytest.raises(ValueError, match='reservation changed'):
        recovery.persist_reservation(reservation)
    assert decode_record(json.loads(path.read_bytes())) == record


def test_life002_uninspectable_workspace_is_not_completed_cleanup(record, tmp_path):
    parent = tmp_path / 'parent'
    parent.mkdir()
    borrowed = parent / 'borrowed'
    borrowed.mkdir()
    record = replace(record, workspaces=(*record.workspaces, WorkspaceClaim(str(borrowed), workspace_identity(borrowed))))
    path = write(record)
    parent.rename(tmp_path / 'original-parent')
    parent.write_text('replacement')
    with pytest.raises(NotADirectoryError):
        processes.recover_orphan(path)
    assert path.exists(), 'LIFE-002: unknown workspace evidence must retain the durable obligation'
