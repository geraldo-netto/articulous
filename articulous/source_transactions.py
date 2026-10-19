"""Stage import files and roll back failed publication without replacing the repository."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile

from .source_files import cleanup_workspace, require_workspace, workspace_identity

def fingerprint(path):
    try:
        with path.open('rb') as source:
            return hashlib.file_digest(source, 'sha256').digest()
    except FileNotFoundError:
        return None


def check_overwrite(path, previous, content, force):
    if previous is not None and previous != hashlib.sha256(content).digest() and not force:
        raise ValueError(f'Refusing to overwrite edited source: {path}; review and use --force deliberately')


def write_import(path, content, force):
    check_overwrite(path, fingerprint(path), content, force)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class SourceTransaction:
    def __init__(self, output, workspace, final_paths=()):
        self.output = output
        self.final_paths = tuple(Path(path) for path in final_paths)
        self.workspace = workspace
        self.identity = workspace_identity(workspace)
        self.stage = workspace / 'new'
        self.stage.mkdir()
        self.expected = {}
        self.recovery_required = False

    def destination(self, relative):
        relative = Path(relative)
        if relative.is_absolute() or not relative.parts or '..' in relative.parts:
            raise ValueError(f'Invalid source path: {relative}')
        target = self.output / relative
        current = target
        while current != self.output:
            if current.is_symlink():
                raise ValueError(f'Refusing symlink import destination: {current}')
            current = current.parent
        return target

    def capture(self, relative):
        relative = Path(relative)
        if relative not in self.expected:
            self.expected[relative] = fingerprint(self.destination(relative))
        return self.expected[relative]

    def write(self, relative, content, force=False):
        previous = self.capture(relative)
        check_overwrite(self.destination(relative), previous, content, force)
        write_import(self.stage / relative, content, force)

    def changes(self):
        require_workspace(self.workspace, self.identity)
        changes = []
        for relative, expected in self.expected.items():
            if fingerprint(self.destination(relative)) != expected:
                raise ValueError(f'Import destination changed during staging: {relative}')
        for source in self.stage.rglob('*'):
            if not source.is_file():
                continue
            relative = source.relative_to(self.stage)
            if fingerprint(source) != self.expected[relative]:
                changes.append(relative)
        def publication_order(path):
            return path in self.final_paths, path
        return sorted(changes, key=publication_order)

    def publish(self):
        changes = self.changes()
        journal, directories = [], []
        try:
            for relative in changes:
                target = self.destination(relative)
                if fingerprint(target) != self.expected[relative]:
                    raise ValueError(f'Import destination changed during publication: {relative}')
                make_parents(target.parent, directories)
                backup = self.workspace / 'previous' / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                journal.append((target, backup, self.expected[relative] is not None))
                if self.expected[relative] is not None:
                    target.replace(backup)
                staged = self.stage / relative
                if backup.exists():
                    staged.chmod(backup.stat().st_mode)
                staged.replace(target)
        except BaseException:
            self.rollback(journal, directories)
            raise

    def rollback(self, journal, directories):
        self.recovery_required = True
        errors = []
        for target, backup, existed in reversed(journal):
            try:
                if backup.exists():
                    backup.replace(target)
                elif not existed:
                    target.unlink(missing_ok=True)
            except OSError as error:
                errors.append(error)
        for directory in reversed(directories):
            try:
                directory.rmdir()
            except OSError as error:
                errors.append(error)
        if errors:
            raise RuntimeError(f'Import rollback needs recovery; retained workspace: {self.workspace}') from errors[0]
        self.recovery_required = False


def make_parents(directory, created):
    missing = []
    while not directory.exists():
        missing.append(directory)
        directory = directory.parent
    for directory in reversed(missing):
        directory.mkdir()
        created.append(directory)


@contextmanager
def source_transaction(output, *, final_paths=(), prefix='.articulous-edit-'):
    output = Path(output).resolve()
    parent = output.parent
    while not parent.exists():
        parent = parent.parent
    workspace = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    identity = workspace_identity(workspace)
    transaction = None
    try:
        transaction = SourceTransaction(output, workspace, final_paths)
        yield transaction
        transaction.publish()
    finally:
        if transaction is None or not transaction.recovery_required:
            cleanup_workspace(workspace, identity)
