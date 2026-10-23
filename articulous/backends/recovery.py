"""Linux operator recovery of trusted, durable native-session reservations."""
from contextlib import contextmanager
from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import stat

from ..filesystem import _generated_output, open_regular_file
from ..recovery_contracts import ProcessGeneration, RecoveryRecord, WorkspaceClaim, decode_record, encode_record
from ..source_files import require_workspace

MAX_RECORD_BYTES = 1024 * 1024


def boot_identity():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def process_state(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rpartition(') ')[2].split()
    except FileNotFoundError:
        return None
    return ProcessGeneration(pid, int(fields[19])), fields[0]


def generation(pid):
    state = process_state(pid)
    if state is None:
        raise RuntimeError('Native process generation is unavailable')
    return state[0]


def journal_path(workspace):
    return Path(str(workspace) + '.recovery.json')


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_record(path, record):
    payload = json.dumps(encode_record(record), separators=(',', ':')).encode()
    if len(payload) > MAX_RECORD_BYTES:
        raise ValueError('Recovery record capacity exceeded')
    with _generated_output(path, permissions=0o600) as staged:
        staged.write_bytes(payload)
        os.fsync(staged.fd)
    sync_directory(path.parent)


def reservation_record(reservation):
    return RecoveryRecord(boot_identity(), generation(os.getpid()),
                          generation(reservation.process.pid), workspace_claims(reservation))


def workspace_claims(reservation):
    return tuple(WorkspaceClaim(str(item.path), item.identity)
                 for item in (reservation.workspace, *reservation.borrowed))


def persist_reservation(reservation):
    path = journal_path(reservation.workspace.path)
    record = reservation.record or reservation_record(reservation)
    record = replace(record, workspaces=workspace_claims(reservation))
    reservation.record = record
    if path.exists() or path.is_symlink():
        with claim_record(path) as (existing, _):
            require_same_reservation(existing, record)
    write_record(path, record)


def remove_record(reservation):
    if reservation.record is None:
        return
    path = journal_path(reservation.workspace.path)
    if not path.exists() and not path.is_symlink():
        return
    with claim_record(path) as (record, source):
        require_same_reservation(record, reservation.record)
        require_file_identity(path, source)
        path.unlink()
        sync_directory(path.parent)


def require_same_reservation(actual, expected):
    if (actual.boot, actual.owner, actual.process) != (expected.boot, expected.owner, expected.process):
        raise ValueError('Recovery journal reservation changed')
    if not set(actual.workspaces).issubset(expected.workspaces):
        raise ValueError('Recovery journal workspace obligations changed')


def require_file_identity(path, source):
    actual, expected = path.lstat(), os.fstat(source.fileno())
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        raise ValueError('Recovery journal identity changed')
    if expected.st_uid != os.getuid() or stat.S_IMODE(expected.st_mode) != 0o600 or expected.st_nlink != 1:
        raise ValueError('Recovery journal must be private and singly owned')


@contextmanager
def claim_record(path):
    with open_regular_file(path) as source:
        fcntl.flock(source.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_file_identity(path, source)
        payload = source.read(MAX_RECORD_BYTES + 1)
        if len(payload) > MAX_RECORD_BYTES:
            raise ValueError('Recovery record capacity exceeded')
        record = decode_record(json.loads(payload))
        if journal_path(record.workspaces[0].path) != path:
            raise ValueError('Recovery journal path does not match its reservation')
        yield record, source


def require_owner_lost(record):
    if record.boot != boot_identity():
        return
    state = process_state(record.owner.pid)
    if state is not None and state[0] == record.owner and state[1] != 'Z':
        raise RuntimeError('Recovery owner is still live')


def require_native_quiet(record, group_running):
    if record.boot != boot_identity():
        return
    state = process_state(record.process.pid)
    if state is not None:
        if state[0] != record.process:
            raise RuntimeError('Native process generation changed; preserve reservation')
        if state[1] != 'Z':
            raise RuntimeError('Native process is still live; operator fence required')
    if group_running(record.process.pid):
        raise RuntimeError('Native group is still live; operator fence required')


def release_claim(claim):
    path = Path(claim.path)
    try:
        require_workspace(path, claim.identity)
    except FileNotFoundError:
        return
    import shutil
    shutil.rmtree(path)
    sync_directory(path.parent)


def recover_orphan(path, group_running):
    path = Path(path).absolute()
    with claim_record(path) as (record, source):
        require_owner_lost(record)
        require_native_quiet(record, group_running)
        require_file_identity(path, source)
        for claim in record.workspaces:
            release_claim(claim)
        require_file_identity(path, source)
        path.unlink()
        sync_directory(path.parent)
