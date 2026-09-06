"""Generated writes use their original inode across path replacements."""
import os
import random

import pytest

from articulous.filesystem import StagedOutput, atomic_output


def _replace_stage(path, victim, kind):
    path.unlink()
    makers = {"symlink": lambda: path.symlink_to(victim),
              "hardlink": lambda: path.hardlink_to(victim),
              "fifo": lambda: os.mkfifo(path),
              "regular": lambda: path.write_text("replacement")}
    makers[kind]()


@pytest.mark.parametrize("seed", [2026, 0xC0FFEE])
def test_fuzz_staging_swaps_preserve_external_files(tmp_path, seed):
    kinds = ["symlink", "hardlink", "fifo", "regular"]
    random.Random(seed).shuffle(kinds)
    victim = tmp_path / "manual"
    victim.write_text("keep")
    for kind in kinds:
        target = tmp_path / "page"
        with pytest.raises(ValueError, match="staging file changed"):
            with atomic_output(target, generated=True) as staged:
                assert isinstance(staged, StagedOutput)
                _replace_stage(staged.path, victim, kind)
                staged.write_bytes(b"rendered")
        assert victim.read_text() == "keep"
        assert not target.exists()


@pytest.mark.parametrize("linked", [False, True])
def test_directory_swap_before_write_preserves_replacement(tmp_path, linked):
    output = tmp_path / "output"
    output.mkdir()
    moved = tmp_path / "moved"
    manual = tmp_path / "manual" if linked else output
    victim = None
    with pytest.raises(ValueError, match="symlink|directory changed"):
        with atomic_output(output / "page", generated=True) as staged:
            output.rename(moved)
            manual.mkdir()
            if linked:
                output.symlink_to(manual, target_is_directory=True)
            victim = manual / staged.name
            victim.write_text("keep")
            staged.write_text("rendered")
    assert victim is not None
    assert victim.read_text() == "keep"
    assert list(moved.iterdir()) == []


def test_descriptor_output_roundtrip_and_invalid_modes(tmp_path):
    target = tmp_path / "page"
    with atomic_output(target, generated=True) as staged:
        with pytest.raises(ValueError, match="only w and wb"):
            staged.open("r")
        staged.write_bytes(b"long prior content")
        staged.write_text("café")
    assert target.read_text() == "café"
