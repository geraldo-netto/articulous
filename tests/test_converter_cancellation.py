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
