"""BUILD-009: forced deadlines stop owned descendants and remove owned profiles."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from articulous.browser_process import run_browser
from articulous.backends.processes import await_group_exit, group_running, open_session


TREE = """
import json, os, signal, subprocess, sys, tempfile, time
from pathlib import Path
if sys.argv[2] == 'stubborn':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, '-c',
    'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
profile = tempfile.mkdtemp(prefix='browser-timeout-fixture-')
Path(sys.argv[1]).write_text(json.dumps({'parent':os.getpid(), 'child':child.pid, 'profile':profile}))
print('ready', flush=True)
time.sleep(60)
"""


def running(pid):
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rpartition(") ")[2][0]
        return state != "Z"
    except FileNotFoundError:
        return False


def recover_fixture_failure():
    from articulous.process_contracts import NativeCleanupError
    from articulous.backends.processes import recover_session
    error = sys.exc_info()[1]
    if isinstance(error, NativeCleanupError):
        recover_session(error.token)


class BrowserProcess(unittest.TestCase):
    def test_build009_timeout_stops_owned_tree_and_keeps_unrelated_process(self):
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        try:
            for mode in ("cooperative", "stubborn"):
                with (
                    self.subTest(mode=mode),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    path = Path(directory) / "processes.json"
                    record = None
                    try:
                        with self.assertRaises(subprocess.TimeoutExpired) as caught:
                            run_browser(
                                [sys.executable, "-u", "-c", TREE, str(path), mode],
                                timeout=1,
                            )
                        record = json.loads(path.read_text())
                        self.assertEqual(1, caught.exception.timeout)
                        self.assertIn("ready", str(caught.exception.output))
                        self.assertFalse(running(record["parent"]), record)
                        self.assertFalse(running(record["child"]), record)
                        self.assertFalse(Path(record["profile"]).exists(), record)
                        self.assertIsNone(unrelated.poll())
                    finally:
                        if record is None and path.exists():
                            record = json.loads(path.read_text())
                        if record is not None:
                            recover_fixture_failure()
        finally:
            unrelated.kill()
            unrelated.wait(timeout=5)

    def test_build009_normal_exit_preserves_output_and_cleans_scratch(self):
        code = 'import json,tempfile; p=tempfile.mkdtemp(prefix="browser-timeout-fixture-"); print(json.dumps({"profile":p})); print("diagnostic",file=__import__("sys").stderr)'
        result = run_browser([sys.executable, "-c", code], timeout=5)
        record = json.loads(result.stdout)
        try:
            self.assertEqual(0, result.returncode)
            self.assertEqual("diagnostic\n", result.stderr)
            self.assertFalse(Path(record["profile"]).exists())
        finally:
            shutil.rmtree(record["profile"], ignore_errors=True)

    def test_build009_bounded_invalid_requests_are_rejected_before_launch(self):
        for timeout in (
            None,
            False,
            True,
            0,
            -1,
            float("nan"),
            float("inf"),
            "1",
            2**10000,
        ):
            with self.subTest(timeout=repr(timeout)), self.assertRaises(ValueError):
                run_browser([sys.executable, "-c", "pass"], timeout=timeout)
        for command in (
            [],
            "/bin/true",
            b"/bin/true",
            [1],
            [""],
            [sys.executable, None],
            [sys.executable, "\x00"],
        ):
            with self.subTest(command=command), self.assertRaises(ValueError):
                run_browser(command, timeout=5)

    def test_build009_startup_failure_and_exception_cleanup(self):
        with self.assertRaises(FileNotFoundError):
            run_browser(["/nonexistent/morpha-browser"], timeout=5)
        session = None
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            with open_session(
                [sys.executable, "-c", "import time; time.sleep(60)"]
            ) as session:
                raise RuntimeError("cancelled")
        assert session is not None
        self.assertIsNotNone(session.returncode)

    def test_build009_unsupported_backend_is_explicit(self):
        for platform in ("win32", "darwin"):
            with (
                self.subTest(platform=platform),
                patch("articulous.backends.processes.sys.platform", platform),
            ):
                with self.assertRaisesRegex(NotImplementedError, "only on Linux"):
                    run_browser([sys.executable, "-c", "pass"], timeout=5)

    def test_build009_cleanup_wait_is_bounded(self):
        with patch("articulous.backends.processes.group_running", return_value=True):
            with patch(
                "articulous.backends.processes.time.monotonic", side_effect=[10, 12]
            ):
                with self.assertRaisesRegex(TimeoutError, "did not stop"):
                    await_group_exit(123456789)
        with patch(
            "articulous.backends.processes.group_running", side_effect=[True, False]
        ):
            with patch(
                "articulous.backends.processes.time.monotonic", side_effect=[10, 10.1]
            ):
                with patch("articulous.backends.processes.time.sleep") as sleep:
                    await_group_exit(123456789)
                    sleep.assert_called_once_with(0.01)

    def test_build009_group_state_handles_disappearing_processes_and_zombies(self):
        with tempfile.TemporaryDirectory() as directory:
            vanished = Path(directory) / "vanished"
            other = Path(directory) / "other"
            owned = Path(directory) / "owned"
            other.write_text("11 (other) S 1 24 24")
            owned.write_text("12 (owned (child)) Z 1 42 42")
            with patch(
                "articulous.backends.processes.Path.glob",
                return_value=[vanished, other, owned],
            ):
                self.assertFalse(group_running(42))
            owned.write_text("12 (owned (child)) S 1 42 42")
            with patch(
                "articulous.backends.processes.Path.glob", return_value=[other, owned]
            ):
                self.assertTrue(group_running(42))
