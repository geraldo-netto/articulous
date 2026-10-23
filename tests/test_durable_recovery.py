"""LIFE-002: durable reservations survive loss of their Python owner."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from unittest.mock import patch

import pytest

from articulous.backends import processes
from articulous.source_files import cleanup_workspace, workspace_identity


OWNER = '''
import json, os, signal, sys
from pathlib import Path
from unittest.mock import patch
from articulous.backends import processes
from articulous.process_contracts import NativeCleanupError
command = 'import time; time.sleep(600)'
if sys.argv[3] == 'descendant':
    command = 'import subprocess,sys; subprocess.Popen([sys.executable,"-c","import time;time.sleep(600)"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)'
try:
    with patch.object(processes, 'finish_native', side_effect=RuntimeError('lost fence')):
        with processes.open_session([sys.executable, '-c', command]) as session:
            if sys.argv[3] == 'descendant':
                session.communicate()
except NativeCleanupError as error:
    borrowed = Path(sys.argv[2])
    processes.defer_workspace_cleanup(error.token, borrowed, processes.workspace_identity(borrowed))
    Path(sys.argv[1]).write_text(json.dumps({'pid': error.token.pid, 'workspace': error.token.workspace}))
    os.kill(os.getpid(), signal.SIGKILL)
'''


def stop_orphan(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    processes.await_group_exit(pid)


@pytest.mark.parametrize('mode', ['leader', 'descendant'])
def test_life002_forced_owner_loss_keeps_live_native_and_borrowed_workspaces(tmp_path, mode):
    report = tmp_path / 'owner.json'
    borrowed = tmp_path / 'borrowed'
    borrowed.mkdir()
    result = subprocess.run([sys.executable, '-c', OWNER, str(report), str(borrowed), mode],
                            capture_output=True, text=True)
    assert result.returncode == -signal.SIGKILL, result.stderr
    info = json.loads(report.read_text())
    scratch = Path(info['workspace'])
    identity = workspace_identity(scratch)
    journal = scratch.with_name(scratch.name + '.recovery.json')
    try:
        assert journal.exists(), 'LIFE-002: retained native ownership must have a durable handoff'
        with pytest.raises(RuntimeError, match='live'):
            processes.recover_orphan(journal)
        assert scratch.exists() and borrowed.exists() and journal.exists()
        stop_orphan(info['pid'])
        processes.recover_orphan(journal)
        assert not scratch.exists() and not borrowed.exists() and not journal.exists()
    finally:
        stop_orphan(info['pid'])
        cleanup_workspace(scratch, identity)
        journal.unlink(missing_ok=True)


def test_life002_live_owner_cannot_be_claimed():
    before = set(processes._RETAINED)
    try:
        with patch.object(processes, 'await_group_exit', side_effect=TimeoutError('fence')):
            with pytest.raises(RuntimeError, match='recovery'):
                with processes.open_session([sys.executable, '-c', 'pass']):
                    pass
        token = (set(processes._RETAINED) - before).pop()
        journal = Path(token.workspace + '.recovery.json')
        assert journal.exists(), 'LIFE-002: the durable record must precede handoff'
        with pytest.raises(RuntimeError, match='owner'):
            processes.recover_orphan(journal)
    finally:
        for token in set(processes._RETAINED) - before:
            processes.recover_session(token)


def test_life002_failed_cleanup_keeps_durable_reservation():
    before = set(processes._RETAINED)
    reservation = None
    token = None
    try:
        with patch.object(processes, 'await_group_exit', side_effect=TimeoutError('fence')):
            with pytest.raises(RuntimeError, match='recovery'):
                with processes.open_session([sys.executable, '-c', 'pass']):
                    pass
        token = (set(processes._RETAINED) - before).pop()
        reservation = processes._RETAINED[token]
        with patch.object(processes, 'cleanup_workspace'):
            with pytest.raises(RuntimeError, match='cleanup'):
                processes.recover_session(token)
        assert token in processes._RETAINED
        assert Path(token.workspace + '.recovery.json').exists()
    finally:
        if reservation is not None and reservation.workspace.path.exists():
            assert token is not None
            processes._RETAINED.setdefault(token, reservation)
        for token in set(processes._RETAINED) - before:
            processes.recover_session(token)
