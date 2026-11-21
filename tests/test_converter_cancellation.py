"""TEST-002: converter cancellation fences descendants before releasing image scratch."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
import pytest
from articulous.backends.imagemagick import ImageMagick
from articulous.backends.processes import LinuxSession

CONVERTER = '''import json, os, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
Path(os.environ['CONVERTER_RECORD']).write_text(json.dumps({'parent':os.getpid(), 'child':child.pid}))
print('ready', flush=True)
time.sleep(60)
'''


def ready(session, record, communicate):
    deadline = time.monotonic() + 5
    while not record.exists():
        try:
            communicate(session, .01)
            raise AssertionError('Converter exited before ready')
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                raise AssertionError('Converter did not report ready')


def test_test002_converter_cancellation_settles_before_workspace_release(tmp_path):
    executable = tmp_path / 'convert'
    executable.write_text('#!' + sys.executable + '\n' + CONVERTER)
    executable.chmod(0o700)
    record = tmp_path / 'processes.json'
    communicate = LinuxSession.communicate
    interrupted = False
    def interrupt(session, timeout=None):
        nonlocal interrupted
        if not interrupted:
            ready(session, record, communicate)
            interrupted = True
            raise KeyboardInterrupt
        return communicate(session, timeout)
    backend = ImageMagick()
    with backend.workspace() as workspace:
        with patch.dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ['PATH'], CONVERTER_RECORD=str(record)):
            with patch.object(LinuxSession, 'communicate', interrupt), pytest.raises(KeyboardInterrupt):
                backend.shrink(tmp_path / 'source.jpg', workspace / 'target.jpg', 4, 82)
        processes = json.loads(record.read_text())
        for pid in processes.values():
            path = Path(f'/proc/{pid}/stat')
            assert not path.exists() or path.read_text().rpartition(') ')[2][0] == 'Z'
        assert workspace.exists()
    assert not workspace.exists()


def test_life004_unknown_converter_fence_retains_borrowed_workspace(tmp_path):
    from articulous.backends import processes
    executable = tmp_path / 'convert'
    executable.write_text('#!' + sys.executable + '\npass\n')
    executable.chmod(0o700)
    before = set(processes._RETAINED)
    workspace = None
    try:
        with patch.dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ['PATH']):
            with patch.object(processes, 'await_group_exit', side_effect=TimeoutError('missing native fence')):
                with pytest.raises(RuntimeError, match='recovery'):
                    with ImageMagick().workspace() as workspace:
                        ImageMagick().shrink(tmp_path / 'source.jpg', workspace / 'target.jpg', 4, 82)
            assert workspace is not None and workspace.exists(), 'LIFE-004: a borrowed target workspace stays funded until native quiescence'
        token = (set(processes._RETAINED) - before).pop()
        processes.recover_session(token)
        assert workspace is not None and not workspace.exists()
    finally:
        for token in set(processes._RETAINED) - before:
            processes.recover_session(token)


def test_review28_32_life004_failed_handoff_keeps_token_and_manual_workspace(tmp_path):
    from articulous.process_contracts import NativeCleanupError
    from articulous.backends import processes
    from articulous.backends import imagemagick
    from articulous.source_files import cleanup_workspace, workspace_identity
    executable = tmp_path / 'convert'
    executable.write_text('#!' + sys.executable + '\npass\n')
    executable.chmod(0o700)
    before = set(processes._RETAINED)
    workspace, identity = None, None
    defer = imagemagick.defer_workspace_cleanup
    def fail_target_handoff(token, path, expected):
        if path == workspace:
            raise OSError('handoff')
        defer(token, path, expected)
    try:
        with patch.dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ['PATH']):
            with patch.object(processes, 'await_group_exit', side_effect=TimeoutError('missing fence')):
                with patch.object(imagemagick, 'defer_workspace_cleanup', side_effect=fail_target_handoff):
                    with pytest.raises(NativeCleanupError, match='manual recovery') as retained:
                        with ImageMagick().workspace() as workspace:
                            identity = workspace_identity(workspace)
                            ImageMagick().shrink(tmp_path / 'source.jpg', workspace / 'target.jpg', 4, 82)
        assert workspace is not None and workspace.exists()
        assert retained.value.token in processes._RETAINED
        assert retained.value.__notes__ == [f'Image workspace requires manual recovery: {workspace}']
        assert isinstance(retained.value.__cause__, OSError)
        processes.recover_session(retained.value.token)
        assert retained.value.token not in processes._RETAINED
        assert workspace_identity(workspace) == identity
    finally:
        for token in set(processes._RETAINED) - before:
            processes.recover_session(token)
        if workspace is not None and identity is not None:
            cleanup_workspace(workspace, identity)


def test_review28_31_literal_aliases_survive_unsettled_native_session(tmp_path):
    from articulous.backends import processes
    from articulous.process_contracts import NativeCleanupError

    tool = tmp_path / 'convert'
    tool.write_text('#!' + sys.executable + '\npass\n')
    tool.chmod(0o700)
    before = set(processes._RETAINED)
    source = tmp_path / 'source%d.jpg'
    target_root, target = None, None
    try:
        with patch.dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ['PATH']):
            with patch.object(processes, 'await_group_exit', side_effect=TimeoutError('missing fence')):
                with pytest.raises(NativeCleanupError) as retained:
                    with ImageMagick().workspace() as target_root:
                        target = target_root / 'target%d.jpg'
                        ImageMagick().shrink(source, target, 4, 82)
        pending = processes._RETAINED[retained.value.token].borrowed
        aliases, output = pending
        assert target_root is not None and target is not None
        assert output.path == target_root
        assert {path.readlink() for path in aliases.path.iterdir()} == {source, target}
        processes.recover_session(retained.value.token)
        assert not aliases.path.exists() and not output.path.exists()
    finally:
        for token in set(processes._RETAINED) - before:
            processes.recover_session(token)
