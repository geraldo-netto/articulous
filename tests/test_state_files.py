"""Regular-file requirements for configuration and build state."""
import json
import os
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from articulous.cli import setup_logging
from articulous.config import load_or_create_config
from articulous.filesystem import open_regular_file
from articulous.runtime import load_cache


def _make_socket(path):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.bind(str(path))


def _make_special(path, kind):
    makers = {"fifo": lambda: os.mkfifo(path), "directory": path.mkdir,
              "socket": lambda: _make_socket(path)}
    makers[kind]()


@pytest.mark.parametrize("role", ["config", "cache", "log"])
@pytest.mark.parametrize("kind", ["fifo", "directory", "socket"])
def test_cli_rejects_special_state_files_without_blocking(site_root, role, kind):
    config_path = site_root / "config.json"
    config = json.loads(config_path.read_text())
    config["logging"]["file"] = "build.log"
    config_path.write_text(json.dumps(config))
    paths = {"config": config_path, "cache": site_root / ".build-cache.json",
             "log": site_root / "build.log"}
    path = paths[role]
    path.unlink(missing_ok=True)
    _make_special(path, kind)
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "sitegen.py")],
        cwd=site_root, capture_output=True, text=True, timeout=5,
    )
    assert result.returncode != 0
    assert "must be a regular file" in result.stderr
    assert not (site_root / "output").exists()
    assert path.exists()


@pytest.mark.parametrize("loader", [load_or_create_config, load_cache])
@pytest.mark.parametrize("kind", ["fifo", "directory", "socket"])
def test_json_readers_reject_special_files(tmp_path, loader, kind):
    path = tmp_path / "input.json"
    _make_special(path, kind)
    with pytest.raises(ValueError, match="must be a regular file"):
        loader(path)


@pytest.mark.parametrize("loader", [load_or_create_config, load_cache])
def test_json_readers_accept_regular_symlink_targets(tmp_path, loader):
    target = tmp_path / "target.json"
    target.write_text('{"site": {"site_name": "Café"}}')
    link = tmp_path / "link.json"
    link.symlink_to(target)
    assert loader(link)["site"]["site_name"] == "Café"
    assert link.is_symlink()


@pytest.mark.parametrize("loader", [load_or_create_config, load_cache])
def test_json_readers_reject_symlink_to_device(tmp_path, loader):
    path = tmp_path / "device.json"
    path.symlink_to("/dev/null")
    with pytest.raises(ValueError, match="must be a regular file"):
        loader(path)


@pytest.mark.parametrize("kind", ["fifo", "directory", "socket"])
def test_logging_rejects_special_files(tmp_path, kind):
    path = tmp_path / "build.log"
    _make_special(path, kind)
    config = {"logging": {"level": "INFO", "file": path.name}}
    with pytest.raises(ValueError, match="must be a regular file"):
        setup_logging(config, tmp_path)


def test_logging_appends_to_regular_symlink_target(tmp_path):
    import logging
    target = tmp_path / "target.log"
    target.write_text("previous message\n")
    link = tmp_path / "build.log"
    link.symlink_to(target)
    setup_logging({"logging": {"level": "INFO", "file": link.name}}, tmp_path)
    logging.info("next message")
    setup_logging({"logging": {"level": "INFO", "file": None}}, tmp_path)
    assert target.read_text().startswith("previous message\n")
    assert "next message" in target.read_text()
    assert link.is_symlink()


def test_regular_reader_rejects_file_swapped_after_validation(tmp_path, monkeypatch):
    path = tmp_path / "input.json"
    path.write_text("{}")
    original_open = os.open
    descriptors = []

    def swap_and_open(filename, flags, mode):
        assert flags & os.O_NONBLOCK
        path.unlink()
        os.mkfifo(path)
        fd = original_open(filename, flags, mode)
        descriptors.append(fd)
        return fd

    monkeypatch.setattr(os, "open", swap_and_open)
    with pytest.raises(ValueError, match="Opened path must be a regular file"):
        with open_regular_file(path):
            pytest.fail("Special file accepted")
    assert stat.S_ISFIFO(path.stat().st_mode)
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
