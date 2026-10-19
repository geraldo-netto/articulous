"""BUILD-013: checkpoints observe finite native suites without an aggregate kill cap."""

from contextlib import contextmanager
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from articulous import browser_process


@contextmanager
def session_scope(session):
    try:
        yield session
    finally:
        session.stop()


class BrowserProgress(unittest.TestCase):
    def test_build013_progressing_suite_survives_four_checkpoints(self):
        stages = [
            f"[BUILD-013] settled {index}: domain; assertions={index * 100}\n"
            for index in range(1, 5)
        ]
        outputs = ["".join(stages[:index]) for index in range(1, 5)]
        session = Mock(returncode=0)
        session.communicate.side_effect = [
            *(
                subprocess.TimeoutExpired(["native"], 30, stderr=value.encode())
                for value in outputs
            ),
            ('{"assertions":400}', outputs[-1]),
        ]
        messages = []
        with patch(
            "articulous.browser_process.open_session",
            return_value=session_scope(session),
        ):
            result = browser_process.run_browser_suite(
                ["native"], checkpoint=30, report=messages.append
            )
        self.assertEqual('{"assertions":400}', result.stdout)
        self.assertEqual(outputs[-1], result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertEqual(stages, [message + "\n" for message in messages])
        self.assertEqual(5, session.communicate.call_count)
        session.stop.assert_called_once()

    def test_build013_uncertain_progress_is_explicit_and_cancellation_cleans(self):
        session = Mock(returncode=None)
        session.communicate.side_effect = [
            subprocess.TimeoutExpired(["native"], 1, stderr=b"heartbeat\n"),
            subprocess.TimeoutExpired(["native"], 1, stderr=None),
            KeyboardInterrupt,
        ]
        messages = []
        with patch(
            "articulous.browser_process.open_session",
            return_value=session_scope(session),
        ):
            with self.assertRaises(KeyboardInterrupt):
                browser_process.run_browser_suite(
                    ["native"], checkpoint=1, report=messages.append
                )
        self.assertEqual(2, len(messages))
        self.assertTrue(
            all("no newly settled stage" in message for message in messages)
        )
        session.stop.assert_called_once()

    def test_build013_finite_child_retains_every_case_and_error_output(self):
        messages = []
        code = (
            "import time,sys\nfor index in range(4):\n"
            ' time.sleep(.03)\n print(f"[BUILD-013] settled {index+1}: case; assertions={index+1}",file=sys.stderr,flush=True)\n'
            'print("all four cases complete")\nsys.exit(7)'
        )
        result = browser_process.run_browser_suite(
            [sys.executable, "-c", code], checkpoint=0.01, report=messages.append
        )
        self.assertEqual(7, result.returncode)
        self.assertEqual("all four cases complete\n", result.stdout)
        self.assertEqual(4, result.stderr.count("settled"))
        self.assertTrue(messages)

    def test_build013_invalid_checkpoint_rejected_before_launch(self):
        for value in (None, False, 0, -1, float("nan"), float("inf"), "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                browser_process.run_browser_suite(["native"], checkpoint=value)
