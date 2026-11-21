"""PERF-30: process-local workers and Linux CPU bandwidth boundaries."""
from unittest.mock import Mock

import pytest

from articulous import runtime
from articulous.backends import cpu_capacity as cpu


@pytest.mark.parametrize(('text', 'expected'), [
    ('max 100000', None), ('50000 100000', 1), ('100001 100000', 2),
    ('-1 100000', None), ('0 100000', None), ('100000 0', None),
    ('nan 100000', None), ('-1', None), ('2 3 4', None),
])
def test_perf30_bandwidth_bounds(tmp_path, text, expected):
    control = tmp_path / 'cpu.max'
    control.write_text(text)
    assert cpu._bandwidth(control) == expected


@pytest.mark.parametrize('manifest', ['0:://outside', '0::/a/../../x', '5:cpu:/slice'])
def test_perf30_invalid_cgroup_membership_is_ignored(tmp_path, manifest):
    membership = tmp_path / 'cgroup'
    membership.write_text(manifest)
    assert cpu._cgroup_path(membership) is None


def test_perf30_uses_tightest_quota_in_the_ancestry(tmp_path, monkeypatch):
    root = tmp_path / 'groups'
    leaf = root / 'slice/leaf'
    leaf.mkdir(parents=True)
    membership = tmp_path / 'cgroup'
    membership.write_text('4:cpu:/old\n0::/slice/leaf\n')
    (root / 'cpu.max').write_text('max 100000')
    (leaf.parent / 'cpu.max').write_text('140000 100000')
    (leaf / 'cpu.max').write_text('500000 100000')
    monkeypatch.setattr(cpu, '_CGROUP_ROOT', root)
    monkeypatch.setattr(cpu, '_CGROUP_MEMBERSHIP', membership)
    monkeypatch.setattr(cpu.sys, 'platform', 'linux')
    monkeypatch.setattr(cpu.os, 'cpu_count', Mock(return_value=32))
    monkeypatch.setattr(cpu.os, 'sched_getaffinity', Mock(return_value={0, 1, 2}), raising=False)
    assert cpu.available_cpus() == 2


def test_perf30_native_probe_falls_back_when_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(cpu, '_CGROUP_MEMBERSHIP', tmp_path / 'missing')
    monkeypatch.setattr(cpu.sys, 'platform', 'linux')
    monkeypatch.setattr(cpu.os, 'cpu_count', Mock(return_value=None))
    monkeypatch.setattr(cpu.os, 'sched_getaffinity', Mock(side_effect=OSError), raising=False)
    assert cpu.available_cpus() == 4


def test_perf30_portable_cpu_count_avoids_linux_probes(monkeypatch):
    monkeypatch.setattr(cpu.sys, 'platform', 'win32')
    monkeypatch.setattr(cpu.os, 'cpu_count', Mock(return_value=2))
    monkeypatch.setattr(cpu, '_affinity_count', Mock(side_effect=AssertionError))
    assert cpu.available_cpus() == 2


def test_perf30_direct_runtime_uses_cpu_provider(monkeypatch):
    monkeypatch.setattr(runtime, 'available_cpus', Mock(return_value=1))
    executor = Mock(wraps=runtime.ThreadPoolExecutor)
    monkeypatch.setattr(runtime, 'ThreadPoolExecutor', executor)
    assert runtime.run_parallel_tasks([str]) == ['']
    executor.assert_called_once_with(max_workers=1)
