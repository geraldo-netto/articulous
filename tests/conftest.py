"""
Shared test helpers.

Centralises the subprocess boilerplate every test would otherwise
re-implement: building the argv list, capturing stdout/stderr, and
asserting on the return code.
"""
import subprocess
from pathlib import Path

import pytest

SITEGEN = "./sitegen.py"


def _run(args, check=True):
    result = subprocess.run(
        [SITEGEN, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check:
        assert result.returncode == 0, (
            f"sitegen failed: {' '.join([SITEGEN, *args])}\n"
            f"stderr:\n{result.stderr.decode()}"
        )
    return result


@pytest.fixture
def run_sitegen():
    """
    Return a callable that invokes sitegen with the given extra args
    and asserts a clean exit (unless check=False is passed).
    """
    return _run


def xml_files(root: Path = Path("content")) -> list:
    """List all XML article files under ``root`` (recursive)."""
    return list(root.rglob("*.xml"))
