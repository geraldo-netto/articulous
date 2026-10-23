"""Linux process groups; retain a child PID lease until every member is quiescent."""
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time

from ..process_contracts import ProcessSession, SessionOptions, RecoveryToken, NativeCleanupError, deadline_seconds
from ..tooling_resources import tooling_resources
from ..source_files import cleanup_workspace, require_workspace, workspace_identity
from ..recovery_contracts import RecoveryRecord

_RETAINED = {}


def group_running(group: int) -> bool:
    for entry in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = entry.read_text().rpartition(') ')[2].split()
        except FileNotFoundError:
            continue
        if int(fields[2]) == group and fields[0] != 'Z':
            return True
    return False


def await_group_exit(group: int) -> None:
    deadline = time.monotonic() + 1
    while group_running(group):
        if time.monotonic() >= deadline:
            raise TimeoutError('Owned browser group did not stop after SIGKILL')
        time.sleep(.01)


class LinuxSession:
    def __init__(self, process: subprocess.Popen[str], options: SessionOptions = SessionOptions()):
        stdout, stderr = process.stdout, process.stderr
        if stdout is None or stderr is None:
            raise ValueError('Native session requires captured stdout and stderr')
        self._process = process
        self._stdout, self._stderr = stdout, stderr
        self._selector = selectors.DefaultSelector()
        self._buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        self._options = options
        self._checkpoint_scanned = 0
        self._checkpoint_emitted = 0
        self._code = None
        self.settled = False
        self._quiet = False
        self._drained = False
        try:
            self._selector.register(self._stdout, selectors.EVENT_READ, 'stdout')
            self._selector.register(self._stderr, selectors.EVENT_READ, 'stderr')
        except BaseException:
            self._selector.close()
            raise

    def _observe_exit(self):
        evidence = os.waitid(os.P_PID, self._process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if evidence is not None:
            self._code = evidence.si_status if evidence.si_code == os.CLD_EXITED else -evidence.si_status
        return self._code

    @property
    def returncode(self):
        return self._code if self.settled else self._observe_exit()

    def _read_ready(self, timeout):
        for key, _ in self._selector.select(timeout):
            chunk = os.read(key.fd, 65536)
            if chunk:
                self._buffers[key.data].extend(chunk)
            else:
                self._selector.unregister(key.fileobj)

    def _output(self):
        return bytes(self._buffers['stdout']).decode(), bytes(self._buffers['stderr']).decode()

    def _checkpoint_stderr(self):
        buffer = self._buffers['stderr']
        end = buffer.rfind(b'\n', self._checkpoint_scanned) + 1
        if not end:
            self._checkpoint_scanned = len(buffer)
            return b''
        with memoryview(buffer)[self._checkpoint_emitted:end] as borrowed:
            result = bytes(borrowed)
        self._checkpoint_scanned = len(buffer)
        self._checkpoint_emitted = end
        return result

    def _timeout(self, seconds):
        if self._options.checkpoint_output:
            return subprocess.TimeoutExpired(self._process.args, seconds, stderr=self._checkpoint_stderr())
        return subprocess.TimeoutExpired(self._process.args, seconds,
            output=bytes(self._buffers['stdout']), stderr=bytes(self._buffers['stderr']))

    def _collect(self, timeout):
        seconds = deadline_seconds(timeout) if timeout is not None else None
        deadline = time.monotonic() + seconds if seconds is not None else None
        while not self._drained:
            self._read_ready(.01)
            if self._observe_exit() is not None and not self._selector.get_map():
                self._drained = True
                return
            if seconds is not None and deadline is not None and time.monotonic() >= deadline:
                raise self._timeout(seconds)

    def communicate(self, timeout=None):
        if not self.settled:
            self._collect(timeout)
        return self._output()

    def signal_group(self, number):
        if self.settled:
            return
        self._observe_exit()
        try:
            os.killpg(self._process.pid, number)
        except ProcessLookupError:
            pass

    def stop(self):
        if self.settled:
            return self._output()
        if not self._quiet:
            self.signal_group(signal.SIGTERM)
            try:
                self._collect(1)
            except subprocess.TimeoutExpired:
                pass
            finally:
                self.signal_group(signal.SIGKILL)
                await_group_exit(self._process.pid)
                self._quiet = True
        self._collect(1)
        self._selector.close()
        self._stdout.close()
        self._stderr.close()
        self._reap()
        if not self.settled:
            raise RuntimeError('Native wait returned without exit evidence')
        return self._output()

    def _reap(self):
        try:
            self._process.wait()
        finally:
            self._code = self._process.returncode
            self.settled = self._code is not None


def stop_uninitialized(process):
    os.killpg(process.pid, signal.SIGKILL)
    await_group_exit(process.pid)
    process.stdout.close()
    process.stderr.close()
    process.wait()


def native_settled(session, process):
    if session is not None:
        return session.settled
    return process.returncode is not None and process.stdout.closed and process.stderr.closed


def finish_native(session, process):
    if session is None:
        stop_uninitialized(process)
    else:
        session.stop()


@dataclass(frozen=True)
class WorkspaceReservation:
    path: Path
    identity: tuple[int, int, int]


@dataclass
class NativeRecovery:
    session: LinuxSession | None
    process: subprocess.Popen
    workspace: WorkspaceReservation
    borrowed: list[WorkspaceReservation] = field(default_factory=list)
    record: RecoveryRecord | None = None


def defer_workspace_cleanup(token, path, identity):
    from .recovery import persist_reservation
    require_workspace(path, identity)
    _RETAINED[token].borrowed.append(WorkspaceReservation(path, identity))
    persist_reservation(_RETAINED[token])


def cleanup_recovery(reservation):
    for workspace in (reservation.workspace, *reservation.borrowed):
        cleanup_workspace(workspace.path, workspace.identity)
        if workspace.path.exists() or workspace.path.is_symlink():
            raise RuntimeError(f'Native workspace cleanup is incomplete: {workspace.path}')


def complete_recovery(token, reservation):
    from .recovery import remove_record
    try:
        cleanup_recovery(reservation)
        remove_record(reservation)
    except BaseException:
        _RETAINED[token] = reservation
        raise


def recover_session(token):
    reservation = _RETAINED.pop(token)
    try:
        finish_native(reservation.session, reservation.process)
    except BaseException:
        if native_settled(reservation.session, reservation.process):
            complete_recovery(token, reservation)
        else:
            _RETAINED[token] = reservation
        raise
    complete_recovery(token, reservation)


def recover_orphan(path):
    if sys.platform != 'linux':
        raise NotImplementedError('Durable native recovery is validated only on Linux')
    from .recovery import recover_orphan as recover
    recover(path, group_running)


def settle_session(session, process, scratch, identity):
    if process is None:
        cleanup_workspace(scratch, identity)
        return
    try:
        finish_native(session, process)
    except BaseException as error:
        if native_settled(session, process):
            cleanup_workspace(scratch, identity)
            raise
        token = RecoveryToken(process.pid, str(scratch))
        _RETAINED[token] = NativeRecovery(session, process, WorkspaceReservation(scratch, identity))
        try:
            from .recovery import persist_reservation
            persist_reservation(_RETAINED[token])
        except BaseException as storage_error:
            raise NativeCleanupError(token) from storage_error
        raise NativeCleanupError(token) from error
    cleanup_workspace(scratch, identity)



def session_environment(scratch, options: SessionOptions = SessionOptions()):
    environment = dict(os.environ, TMPDIR=str(scratch), ARTICULOUS_PYTHON=sys.executable)
    for name in ('ARTICULOUS_BROWSER_SESSION', 'ARTICULOUS_NATIVE_COVERAGE'):
        environment.pop(name, None)
    if not options.tooling:
        return environment
    tools = scratch / 'tools'
    tools.mkdir()
    for resource in tooling_resources():
        (tools / resource.path).write_bytes(resource.content)
    environment.update(ARTICULOUS_BROWSER_SESSION=(tools / 'browser-session.mjs').as_uri(),
                       ARTICULOUS_NATIVE_COVERAGE=(tools / 'native-coverage.mjs').as_uri())
    return environment


def _allocate_workspace():
    from .recovery import journal_path
    while True:
        scratch = Path(tempfile.mkdtemp(prefix='articulous-owned-'))
        identity = workspace_identity(scratch)
        journal = journal_path(scratch)
        if not journal.exists() and not journal.is_symlink():
            return scratch
        require_workspace(scratch, identity)
        scratch.rmdir()


@contextmanager
def open_session(command: Sequence[str], *, options: SessionOptions = SessionOptions()) -> Iterator[ProcessSession]:
    if not isinstance(options, SessionOptions):
        raise ValueError('Native session requires SessionOptions')
    if sys.platform != 'linux':
        raise NotImplementedError('Native browser supervision is validated only on Linux')
    scratch = _allocate_workspace()
    identity = workspace_identity(scratch)
    process, session = None, None
    try:
        environment = session_environment(scratch, options)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8', start_new_session=True, env=environment)
        session = LinuxSession(process, options)
        yield session
    finally:
        settle_session(session, process, scratch, identity)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Recover a retained native reservation after owner loss')
    parser.add_argument('journal', type=Path)
    args = parser.parse_args(argv)
    recover_orphan(args.journal)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
