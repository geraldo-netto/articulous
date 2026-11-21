"""
Shared pytest helpers.

Two main fixtures:

* ``site_root`` — a per-test copy of the fixture site under
  ``tests/fixtures/site`` (content/, xsl/, assets/, config.json) in a
  fresh tmpdir, with cwd pointed at it for the duration of the test.
  Tests that need to invoke run_build end-to-end use this.

* ``run_sitegen`` — wrapper around ``python -m articulous`` for the
  subprocess-style integration test. It runs from whatever cwd the
  caller set up (typically ``site_root``).
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from articulous.tree_entries import tree_entries
from articulous.cli import CliOptions, parse_cli_args
from articulous.config import apply_cli_overrides, load_or_create_config
from articulous.filesystem import TempWorkspace


FIXTURE_SITE = Path(__file__).parent / "fixtures" / "site"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cache_clock(monkeypatch):
    seconds = [2_000_000_000]

    def now():
        return seconds[0] * 1_000_000_000
    monkeypatch.setattr(time, 'time_ns', now)
    return seconds


@pytest.fixture
def projection_workspace_cleanup(monkeypatch):
    original = TempWorkspace.named_file
    with ExitStack() as cleanup:
        def managed_file(workspace, *args, **kwargs):
            file = original(workspace, *args, **kwargs)
            cleanup.callback(Path(file.name).unlink, missing_ok=True)
            cleanup.callback(file.close)
            return file
        monkeypatch.setattr(TempWorkspace, "named_file", managed_file)
        yield


@pytest.fixture
def site_root(tmp_path, monkeypatch):
    """Copy of the fixture site in tmp_path; cwd points at it."""
    dest = tmp_path / "site"
    shutil.copytree(FIXTURE_SITE, dest)
    monkeypatch.chdir(dest)
    return dest


@pytest.fixture
def run_sitegen(monkeypatch):
    """Run this checkout as a module from the caller's site directory."""
    monkeypatch.setenv("PYTHONPATH", str(PROJECT_ROOT), prepend=os.pathsep)

    def _run(args, check=True, *, timeout=None):
        result = subprocess.run(
            [sys.executable, "-m", "articulous", *args],
            timeout=timeout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if check:
            assert result.returncode == 0, (
                f"articulous failed: {' '.join(args)}\n"
                f"stderr:\n{result.stderr.decode()}"
            )
        return result

    return _run


def xml_files(root: Path) -> list:
    """List all XML article files under ``root`` (recursive)."""
    return list(root.rglob("*.xml"))


@pytest.fixture
def seo_config(site_root):
    cli = CliOptions(parse_cli_args([]))
    config = load_or_create_config(site_root / "config.json")
    apply_cli_overrides(config, cli, site_root)
    return cli, config


def pytest_sessionstart(session):
    session.config.stash[SOURCE_DIGESTS] = {
        path: sha256(path.read_bytes()).hexdigest() for path in tree_entries(PROJECT_ROOT / 'articulous')
        if path.suffix == '.py'
    }


SOURCE_DIGESTS = pytest.StashKey[dict]()


def _bind_coverage(report_path, output, sources):
    report = json.loads(report_path.read_bytes())
    for name, entry in report['files'].items():
        path = Path(name).resolve()
        if path in sources:
            entry['source_sha256'] = sources[path]
    report_path.write_text(json.dumps(report))
    report_path.replace(output)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtestloop(session):
    reports = session.config.getoption('cov_report', default={})
    if 'json' not in reports or session.config.getoption('no_cov', default=False):
        return (yield)
    original = reports['json']
    output = Path(original or 'coverage.json').resolve()
    output.parent.mkdir(exist_ok=True, parents=True)
    with TemporaryDirectory(dir=output.parent) as work:
        measured = Path(work) / 'coverage.json'
        reports['json'] = str(measured)
        try:
            result = yield
            if measured.exists():
                _bind_coverage(measured, output, session.config.stash[SOURCE_DIGESTS])
        finally:
            reports['json'] = original
        return result
