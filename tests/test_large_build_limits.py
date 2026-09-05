"""Large valid integers must not overflow internal iterator windows."""
import json
import random
import sys

import pytest

from articulous.runtime import run_parallel_tasks


@pytest.mark.parametrize("limit", [sys.maxsize - 1, sys.maxsize, sys.maxsize + 1, 10**100])
def test_large_page_and_worker_limits_preserve_full_build(site_root, run_sitegen, limit):
    run_sitegen([])
    output = site_root / "output"
    before = {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    config_path = site_root / "config.json"
    config = json.loads(config_path.read_text())
    config["site"]["pagination"]["per_page"] = limit
    config["build"]["parallelism"] = limit
    config_path.write_text(json.dumps(config))
    run_sitegen(["--force"])
    after = {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    assert after == before


@pytest.mark.parametrize("seed", [0xB0A, 2026, 0xC0FFEE])
def test_fuzz_large_worker_limits_execute_available_tasks(seed):
    rng = random.Random(seed)
    for _ in range(10):
        limit = sys.maxsize + rng.getrandbits(rng.randint(1, 400))
        assert run_parallel_tasks([lambda: "done"], max_workers=limit) == ["done"]
