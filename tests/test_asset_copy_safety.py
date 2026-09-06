"""Asset copies reject unsafe paths at the actual I/O boundary."""
import os
import random
import stat
from pathlib import Path

import pytest

from articulous.cli import CliOptions, parse_cli_args
from articulous.config import apply_cli_overrides, load_or_create_config
from articulous.filesystem import copy_asset_file
from articulous.pipeline import run_build


def _replace(path, victim, kind):
    path.unlink(missing_ok=True)
    makers = {"symlink": lambda: path.symlink_to(victim),
              "hardlink": lambda: path.hardlink_to(victim),
              "fifo": lambda: os.mkfifo(path), "directory": path.mkdir}
    makers[kind]()


@pytest.mark.parametrize("seed", [2026, 0xC0FFEE])
def test_fuzz_copy_source_swaps_after_hashing(site_root, monkeypatch, seed):
    cli = CliOptions(parse_cli_args([]))
    config = load_or_create_config(site_root / "config.json")
    apply_cli_overrides(config, cli, site_root)
    victim = site_root.parent / "private.txt"
    victim.write_text("private content")
    kinds = ["symlink", "fifo", "directory"]
    random.Random(seed).shuffle(kinds)
    for kind in kinds:
        with monkeypatch.context() as patch:
            patch.setattr("articulous.pipeline.copy_asset_file", _swapped_copy(victim, kind))
            with pytest.raises((ValueError, OSError)):
                run_build(cli, config, site_root)
        source = site_root / "assets/style.css"
        _remove_entry(source)
        source.write_text("asset")
        assert victim.read_text() == "private content"
        assert not (site_root / "output/assets/style.css").exists()


def _swapped_copy(victim, kind):
    def copy(source, destination):
        _replace(source, victim, kind)
        copy_asset_file(source, destination)
    return copy


def _remove_entry(path):
    if path.is_dir() and not path.is_symlink():
        path.rmdir()
    else:
        path.unlink()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory"])
def test_destination_swapped_during_copy_preserves_victim(tmp_path, monkeypatch, kind):
    source, destination, victim = (tmp_path / name for name in ("source", "dest", "manual"))
    source.write_text("asset")
    victim.write_text("keep")
    import shutil
    original = shutil.copyfileobj
    def swap(input_file, output):
        _replace(destination, victim, kind)
        original(input_file, output)
    monkeypatch.setattr("articulous.filesystem.shutil.copyfileobj", swap)
    with pytest.raises((OSError, ValueError)):
        copy_asset_file(source, destination)
    assert victim.read_text() == "keep"


@pytest.mark.parametrize("role", ["source", "destination"])
def test_copy_rejects_symlinked_ancestors(tmp_path, role):
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "file").write_text("keep")
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    source = alias / "file" if role == "source" else actual / "file"
    destination = alias / "file" if role == "destination" else tmp_path / "copied"
    with pytest.raises((OSError, ValueError)):
        copy_asset_file(source, destination)
    assert (actual / "file").read_text() == "keep"


@pytest.mark.parametrize("existing", [False, True])
def test_copy_preserves_content_permissions_and_times(tmp_path, existing):
    source, destination = tmp_path / "source", tmp_path / "new/asset"
    source.write_bytes(b"asset\x00data")
    source.chmod(0o640)
    os.utime(source, ns=(1234567890000000000, 1234567890000000000))
    if existing:
        destination.parent.mkdir()
        destination.write_text("previous")
    copy_asset_file(source, destination)
    assert destination.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o640
    assert destination.stat().st_mtime_ns == source.stat().st_mtime_ns


def test_source_ancestor_swapped_while_opening_is_rejected(tmp_path, monkeypatch):
    parent = tmp_path / "source"
    parent.mkdir()
    (parent / "file").write_text("asset")
    victim = tmp_path / "manual"
    victim.mkdir()
    (victim / "file").write_text("keep")
    original = os.open
    def swap(path, flags, *args, **kwargs):
        if Path(path).name == "source":
            parent.rename(tmp_path / "moved")
            parent.symlink_to(victim, target_is_directory=True)
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", swap)
    with pytest.raises(OSError):
        copy_asset_file(parent / "file", tmp_path / "dest")
    assert not (tmp_path / "dest").exists()
