"""Route changes remove only selected owned obstructions, including on recovery."""
import logging
import os
import random
from pathlib import Path

import pytest

from articulous.cli import CliOptions, parse_cli_args
from articulous.config import apply_cli_overrides, load_or_create_config
from articulous.migrations import OutputMigrations
from articulous.ownership import load_ownership, ownership_path
from articulous.pipeline import run_build


def _configuration(root, sections):
    cli = CliOptions(parse_cli_args(["--only", sections]))
    config = load_or_create_config(root / "config.json")
    apply_cli_overrides(config, cli, root)
    return cli, config


@pytest.mark.parametrize("section,filename", [("rss", "rss.xml"), ("search", "search.json")])
def test_owned_routes_migrate_both_directions(site_root, caplog, section, filename):
    cli, config = _configuration(site_root, section)
    output = site_root / "output"
    run_build(cli, config, site_root)
    leaf = output / filename
    original = leaf.read_bytes()
    for route in (f"/{filename}/nested/{filename}", f"/{filename}"):
        config["urls"][section] = route
        cli.dry_run = True
        journal = ownership_path(output).read_bytes()
        with caplog.at_level(logging.INFO):
            run_build(cli, config, site_root)
        assert "Would remove obsolete route obstruction" in caplog.text
        assert leaf.read_bytes() == original
        assert ownership_path(output).read_bytes() == journal
        cli.dry_run = False
        run_build(cli, config, site_root)
        leaf = output / route.lstrip("/")
        original = leaf.read_bytes()
        assert original
        assert load_ownership(output).paths == {route.lstrip("/"): section}
        before = leaf.stat().st_mtime_ns
        run_build(cli, config, site_root)
        assert leaf.stat().st_mtime_ns == before


def _obstruction(path, kind):
    makers = {
        "file": lambda: path.write_bytes(b"keep"),
        "fifo": lambda: os.mkfifo(path),
        "directory": lambda: path.mkdir(),
        "symlink": lambda: path.symlink_to("missing"),
    }
    makers[kind]()


@pytest.mark.parametrize("seed", [2026, 0xC0FFEE])
def test_migration_rejects_unsafe_obstructions_fuzz(tmp_path, seed):
    cases = [(kind, owner) for kind in ("file", "fifo", "directory", "symlink")
             for owner in ("unowned", "retained", "selected")]
    rng = random.Random(seed)
    rng.shuffle(cases)
    for index, (kind, owner) in enumerate(cases):
        root = tmp_path / str(index)
        root.mkdir()
        entry = root / "old.xml"
        _obstruction(entry, kind)
        old = {} if owner == "unowned" else {"old.xml": "rss"}
        retained = old if owner == "retained" else {}
        plan = OutputMigrations(root, old, retained)
        target = entry / Path(*(["nested"] * rng.randint(0, 4))) / "feed.xml"
        _check_obstruction(plan, target, kind, owner)
        assert entry.lstat()


def _check_obstruction(plan, target, kind, owner):
    if kind == "directory":
        assert not plan.requires_rebuild(target)
    elif kind == "file" and owner == "selected":
        assert plan.requires_rebuild(target)
        assert len(plan.removals()) == 1
    else:
        with pytest.raises((ValueError, OSError)):
            plan.requires_rebuild(target)


@pytest.mark.parametrize("kind", ["file", "fifo", "directory", "symlink"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_directory_migration_preserves_unowned_entries(site_root, kind, dry_run):
    cli, config = _configuration(site_root, "rss")
    config["urls"]["rss"] = "/feed/old.xml"
    run_build(cli, config, site_root)
    directory = site_root / "output/feed"
    extra = directory / "manual"
    _obstruction(extra, kind)
    owned = directory / "old.xml"
    before = owned.read_bytes()
    config["urls"]["rss"] = "/feed"
    cli.dry_run = dry_run
    with pytest.raises(ValueError, match="unowned|symlink"):
        run_build(cli, config, site_root)
    assert owned.read_bytes() == before
    assert extra.lstat()
    assert not load_ownership(site_root / "output").pending


@pytest.mark.parametrize("reverse", [False, True])
def test_migration_failure_recovers_with_full_build(site_root, monkeypatch, reverse):
    cli, config = _configuration(site_root, "rss")
    routes = ["/rss.xml", "/rss.xml/nested/feed.xml"]
    if reverse:
        routes.reverse()
    config["urls"]["rss"] = routes[0]
    run_build(cli, config, site_root)
    config["urls"]["rss"] = routes[1]
    with monkeypatch.context() as patch:
        patch.setattr("articulous.pipeline._run_plan", _fail_publication)
        with pytest.raises(OSError, match="interrupted"):
            run_build(cli, config, site_root)
    assert load_ownership(site_root / "output").pending
    with pytest.raises(ValueError, match="full recovery"):
        run_build(cli, config, site_root)
    cli.only_sections = []
    run_build(cli, config, site_root)
    assert (site_root / "output" / routes[1].lstrip("/")).is_file()
    assert not load_ownership(site_root / "output").pending


def _fail_publication(*_args):
    raise OSError("interrupted publication")


def test_migration_revalidates_before_removal(tmp_path):
    directory = tmp_path / "feed"
    directory.mkdir()
    old = directory / "old.xml"
    old.write_bytes(b"keep")
    plan = OutputMigrations(tmp_path, {"feed/old.xml": "rss"}, {})
    assert plan.requires_rebuild(directory)
    (directory / "manual").write_bytes(b"manual")
    with pytest.raises(ValueError, match="unowned"):
        plan.removals()
    assert old.read_bytes() == b"keep"


@pytest.mark.parametrize("reverse", [False, True])
def test_interrupted_migration_can_revert_routes(site_root, monkeypatch, reverse):
    import articulous.pipeline as pipeline

    cli, config = _configuration(site_root, "rss")
    routes = ["/rss.xml", "/rss.xml/nested/feed.xml"]
    if reverse:
        routes.reverse()
    config["urls"]["rss"] = routes[0]
    run_build(cli, config, site_root)
    config["urls"]["rss"] = routes[1]
    real_run = pipeline._run_plan

    def publish_then_fail(*args):
        real_run(*args)
        _fail_publication()

    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "_run_plan", publish_then_fail)
        with pytest.raises(OSError, match="interrupted"):
            run_build(cli, config, site_root)
    config["urls"]["rss"] = routes[0]
    cli.only_sections = []
    run_build(cli, config, site_root)
    assert (site_root / "output" / routes[0].lstrip("/")).is_file()
    assert not load_ownership(site_root / "output").pending
