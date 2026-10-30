"""WIRING-001 / CODE-017: exact public resources provide a working VB.NET grammar."""
import json
from pathlib import Path
from articulous.browser_process import run_browser_suite
from articulous.theme_resources import code_resources


def test_wiring001_vbnet_dependency_tokens_and_fault_control(tmp_path):
    resources = {item.path: item.content.decode() for item in code_resources()}
    names = ['core', 'basic', 'vbnet']
    payload = [resources['assets/vendor/prism/prism-' + name + '.js'] for name in names]
    path = tmp_path / 'resources.json'
    path.write_text(json.dumps(payload))
    script = Path(__file__).parent / 'tooling/vbnet-regression.mjs'
    result = run_browser_suite(['node', str(script), str(path)])
    assert result.returncode == 0, result.stdout + result.stderr
