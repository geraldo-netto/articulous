"""Durable native reservations, independent of process and storage adapters."""
from dataclasses import dataclass
import stat
from pathlib import PurePosixPath
from uuid import UUID


def _integers(value, length):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError('Invalid recovery identity shape')
    if any(type(part) is not int or part < 0 for part in value):
        raise ValueError('Invalid recovery identity integers')
    return tuple(value)


@dataclass(frozen=True)
class ProcessGeneration:
    pid: int
    started: int

    def __post_init__(self):
        _integers((self.pid, self.started), 2)
        if not 0 < self.pid < 2**31:
            raise ValueError('Invalid recovery PID')


@dataclass(frozen=True)
class WorkspaceClaim:
    path: str
    identity: tuple[int, int, int]

    def __post_init__(self):
        if not isinstance(self.path, str) or '\0' in self.path:
            raise ValueError('Invalid recovery workspace path')
        path = PurePosixPath(self.path)
        if not path.is_absolute() or str(path) != self.path or '..' in path.parts or self.path == '/':
            raise ValueError('Invalid recovery workspace path')
        if not isinstance(self.identity, tuple):
            raise ValueError('Recovery workspace identity must be immutable')
        _integers(self.identity, 3)
        if not stat.S_ISDIR(self.identity[2]):
            raise ValueError('Recovery workspace must be a directory')


@dataclass(frozen=True)
class RecoveryRecord:
    boot: str
    owner: ProcessGeneration
    process: ProcessGeneration
    workspaces: tuple[WorkspaceClaim, ...]

    def __post_init__(self):
        if not isinstance(self.boot, str) or str(UUID(self.boot)) != self.boot:
            raise ValueError('Invalid recovery boot identity')
        if not isinstance(self.owner, ProcessGeneration) or not isinstance(self.process, ProcessGeneration):
            raise ValueError('Invalid recovery process generation')
        _validate_claims(self.workspaces)


def _validate_claims(claims):
    if not isinstance(claims, tuple) or not claims:
        raise ValueError('Recovery requires workspace claims')
    if not all(isinstance(claim, WorkspaceClaim) for claim in claims):
        raise ValueError('Invalid recovery workspace claims')
    paths = tuple(claim.path for claim in claims)
    if len(set(paths)) != len(paths):
        raise ValueError('Duplicate recovery workspace claims')


def decode_record(value):
    if not isinstance(value, dict) or set(value) != {'version', 'boot', 'owner', 'process', 'workspaces'}:
        raise ValueError('Invalid recovery record fields')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Invalid recovery record version')
    if not isinstance(value['workspaces'], list):
        raise ValueError('Invalid recovery workspace list')
    return RecoveryRecord(value['boot'], ProcessGeneration(*_integers(value['owner'], 2)),
                          ProcessGeneration(*_integers(value['process'], 2)),
                          tuple(_decode_claim(claim) for claim in value['workspaces']))


def _decode_claim(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('Invalid recovery workspace record')
    return WorkspaceClaim(value[0], _integers(value[1], 3))


def encode_record(record):
    return {'version': 1, 'boot': record.boot,
            'owner': [record.owner.pid, record.owner.started],
            'process': [record.process.pid, record.process.started],
            'workspaces': [[claim.path, list(claim.identity)] for claim in record.workspaces]}
