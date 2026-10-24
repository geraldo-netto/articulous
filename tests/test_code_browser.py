"""REVIEW-009: native DOM lifecycle and complete maintained-code V8 coverage."""
import hashlib
import json
import os
from pathlib import Path
import shutil

from articulous.browser_process import run_browser_suite


def test_review009_native_code_and_clipboard_lifetimes(tmp_path, monkeypatch):
    executable = os.environ.get('ARTICULOUS_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome')
    assert executable, 'Native Chromium is required; set ARTICULOUS_CHROMIUM to an installed executable'
    report_path = tmp_path / 'browser-coverage.json'
    monkeypatch.setenv('ARTICULOUS_CHROMIUM', executable)
    monkeypatch.setenv('ARTICULOUS_CODE_COVERAGE', str(report_path))
    root = Path(__file__).resolve().parents[1]
    result = run_browser_suite(['node', str(root / 'tests/tooling/code-browser.mjs')])
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(report_path.read_text())
    assert set(report['cases']) == {
        'admission', 'normalization', 'success', 'rejection', 'defaultLabels', 'cutoffBeforeWrite',
        'detachedAdmission', 'movedWrapper', 'changedWrapperClass', 'staleTimer', 'initialization',
        'stale-success', 'stale-error', 'unsupported', 'missing-toolbar', 'missing-prism',
    }
    assert report['browser']['product']
    assert {row['file'] for row in report['coverage']} == set(report['sources'])
    assert all(row['percent'] >= 80 for row in report['coverage'])
    for name, expected in report['sources'].items():
        content = (root / 'articulous/theme_assets' / name.lstrip('/')).read_bytes()
        assert hashlib.sha256(content).hexdigest() == expected
