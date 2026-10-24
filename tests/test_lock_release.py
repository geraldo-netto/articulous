"""Successful processes release metadata without replacing the lock inode."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from articulous.filesystem import lock_file


def test_successful_cli_builds_do_not_warn_about_recovery(site_root, run_sitegen):
    run_sitegen([])
    locks = list(site_root.glob("*.articulous.lock"))
    identities = {path: path.stat().st_ino for path in locks}
    result = run_sitegen([])
    assert b"Recovering" not in result.stdout + result.stderr
    assert len(locks) == 2
    assert all(path.read_bytes() == b"" for path in locks)
    assert {path: path.stat().st_ino for path in locks} == identities


def test_abandoned_process_still_reports_recovery(tmp_path, caplog):
    path = tmp_path / "build.lock"
    script = """
import os, sys
from pathlib import Path
from articulous.filesystem import lock_file
with lock_file(Path(sys.argv[1])):
    os._exit(0)
"""
    subprocess.run([sys.executable, "-c", script, str(path)], check=True,
                   cwd=Path(__file__).resolve().parents[1])
    with caplog.at_level("WARNING"), lock_file(path):
        assert "Recovering dead process build lock" in caplog.text
    assert path.read_bytes() == b""


def test_metadata_cleanup_failure_releases_os_lock(tmp_path, monkeypatch):
    path = tmp_path / "build.lock"
    with pytest.raises(OSError, match="cleanup failed"):
        with monkeypatch.context() as patch:
            with lock_file(path):
                patch.setattr(os, "fsync", _fail_sync)
    with lock_file(path):
        assert path.exists()


def _fail_sync(_fd):
    raise OSError("cleanup failed")


@pytest.mark.parametrize('body_failure', [False, True])
def test_review001_unlock_failure_closes_descriptor(tmp_path, body_failure):
    from unittest.mock import patch
    from articulous import filesystem as fs

    path = tmp_path / 'unlock.lock'
    descriptor = fs._acquire_lock(path, 3600)
    with patch.object(fs.os, 'close', wraps=os.close) as close:
        try:
            with pytest.raises(InterruptedError) as failure:
                with patch.object(fs, '_acquire_lock', return_value=descriptor):
                    with patch.object(fs.fcntl, 'flock', side_effect=InterruptedError('unlock')):
                        with lock_file(path):
                            if body_failure:
                                raise LookupError('body')
            close.assert_called_once_with(descriptor)
            if body_failure:
                assert isinstance(failure.value.__context__, LookupError)
        finally:
            if not close.called:
                os.close(descriptor)
    with lock_file(path):
        pass
