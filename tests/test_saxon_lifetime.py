"""REVIEW-020: native descendants settle before output or input ownership retires."""
import json
from pathlib import Path
import sys

import pytest

from articulous.browser_process import run_owned


@pytest.mark.parametrize('mode', ['success', 'failure', 'cancel'])
@pytest.mark.parametrize('stdio', ['keep', 'close'])
def test_review020_saxon_settles_descendants_before_return(tmp_path, mode, stdio):
    tooling = Path(__file__).parent / 'tooling'
    result = run_owned([sys.executable, '-c', (tooling / 'saxon-lifetime.py').read_text(),
                        str(tmp_path), mode, str(tooling / 'saxon-descendant.py'), stdio], tooling=False)
    observation = json.loads(result.stdout)
    assert observation['alive'] is False
    assert observation['late_read'] is False
    assert observation['before'] == observation['after']
    assert observation['after'] == ('initial' if mode == 'success' else 'previous')
