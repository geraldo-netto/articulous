"""TEST-002/REV-064/095/BUILD-012: real Node transport and source-lifetime controls."""
from pathlib import Path
from articulous.browser_process import run_browser

ROOT = Path(__file__).resolve().parent


def test_test002_cdp_failures_and_owned_profile_settlement():
    result = run_browser(['node', str(ROOT / 'tooling/browser-session-regressions.mjs')], timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_build012_native_sources_survive_context_destruction():
    result = run_browser(['node', str(ROOT / 'tooling/native-coverage-regressions.mjs')], timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_test002_native_node_function_counters(tmp_path, monkeypatch):
    from articulous.browser_process import run_owned
    reports = []
    bootstrap = ROOT / 'tooling/native-node-coverage.mjs'
    for name in ('browser-session', 'native-coverage'):
        report = tmp_path / (name + '.json')
        monkeypatch.setenv('ARTICULOUS_NODE_COVERAGE', str(report))
        result = run_owned(['node', '--import', str(bootstrap), str(ROOT / 'tooling' / (name + '-regressions.mjs'))])
        assert result.returncode == 0
        reports.append(str(report))
    result = run_owned(['node', str(ROOT / 'tooling/coverage-report.mjs'), *reports])
    assert 'percent' in result.stdout
