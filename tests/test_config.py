"""Unit tests for articulous.config."""
import copy
import json
import os
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
        self.config_path = Path("config.json")


def test_log_cannot_alias_cache_lock(tmp_path):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["logging"]["file"] = "..build-cache.json.articulous.lock"
    with pytest.raises(ValueError, match="alias each other"):
        apply_cli_overrides(config, FakeCLI(), tmp_path)


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
    invalid = cast(dict, [])
    with pytest.raises(ValueError, match="root must be an object"):
        validate_config(invalid)


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


@pytest.mark.parametrize("language", [
    "en?query", "en#fragment", "en/fr", "en\\fr", ".", "..", "../en",
    "%2e%2e", "en:us", "en us", "en\n", "en\x7f", "français",
])
def test_validate_config_rejects_unsafe_language_segments(language):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["site"].update(languages=[language], default_language=language)
    with pytest.raises(ValueError, match="site.languages.*ASCII"):
        validate_config(config)


@pytest.mark.parametrize("language", ["en", "pt-BR", "zh-Hant", "es-419", "en_US"])
def test_validate_config_accepts_safe_language_segments(language):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["site"].update(languages=[language], default_language=language)
    validate_config(config)


@pytest.mark.parametrize("pattern", [
    "/feed.xml?format=rss", "/feed.xml#section", "/my%20feed.xml",
    "/feed\\name.xml", "/feed\nname.xml", "/feed\x7fname.xml",
    "https://example.test/feed.xml", "//example.test/feed.xml",
])
def test_url_pattern_rejects_non_file_url_components(pattern):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["urls"]["rss"] = pattern
    with pytest.raises(ValueError, match="URL patterns"):
        validate_config(config)


@pytest.mark.parametrize("section", ["rss", "sitemap", "search"])
@pytest.mark.parametrize("ending", ["/", "//"])
def test_file_url_pattern_rejects_trailing_slashes(section, ending):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["urls"][section] += ending
    with pytest.raises(ValueError, match=rf"urls\.{section}.*file-style"):
        validate_config(config)


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


@pytest.mark.parametrize("source", ["content", "xsl", "assets"])
@pytest.mark.parametrize("output", ["{source}", "{source}/generated", "."])
def test_output_layout_rejects_source_overlap(tmp_path, source, output):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["paths"]["output_dir"] = output.format(source=source)
    with pytest.raises(ValueError, match="overlap"):
        apply_cli_overrides(cfg, FakeCLI(), tmp_path)
    assert list(tmp_path.iterdir()) == []


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


@pytest.mark.parametrize("kind", ["same", "symlink", "hardlink"])
def test_cache_cannot_alias_active_configuration(tmp_path, kind):
    source = tmp_path / "alternate.json"
    source.write_text("configuration")
    aliases = {"same": lambda: None, "symlink": lambda: (tmp_path / "cache.json").symlink_to(source),
               "hardlink": lambda: os.link(source, tmp_path / "cache.json")}
    aliases[kind]()
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["build"]["cache_file"] = source.name if kind == "same" else "cache.json"
    cli = FakeCLI()
    cli.config_path = source
    with pytest.raises(ValueError, match="aliases the configuration"):
        apply_cli_overrides(config, cli, tmp_path)
    assert source.read_text() == "configuration"


@pytest.mark.parametrize("log_file,message", [
    ("content/article.xml", "overlaps"), ("output/build.log", "overlaps"),
    ("../external.log", "outside project root"), (".build-cache.json", "alias each other"),
])
def test_build_state_paths_are_disjoint(tmp_path, log_file, message):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["logging"]["file"] = log_file
    with pytest.raises(ValueError, match=message):
        apply_cli_overrides(config, FakeCLI(), tmp_path)


@pytest.mark.parametrize("block, key", [("logging", "file"), ("build", "cache_file")])
def test_state_hardlinks_cannot_alias_source_inputs(tmp_path, block, key):
    source = tmp_path / "content/article.xml"
    source.parent.mkdir()
    source.write_text("<article/>")
    (tmp_path / "state").hardlink_to(source)
    config = copy.deepcopy(DEFAULT_CONFIG)
    config[block][key] = "state"
    with pytest.raises(ValueError, match="multiple hardlinks"):
        apply_cli_overrides(config, FakeCLI(), tmp_path)
    assert source.read_text() == "<article/>"
