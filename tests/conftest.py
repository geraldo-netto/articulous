"""
Shared pytest helpers.

Two main fixtures:

* ``site_root`` — a per-test copy of the fixture site under
  ``tests/fixtures/site`` (content/, xsl/, assets/, config.json) in a
  fresh tmpdir, with cwd pointed at it for the duration of the test.
  Tests that need to invoke run_build end-to-end use this.

* ``run_sitegen`` — wrapper around ``./sitegen.py`` for the
  subprocess-style integration test. It runs from whatever cwd the
  caller set up (typically ``site_root``).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


FIXTURE_SITE = Path(__file__).parent / "fixtures" / "site"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SITEGEN = str(PROJECT_ROOT / "sitegen.py")


@pytest.fixture
def site_root(tmp_path, monkeypatch):
    """Copy of the fixture site in tmp_path; cwd points at it."""
    dest = tmp_path / "site"
    shutil.copytree(FIXTURE_SITE, dest)
    monkeypatch.chdir(dest)
    return dest


@pytest.fixture
def run_sitegen():
    """Invoke ./sitegen.py with the given extra args (cwd-sensitive)."""

    def _run(args, check=True):
        result = subprocess.run(
            [sys.executable, SITEGEN, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if check:
            assert result.returncode == 0, (
                f"sitegen failed: {' '.join(args)}\n"
                f"stderr:\n{result.stderr.decode()}"
            )
        return result

    return _run


def xml_files(root: Path) -> list:
    """List all XML article files under ``root`` (recursive)."""
    return list(root.rglob("*.xml"))
