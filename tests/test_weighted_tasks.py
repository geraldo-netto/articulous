"""PERF-21: admitted payload budget, exclusivity and failure settlement."""
from itertools import repeat
import sys

import pytest

from articulous import runtime


@pytest.mark.parametrize('value', [0, -1, True, 'byte', 1.5])
def test_perf21_budget_rejects_invalid_capacity(value):
    with pytest.raises(ValueError, match='input budget'):
        runtime.run_parallel_tasks([str], 1, max_inflight_bytes=value)


@pytest.mark.parametrize('value', [-1, True, 'byte', 1.5, None])
def test_perf21_charge_rejects_invalid_size(value):
    with pytest.raises(ValueError, match='input charge'):
        runtime.WeightedTask(value, str)


def test_perf21_oversized_and_pending_charges_are_funded():
    jobs = [runtime.WeightedTask(charge, str) for charge in (4, 4, sys.maxsize**2, 0, 8, 1)]
    admission = runtime._TaskAdmission(iter(jobs), 8, 8)
    with runtime.ThreadPoolExecutor(max_workers=2) as pool:
        for expected in ((4, 4), (sys.maxsize**2,), (0, 8), (1,)):
            admission.fill(pool)
            assert tuple(admission.pending.values()) == expected
            for future in admission.pending:
                assert future.result() == ''
            admission.settle(tuple(admission.pending))
            assert admission.cost == 0
        admission.fill(pool)
        assert not admission.pending


def test_perf21_failure_does_not_admit_deferred_payload():
    def failed():
        raise OSError('weighted job failed')

    def unexpected():
        pytest.fail('deferred job started after failure')

    jobs = [runtime.WeightedTask(8, failed), runtime.WeightedTask(8, unexpected)]
    with pytest.raises(OSError, match='weighted job failed'):
        runtime.run_parallel_tasks(jobs, max_workers=4, max_inflight_bytes=8)


def test_perf21_regular_callables_have_no_payload_charge():
    assert runtime.run_parallel_tasks(repeat(str, 4), 2, max_inflight_bytes=1) == [''] * 4
