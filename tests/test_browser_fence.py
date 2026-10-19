"""TEST-002: generation-bound pidfds and bounded native quiescence evidence."""
import os
import signal
import sys
import time
from unittest.mock import patch
import pytest
from articulous.backends import browser_fence as fence
from articulous.backends.processes import LinuxSession, open_session


def test_test002_proc_identity_and_members(tmp_path):
    absent = tmp_path / '10'
    foreign = tmp_path / '11'
    zombie = tmp_path / '12'
    live = tmp_path / '13'
    root = tmp_path / '42'
    with patch.object(fence.Path, 'glob', return_value=[absent, foreign, zombie, live, root]):
        with patch.object(fence, 'process_identity', side_effect=[None, (8, 1, 'S'), (42, 2, 'Z'), (42, 3, 'S')]):
            assert list(fence.owned_members(42)) == [(13, (42, 3, 'S'))]
    with patch.object(fence.Path, 'read_text', side_effect=FileNotFoundError):
        assert fence.process_identity(123) is None
    with patch.object(fence.Path, 'read_text', return_value='13 (name (inside)) S 1 42 ' + '0 ' * 16 + '99 0'):
        assert fence.process_identity(13) == (42, 99, 'S')


def test_test002_real_pidfd_generation_and_exit():
    with open_session([sys.executable, '-c', 'print("ready")']) as session:
        assert isinstance(session, LinuxSession)
        pid = session._process.pid
        expected = fence.process_identity(pid)
        assert expected is not None
        descriptor = fence.admit_member(pid, expected)
        assert descriptor is not None
        try:
            fence.signal_member(descriptor, signal.SIGCONT)
            assert session.communicate(2) == ('ready\n', '')
            fence.await_members({(pid, expected[1]): descriptor}, time.monotonic() + 1)
        finally:
            os.close(descriptor)
        changed = expected[0], expected[1] + 1, expected[2]
        assert fence.admit_member(pid, changed) is None
    with patch.object(fence, 'open_pidfd', side_effect=ProcessLookupError):
        assert fence.admit_member(pid, expected) is None
    with patch.object(fence, 'send_signal', side_effect=ProcessLookupError):
        fence.signal_member(-1, signal.SIGCONT)


def test_test002_collect_once_and_reject_unknown_identity():
    handles = {(7, 1): 70}
    members = [(7, (42, 1, 'S')), (8, (42, 2, 'S')), (9, (42, 3, 'S'))]
    with patch.object(fence.select, 'select', return_value=([], [], [])), patch.object(fence, 'owned_members', return_value=iter(members)), patch.object(fence, 'admit_member', side_effect=[None, 90]), patch.object(fence, 'signal_member') as sent:
        assert fence.collect_members(42, handles, signal.SIGSTOP)
        assert handles == {(7, 1): 70, (9, 3): 90}
        sent.assert_called_once_with(90, signal.SIGSTOP)
    with patch.object(fence, 'process_identity', return_value=(42, 1, 'S')):
        assert not fence.stopped_members({(7, 1): 70})
    for identity in [None, (42, 2, 'S'), (42, 1, 'T')]:
        with patch.object(fence, 'process_identity', return_value=identity):
            assert fence.stopped_members({(7, 1): 70})


def test_test002_freeze_deadline_and_progress():
    with patch.object(fence, 'collect_members', return_value=True), patch.object(fence.time, 'monotonic', return_value=12):
        with pytest.raises(TimeoutError, match='admission'):
            fence.freeze_members(42, {}, 10)
    with patch.object(fence, 'collect_members', side_effect=[True, False]), patch.object(fence, 'stopped_members', return_value=True), patch.object(fence.time, 'monotonic', return_value=1), patch.object(fence.time, 'sleep') as sleep:
        fence.freeze_members(42, {}, 10)
        sleep.assert_called_once()
    with pytest.raises(TimeoutError, match='pidfds'):
        fence.await_members({(7, 1): -1}, time.monotonic() - 1)


@pytest.mark.parametrize('phase', ['terminate', 'fence'])
def test_test002_fence_control_and_descriptor_cleanup(phase):
    def collect(owner, handles, number):
        handles[(7, 1)] = 70
    with patch.object(fence.os, 'getppid', return_value=42), patch.object(fence.os, 'getpgrp', return_value=42), patch.object(fence.os, 'getsid', return_value=42):
        with patch.object(fence, 'collect_members', side_effect=collect), patch.object(fence, 'freeze_members', side_effect=collect), patch.object(fence, 'signal_member'), patch.object(fence, 'await_members'), patch.object(fence.os, 'close') as close:
            fence.fence_group(42, phase, 1)
            close.assert_called_once_with(70)


def test_test002_ownership_guard_and_cli():
    with pytest.raises(RuntimeError, match='isolated Linux'):
        fence.fence_group(-1, 'fence', 1)
    with patch.object(fence, 'fence_group') as invoke:
        fence.main(['42', 'fence', '1'])
        invoke.assert_called_once_with(42, 'fence', 1)
    with pytest.raises(SystemExit):
        fence.main(['42', 'fence', '0'])


def test_test002_invalid_phase_is_rejected_before_native_effect():
    with pytest.raises(ValueError, match='phase'):
        fence.fence_group(os.getppid(), 'unknown', 1)


def test_life003_retired_pidfd_cannot_hide_reused_membership_key():
    handles = {(7, 1): 70}
    with patch.object(fence, 'owned_members', return_value=iter([(7, (42, 1, 'T'))])):
        with patch.object(fence, 'admit_member', return_value=71), patch.object(fence, 'signal_member') as sent:
            with patch.object(fence.select, 'select', return_value=([70], [], [])), patch.object(fence.os, 'close'):
                assert fence.collect_members(42, handles, signal.SIGSTOP), 'LIFE-003: a retired descriptor must not conceal a new owned member'
                assert handles[(7, 1)] == 71
                sent.assert_called_once_with(71, signal.SIGSTOP)


def test_life003_failed_admission_requires_another_membership_scan():
    with patch.object(fence, 'owned_members', return_value=iter([(7, (42, 1, 'S'))])):
        with patch.object(fence, 'admit_member', return_value=None):
            assert fence.collect_members(42, {}, signal.SIGSTOP), 'LIFE-003: a raced member must force another scan'
