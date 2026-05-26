"""Unit tests for articulous.config."""
import copy
import json
from pathlib import Path

import pytest

from articulous.config import (
    DEFAULT_CONFIG,
    apply_cli_overrides,
    deep_merge,
    load_or_create_config,
)


class FakeCLI:
    def __init__(self, force=False, verbose=False):
        self.force_full_build = force
        self.verbose = verbose


# --- deep_merge ---

def test_deep_merge_shallow():
    base = {"a": 1, "b": 2}
    deep_merge(base, {"b": 3, "c": 4})
    assert base == {"a": 1, "b": 3, "c": 4}


def test_deep_merge_recurses_into_nested_dicts():
    base = {"x": {"y": 1, "z": 2}}
    deep_merge(base, {"x": {"z": 99, "w": 7}})
    assert base == {"x": {"y": 1, "z": 99, "w": 7}}


def test_deep_merge_returns_base():
    base = {"a": 1}
    assert deep_merge(base, {"b": 2}) is base


def test_deep_merge_override_non_dict_into_dict():
    base = {"x": {"y": 1}}
    deep_merge(base, {"x": "scalar"})
    assert base == {"x": "scalar"}


# --- load_or_create_config ---

def test_load_or_create_config_missing_path_uses_default(tmp_path):
    cfg = load_or_create_config(tmp_path / "nope.json")
    assert cfg == DEFAULT_CONFIG
    assert cfg is not DEFAULT_CONFIG  # deep copy, not shared


def test_load_or_create_config_invalid_json_falls_back(tmp_path, caplog):
    p = tmp_path / "bad.json"
    p.write_text("not-json")
    with caplog.at_level("WARNING"):
        cfg = load_or_create_config(p)
    assert cfg == DEFAULT_CONFIG
    assert any("Invalid config JSON" in r.message for r in caplog.records)


def test_load_or_create_config_non_dict_falls_back(tmp_path, caplog):
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]")
    with caplog.at_level("WARNING"):
        cfg = load_or_create_config(p)
    assert cfg == DEFAULT_CONFIG
    assert any("not a JSON object" in r.message for r in caplog.records)


def test_load_or_create_config_scalar_falls_back(tmp_path, caplog):
    p = tmp_path / "scalar.json"
    p.write_text("42")
    with caplog.at_level("WARNING"):
        cfg = load_or_create_config(p)
    assert cfg == DEFAULT_CONFIG


def test_load_or_create_config_merges_user_overrides(tmp_path):
    p = tmp_path / "good.json"
    p.write_text(json.dumps({"site": {"site_name": "Custom"}}))
    cfg = load_or_create_config(p)
    assert cfg["site"]["site_name"] == "Custom"
    # default values still present
    assert cfg["site"]["base_url"] == DEFAULT_CONFIG["site"]["base_url"]


# --- apply_cli_overrides ---

def test_apply_cli_overrides_force_and_verbose(tmp_path):
    for sub in ("content", "output", "xsl", "assets"):
        (tmp_path / sub).mkdir()
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    apply_cli_overrides(cfg, FakeCLI(force=True, verbose=True), tmp_path)
    assert cfg["build"]["force_full_build"] is True
    assert cfg["logging"]["level"] == "DEBUG"


def test_apply_cli_overrides_resolves_paths(tmp_path):
    for sub in ("content", "output", "xsl", "assets"):
        (tmp_path / sub).mkdir()
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    apply_cli_overrides(cfg, FakeCLI(), tmp_path)
    assert cfg["paths"]["content_dir"] == str((tmp_path / "content").resolve())


def test_apply_cli_overrides_rejects_traversal(tmp_path):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["paths"]["content_dir"] = "../../etc"
    with pytest.raises(ValueError, match="outside project root"):
        apply_cli_overrides(cfg, FakeCLI(), tmp_path)


def test_apply_cli_overrides_rejects_absolute_outside_root(tmp_path):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["paths"]["content_dir"] = "/etc"
    with pytest.raises(ValueError):
        apply_cli_overrides(cfg, FakeCLI(), tmp_path)


def test_apply_cli_overrides_accepts_absolute_inside_root(tmp_path):
    inside = tmp_path / "mycontent"
    inside.mkdir()
    for sub in ("output", "xsl", "assets"):
        (tmp_path / sub).mkdir()
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["paths"]["content_dir"] = str(inside)
    apply_cli_overrides(cfg, FakeCLI(), tmp_path)
    assert Path(cfg["paths"]["content_dir"]) == inside.resolve()
