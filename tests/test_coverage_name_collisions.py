"""REVIEW-031: native counters must distinguish every lexical callable."""
import json
import random
import sys

import pytest

from articulous.browser_process import run_browser_suite
from articulous.coverage_gate import check_report


NATIVE_REPORT = '''
from pathlib import Path
import sys
from coverage import Coverage
path = Path(sys.argv[1])
coverage = Coverage(config_file=False, data_file=None, branch=True, source=[str(path.parent)])
coverage.start()
exec(compile(path.read_text(), str(path), 'exec'), {})
coverage.stop()
coverage.json_report(outfile=sys.argv[2])
'''

SOURCES = {
    'property': ('class Item:\n    @property\n    def value(self):\n        return 7\n'
                 '    @value.setter\n    def value(self, value):\n        self.stored = value\n'
                 'item = Item()\nitem.value = 4\n'),
    'repeated': 'def work():\n    return 1\ndef work():\n    return 2\nwork()\n',
    'conditional': ('if False:\n    def work():\n        return 1\n'
                    'else:\n    def work():\n        return 2\nwork()\n'),
}


def native_report(root, source):
    directory = root / 'code'
    directory.mkdir(exist_ok=True)
    path = directory / 'example.py'
    path.write_text(source)
    report_path = root / 'native.json'
    result = run_browser_suite([sys.executable, '-c', NATIVE_REPORT, str(path), str(report_path)], tooling=False)
    result.check_returncode()
    data = json.loads(report_path.read_text())
    entry = next(iter(data['files'].values()))
    return {'files': {'code/example.py': entry}}, entry


@pytest.mark.parametrize('kind', list(SOURCES))
def test_review031_ambiguous_native_names_are_rejected(tmp_path, kind):
    report, entry = native_report(tmp_path, SOURCES[kind])
    assert entry['missing_lines']
    count, failures = check_report(tmp_path, ['code'], report)
    assert count == 0
    assert len(failures) == 1 and 'Ambiguous callable names' in failures[0]


def test_review031_distinct_property_accessors_keep_native_coverage(tmp_path):
    source = ('class Item:\n    def get_value(self):\n        return self.stored\n'
              '    def set_value(self, value):\n        self.stored = value\n'
              '    value = property(get_value, set_value)\n'
              'item = Item()\nitem.value = 4\nassert item.value == 4\n')
    report, entry = native_report(tmp_path, source)
    assert entry['missing_lines'] == []
    assert check_report(tmp_path, ['code'], report) == (2, [])


def test_review031_seeded_duplicate_names_fail_before_counter_admission(tmp_path):
    randomizer = random.Random(31)
    directory = tmp_path / 'code'
    directory.mkdir()
    for _ in range(32):
        name = 'work_' + ''.join(randomizer.choice('abc_xyz') for _ in range(16))
        source = f'def {name}():\n    return 1\ndef {name}():\n    return 2\n'
        (directory / 'example.py').write_text(source)
        count, failures = check_report(tmp_path, ['code'], {})
        assert count == 0
        assert len(failures) == 1 and 'Ambiguous callable names' in failures[0]
