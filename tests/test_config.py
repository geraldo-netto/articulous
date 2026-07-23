"""Unit tests for articulous.config."""
import copy
import json
from pathlib import Path
from typing import cast

import pytest

from articulous.config import (
    DEFAULT_CONFIG,
    apply_cli_overrides,
    deep_merge,
    load_or_create_config,
    validate_config,
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
    returned = deep_merge(base, {"b": 2})
    returned["c"] = 3
    assert base == {"a": 1, "b": 2, "c": 3}


def test_deep_merge_override_non_dict_into_dict():
    base = {"x": {"y": 1}}
    deep_merge(base, {"x": "scalar"})
    assert base == {"x": "scalar"}


# --- load_or_create_config ---

def test_load_or_create_config_missing_path_uses_default(tmp_path):
    path = tmp_path / "missing" / "config.json"
    cfg = load_or_create_config(path)
    assert cfg == DEFAULT_CONFIG
    assert cfg is not DEFAULT_CONFIG  # deep copy, not shared
    assert json.loads(path.read_text()) == DEFAULT_CONFIG


def test_load_or_create_config_invalid_json_fails_fast(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not-json")
    with pytest.raises(ValueError, match="Invalid config JSON"):
        load_or_create_config(p)


def test_load_or_create_config_non_dict_fails_fast(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]")
    with pytest.raises(ValueError, match="not a JSON object"):
        load_or_create_config(p)


def test_load_or_create_config_scalar_fails_fast(tmp_path):
    p = tmp_path / "scalar.json"
    p.write_text("42")
    with pytest.raises(ValueError, match="not a JSON object"):
        load_or_create_config(p)


def test_load_or_create_config_merges_user_overrides(tmp_path):
    p = tmp_path / "good.json"
    p.write_text(json.dumps({"site": {"site_name": "Custom"}}))
    cfg = load_or_create_config(p)
    assert cfg["site"]["site_name"] == "Custom"
    # default values still present
    assert cfg["site"]["base_url"] == DEFAULT_CONFIG["site"]["base_url"]


def test_load_or_create_config_rejects_invalid_schema(tmp_path):
    p = tmp_path / "bad-schema.json"
    p.write_text(json.dumps({"site": {"languages": ["en", "en"]}}))
    with pytest.raises(ValueError, match="duplicates"):
        load_or_create_config(p)


def _set_nested(config, path, value):
    target = config
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


@pytest.mark.parametrize(
    "path,value,message",
    [
        (("paths",), None, "paths must be an object"),
        (("paths", "content_dir"), "", "non-empty string"),
        (("engines",), {"articles": "lxml"}, "engines keys invalid"),
        (("saxonc", "home"), 7, "saxonc.home"),
        (("site", "site_name"), 7, "site.site_name"),
        (("site", "base_url"), 7, "site.base_url"),
        (("site", "languages"), ["en", "en"], "duplicates"),
        (("site", "pagination"), None, "site.pagination must be an object"),
        (("urls", "rss"), None, "urls.rss"),
        (("build", "cache_file"), "/", "contain a filename"),
        (("build", "force_full_build"), "false", "must be a boolean"),
        (("logging", "level"), "TRACE", "logging.level"),
        (("logging", "file"), 7, "logging.file"),
    ],
)
def test_validate_config_rejects_invalid_fields(path, value, message):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    _set_nested(cfg, path, value)
    with pytest.raises(ValueError, match=message):
        validate_config(cfg)


def test_validate_config_rejects_non_object_root():
    with pytest.raises(ValueError, match="root must be an object"):
        validate_config(cast(dict, []))


def test_validate_config_rejects_unknown_root_key():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["typo"] = True
    with pytest.raises(ValueError, match=r"unknown=\['typo'\]"):
        validate_config(cfg)


def test_validate_config_accepts_optional_strings():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["saxonc"]["home"] = "/opt/saxon"
    cfg["logging"]["level"] = "debug"
    cfg["logging"]["file"] = ""
    validate_config(cfg)


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
    cli = FakeCLI()
    with pytest.raises(ValueError, match="outside project root"):
        apply_cli_overrides(cfg, cli, tmp_path)


def test_apply_cli_overrides_rejects_absolute_outside_root(tmp_path):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["paths"]["content_dir"] = "/etc"
    cli = FakeCLI()
    with pytest.raises(ValueError):
        apply_cli_overrides(cfg, cli, tmp_path)


def test_apply_cli_overrides_accepts_absolute_inside_root(tmp_path):
    inside = tmp_path / "mycontent"
    inside.mkdir()
    for sub in ("output", "xsl", "assets"):
        (tmp_path / sub).mkdir()
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["paths"]["content_dir"] = str(inside)
    apply_cli_overrides(cfg, FakeCLI(), tmp_path)
    assert Path(cfg["paths"]["content_dir"]) == inside.resolve()
