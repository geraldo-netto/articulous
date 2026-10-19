"""TEST-002: never reap an owned group leader before the group's native fence."""
import os
import sys
from articulous.backends.processes import LinuxSession, open_session


from unittest.mock import patch
import pytest
from articulous.backends import processes
from articulous import browser_process


def test_test002_child_identity_is_held_until_group_fence():
    with open_session([sys.executable, '-c', 'print("complete")']) as session:
        assert isinstance(session, LinuxSession)
        assert session.communicate() == ('complete\n', '')
        assert session.returncode == 0
        evidence = os.waitid(os.P_PID, session._process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        assert evidence is not None, 'TEST-002: retain the child PID lease until group cleanup settles'



def test_test002_stopped_session_is_idempotent():
    with open_session([sys.executable, '-c', 'print("done")']) as session:
        assert isinstance(session, LinuxSession)
        session.stop()
        assert session.settled
        session.signal_group(15)
        assert session.stop() == session.communicate()


def test_test002_retained_unknown_fence_is_recoverable():
    scratch, session, pid = None, None, 0
    with patch.object(processes, 'await_group_exit', side_effect=TimeoutError('missing fence')):
        with pytest.raises(RuntimeError, match='retained'):
            with open_session([sys.executable, '-c', 'pass']) as session:
                assert isinstance(session, LinuxSession)
                pid = session._process.pid
    token = next(token for token in processes._RETAINED if token.pid == pid)
    reservation = processes._RETAINED[token]
    scratch = reservation.workspace.path
    assert scratch.is_dir()
    assert reservation.session is session
    assert isinstance(session, LinuxSession)
    assert os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    processes.recover_session(token)
    assert not scratch.exists()
    assert token not in processes._RETAINED


class BrokenSelector:
    def __init__(self, native):
        self.native = native
        self.closed = False

    def register(self, *args):
        raise RuntimeError('selector fault')

    def close(self):
        self.closed = True
        self.native.close()


@pytest.mark.parametrize('missing_fence', [False, True])
def test_test002_partial_session_initialization_settles(missing_fence):
    selector = BrokenSelector(processes.selectors.DefaultSelector())
    observed = []
    popen = processes.subprocess.Popen
    def launch(*args, **kwargs):
        process = popen(*args, **kwargs)
        observed.append(process)
        return process
    with patch.object(processes.selectors, 'DefaultSelector', return_value=selector), patch.object(processes.subprocess, 'Popen', side_effect=launch):
        if missing_fence:
            with patch.object(processes, 'await_group_exit', side_effect=TimeoutError('fence')):
                with pytest.raises(RuntimeError, match='recovery'):
                    with open_session([sys.executable, '-c', 'pass']):
                        pytest.fail('no session may escape failed initialization')
            processes.recover_session(next(token for token in processes._RETAINED if token.pid == observed[0].pid))
        else:
            with pytest.raises(RuntimeError, match='selector fault'):
                with open_session([sys.executable, '-c', 'pass']):
                    pytest.fail('no session may escape failed initialization')
    assert selector.closed
    assert observed[0].returncode is not None
    assert observed[0].stdout.closed and observed[0].stderr.closed


def test_test002_missing_signal_target_and_cli_report(capsys):
    with open_session([sys.executable, '-c', 'pass']) as session:
        assert isinstance(session, LinuxSession)
        with patch.object(processes.os, 'killpg', side_effect=ProcessLookupError):
            session.signal_group(15)
    browser_process.report_progress('settled')
    assert 'settled' in capsys.readouterr().err
    result = processes.subprocess.CompletedProcess(['fake'], 7, 'output', 'error')
    with patch.object(browser_process, 'run_browser_suite', return_value=result):
        assert browser_process.main(['fake']) == 7
    captured = capsys.readouterr()
    assert captured.out == 'output' and captured.err == 'error'


def test_test002_owned_command_propagates_native_failure():
    result = browser_process.run_owned([sys.executable, '-c', 'print("ok")'])
    assert result.stdout == 'ok\n'
    with pytest.raises(processes.subprocess.CalledProcessError):
        browser_process.run_owned([sys.executable, '-c', 'raise SystemExit(7)'])


def test_test002_missing_pipe_and_completion_evidence_fail_closed():
    from unittest.mock import Mock
    with pytest.raises(ValueError, match='captured'):
        LinuxSession(Mock(stdout=None, stderr=None))
    with pytest.raises(RuntimeError, match='exit evidence'):
        browser_process.completed_session(['fake'], Mock(returncode=None), '', '')


def test_test002_invalid_utf8_diagnostics_do_not_retain_native_resources():
    before = set(processes._RETAINED)
    try:
        with pytest.raises(UnicodeDecodeError):
            browser_process.run_owned([sys.executable, '-c', 'import os;os.write(1,bytes([255]))'])
        assert set(processes._RETAINED) == before
    finally:
        # Faulty-control cleanup sponsors any lease retained by the pre-fix decoder.
        with patch.object(LinuxSession, '_output', return_value=('', '')):
            for pid in set(processes._RETAINED) - before:
                processes.recover_session(pid)


def test_test002_interruption_after_reap_settles_known_resources():
    before = set(processes._RETAINED)
    wait = processes.subprocess.Popen.wait
    def interrupted_wait(process, *args, **kwargs):
        wait(process, *args, **kwargs)
        raise KeyboardInterrupt
    try:
        with patch.object(processes.subprocess.Popen, 'wait', interrupted_wait):
            with pytest.raises(KeyboardInterrupt):
                with open_session([sys.executable, '-c', 'pass']):
                    pass
        assert set(processes._RETAINED) == before
    finally:
        for pid in set(processes._RETAINED) - before:
            processes.recover_session(pid)


def test_test002_interruption_before_reap_retains_exact_lease():
    before = set(processes._RETAINED)
    try:
        with patch.object(processes.subprocess.Popen, 'wait', side_effect=InterruptedError('before reap')):
            with pytest.raises(RuntimeError, match='recovery'):
                with open_session([sys.executable, '-c', 'pass']):
                    pass
        retained = set(processes._RETAINED) - before
        assert len(retained) == 1
        pid = retained.pop().pid
        assert os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    finally:
        for pid in set(processes._RETAINED) - before:
            processes.recover_session(pid)


def test_test002_recovery_tokens_never_alias_equal_numeric_pids():
    from articulous.process_contracts import RecoveryToken
    first = RecoveryToken(7, '/first')
    second = RecoveryToken(7, '/first')
    assert first != second
    assert len({first, second}) == 2


def test_test002_retry_failure_preserves_exact_recovery_token():
    before = set(processes._RETAINED)
    try:
        with patch.object(processes, 'await_group_exit', side_effect=TimeoutError('fence')):
            with pytest.raises(RuntimeError, match='recovery'):
                with open_session([sys.executable, '-c', 'pass']):
                    pass
            token = (set(processes._RETAINED) - before).pop()
            with pytest.raises(TimeoutError):
                processes.recover_session(token)
            assert token in processes._RETAINED
    finally:
        for token in set(processes._RETAINED) - before:
            processes.recover_session(token)


def test_test002_recovery_settles_closed_native_state_despite_decode_error():
    before = set(processes._RETAINED)
    try:
        with patch.object(processes, 'await_group_exit', side_effect=TimeoutError('fence')):
            with pytest.raises(RuntimeError, match='recovery'):
                with open_session([sys.executable, '-c', 'import os;os.write(1,bytes([255]))']) as session:
                    session.communicate()
        token = (set(processes._RETAINED) - before).pop()
        with pytest.raises(UnicodeDecodeError):
            processes.recover_session(token)
        assert token not in processes._RETAINED
    finally:
        for token in set(processes._RETAINED) - before:
            processes.recover_session(token)


def test_test002_missing_native_wait_evidence_cannot_release_workspace():
    before = set(processes._RETAINED)
    try:
        with patch.object(processes.subprocess.Popen, 'wait', return_value=None):
            with pytest.raises(RuntimeError, match='recovery'):
                with open_session([sys.executable, '-c', 'pass']):
                    pass
        assert len(set(processes._RETAINED) - before) == 1
    finally:
        for token in set(processes._RETAINED) - before:
            processes.recover_session(token)


@pytest.mark.parametrize('diagnostic_error', [False, True])
def test_life005_interrupted_cleanup_preserves_exact_recovery_owner(tmp_path, diagnostic_error):
    from unittest.mock import Mock
    from articulous.process_contracts import RecoveryToken
    scratch, borrowed = tmp_path / 'native', tmp_path / 'borrowed'
    scratch.mkdir()
    borrowed.mkdir()
    token = RecoveryToken(7, str(scratch))
    reservation = processes.NativeRecovery(Mock(settled=True), Mock(),
        processes.WorkspaceReservation(scratch, processes.workspace_identity(scratch)),
        [processes.WorkspaceReservation(borrowed, processes.workspace_identity(borrowed))])
    cleanup = processes.cleanup_workspace
    def interrupted_cleanup(path, identity):
        if path == borrowed:
            raise KeyboardInterrupt
        cleanup(path, identity)
    processes._RETAINED[token] = reservation
    try:
        error = RuntimeError('diagnostics after native settlement') if diagnostic_error else None
        with patch.object(processes, 'finish_native', side_effect=error):
            with patch.object(processes, 'cleanup_workspace', side_effect=interrupted_cleanup):
                with pytest.raises(KeyboardInterrupt):
                    processes.recover_session(token)
        assert processes._RETAINED.get(token) is reservation, 'LIFE-005: interruption cannot orphan remaining cleanup obligations'
        assert borrowed.exists()
        processes.recover_session(token)
        assert not borrowed.exists() and token not in processes._RETAINED
    finally:
        processes._RETAINED.pop(token, None)
        cleanup(scratch, reservation.workspace.identity)
        cleanup(borrowed, reservation.borrowed[0].identity)
