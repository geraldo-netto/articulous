"""THEME-002: optional resource bytes and a neutral native-JS consumer."""
from pathlib import Path
from articulous.browser_process import run_owned
from articulous.theme_resources import search_resources

ROOT = Path(__file__).resolve().parent


def test_theme002_native_consumer_and_function_counters(tmp_path, monkeypatch):
    resources = search_resources()
    assert len(resources) == 1
    source = tmp_path / 'search-client.js'
    source.write_bytes(resources[0].content)
    counters = tmp_path / 'counters.json'
    monkeypatch.setenv('ARTICULOUS_SEARCH_CLIENT', source.as_uri())
    monkeypatch.setenv('ARTICULOUS_NODE_COVERAGE', str(counters))
    run_owned(['node', '--import', str(ROOT / 'tooling/native-node-coverage.mjs'), str(ROOT / 'tooling/search-client-regressions.mjs')])
    result = run_owned(['node', str(ROOT / 'tooling/search-coverage-report.mjs'), str(counters)])
    assert 'percent' in result.stdout
