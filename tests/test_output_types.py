"""All cache states apply the same output file policy."""
import os
import random
import socket

import pytest

from articulous.runtime import should_rebuild


def _special_target(path, kind):
    if kind == "socket":
        with socket.socket(socket.AF_UNIX) as connection:
            connection.bind(str(path))
        return
    {"directory": path.mkdir, "fifo": lambda: os.mkfifo(path)}[kind]()


@pytest.mark.parametrize("seed", [2026, 0xC0FFEE])
def test_fuzz_nonregular_outputs_are_preserved(tmp_path, seed):
    rng = random.Random(seed)
    cases = [(kind, cache, force) for kind in ("directory", "fifo", "socket")
             for cache in ({}, {"page": ["old"]}, {"page": ["new"]}) for force in (False, True)]
    rng.shuffle(cases)
    for index, (kind, cache, force) in enumerate(cases):
        path = tmp_path / str(index)
        _special_target(path, kind)
        before = path.lstat()
        with pytest.raises(ValueError, match="must be a regular file"):
            should_rebuild("page", cache, ("new",), force, path)
        assert path.lstat() == before


@pytest.mark.parametrize("exists", [False, True])
@pytest.mark.parametrize("cache", [{}, {"page": ["old"]}, {"page": ["new"]}])
@pytest.mark.parametrize("force", [False, True])
def test_regular_and_missing_output_controls(tmp_path, exists, cache, force):
    path = tmp_path / "page"
    if exists:
        path.write_text("published")
    expected = force or not exists or cache.get("page") != ["new"]
    assert should_rebuild("page", cache, ("new",), force, path) is expected
