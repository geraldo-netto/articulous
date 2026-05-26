"""Unit tests for articulous.cli."""
import logging

import pytest

from articulous.cli import (
    CliOptions,
    _resolve_log_level,
    main,
    parse_cli_args,
    setup_logging,
)


# --- parse_cli_args + CliOptions ---

def test_parse_cli_args_defaults():
    args = parse_cli_args([])
    assert args.config == "config.json"
    assert args.only is None
    assert args.lang is None
    assert args.slug is None


def test_cli_options_defaults():
    cli = CliOptions(parse_cli_args([]))
    assert cli.only_sections is None
    assert cli.only_langs is None
    assert cli.only_slugs is None
    assert cli.dry_run is False
    assert cli.force_full_build is False
    assert cli.verbose is False


def test_cli_options_only_splits():
    cli = CliOptions(parse_cli_args(["--only", "articles, rss, , tags"]))
    assert cli.only_sections == ["articles", "rss", "tags"]


def test_cli_options_only_empty_string_means_none():
    cli = CliOptions(parse_cli_args(["--only", ""]))
    assert cli.only_sections is None


def test_cli_options_appendable_flags():
    cli = CliOptions(parse_cli_args(
        ["--lang", "en", "--lang", "fr", "--slug", "a", "--slug", "b"],
    ))
    assert cli.only_langs == ["en", "fr"]
    assert cli.only_slugs == ["a", "b"]


def test_cli_options_force_dry_verbose():
    cli = CliOptions(parse_cli_args(["--force", "--dry-run", "-v"]))
    assert cli.force_full_build is True
    assert cli.dry_run is True
    assert cli.verbose is True


# --- _resolve_log_level ---

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("DEBUG", logging.DEBUG),
        ("info", logging.INFO),
        ("warning", logging.WARNING),
        ("ERROR", logging.ERROR),
        ("CRITICAL", logging.CRITICAL),
    ],
)
def test_resolve_log_level_valid(raw, expected):
    assert _resolve_log_level(raw) == expected


def test_resolve_log_level_invalid_falls_back():
    assert _resolve_log_level("BOGUS") == logging.INFO


def test_resolve_log_level_none_falls_back():
    assert _resolve_log_level(None) == logging.INFO


# --- setup_logging ---

def test_setup_logging_idempotent(tmp_path):
    cfg = {"logging": {"level": "INFO", "file": None}}
    setup_logging(cfg, tmp_path)
    n1 = len(logging.getLogger().handlers)
    setup_logging(cfg, tmp_path)
    n2 = len(logging.getLogger().handlers)
    assert n1 == n2 == 1


def test_setup_logging_verbose_overrides(tmp_path):
    cfg = {"logging": {"level": "WARNING", "file": None}}
    setup_logging(cfg, tmp_path, verbose=True)
    assert logging.getLogger().level == logging.DEBUG


def test_setup_logging_adds_file_handler(tmp_path):
    log_file = tmp_path / "app.log"
    cfg = {"logging": {"level": "INFO", "file": log_file.name}}
    setup_logging(cfg, tmp_path)
    handlers = logging.getLogger().handlers
    assert any(isinstance(h, logging.FileHandler) for h in handlers)
    # close file handlers so tmp_path can be cleaned
    for h in list(handlers):
        if isinstance(h, logging.FileHandler):
            h.close()
            logging.getLogger().removeHandler(h)


# --- main ---

def test_main_invokes_run_build(monkeypatch, site_root):
    called = {}

    def fake_run_build(cli, cfg, project_root):
        called["cli"] = cli
        called["root"] = project_root

    monkeypatch.setattr("articulous.cli.run_build", fake_run_build)
    # site_root fixture has already chdir'd into the fixture site, so
    # Path.cwd() naturally returns it.
    main(["--force"])
    assert called["cli"].force_full_build is True
    assert called["root"] == site_root.resolve()
