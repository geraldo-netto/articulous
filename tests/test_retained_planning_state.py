"""REVIEW28-14 planning state at the incremental rendering boundary."""
from weakref import ref

import pytest

from articulous import pipeline
from articulous.configuration_contracts import BuildRequest


@pytest.mark.parametrize("build_request", [
    BuildRequest(force_full_build=True), BuildRequest(only_slugs=["first-post"], force_full_build=True),
])
@pytest.mark.parametrize("resource", ["previous_route", "output_collision_index", "checked_ancestors"])
def test_review28_14_releases_planning_state_before_render(site_root, seo_config, monkeypatch,
                                                           build_request, resource):
    cli, config = seo_config
    pipeline.run_build(cli, config, site_root)
    prepare = pipeline._prepare_outputs
    run_plan = pipeline._run_plan
    outstanding = []

    def before_prepare(ctx, cache, ownership, manifest, next_paths, plan):
        route = ref(ownership.routes["article:en:first-post"])
        planner = ref(manifest)
        migrations = ref(ctx.output_migrations)
        observations = {
            "previous_route": lambda: route() is not None,
            "output_collision_index": lambda: (owner := planner()) is not None and bool(owner._owners),
            "checked_ancestors": lambda: (owner := migrations()) is not None and bool(owner._parents),
        }
        outstanding.append(observations[resource])
        assert outstanding[0]()
        return prepare(ctx, cache, ownership, manifest, next_paths, plan)

    def at_render(plan, ctx):
        assert not outstanding[0](), resource
        run_plan(plan, ctx)

    monkeypatch.setattr(pipeline, "_prepare_outputs", before_prepare)
    monkeypatch.setattr(pipeline, "_run_plan", at_render)
    pipeline.run_build(build_request, config, site_root)
    assert len(outstanding) == 1


def test_review28_14_unchanged_ownership_reuses_its_path_map(tmp_path):
    ctx = pipeline.BuildCtx(tmp_path, tmp_path, tmp_path, tmp_path / "assets")
    previous = {"rss.xml": "rss", "search.json": "search"}
    selected = {"rss": "rss.xml"}
    request = BuildRequest(only_sections=["rss"])
    assert pipeline._next_output_paths(request, ctx, previous, selected) is previous
    moved = pipeline._next_output_paths(request, ctx, previous, {"rss": "new.xml"})
    assert moved == {"new.xml": "rss", "search.json": "search"}
    assert previous == {"rss.xml": "rss", "search.json": "search"}


def test_review28_14_noop_skips_ownership_encoding(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    pipeline.run_build(cli, config, site_root)
    path = pipeline.ownership_path(site_root / "output")
    initial = path.read_bytes()
    calls = []
    save = pipeline.save_ownership

    def observe(*args, **kwargs):
        calls.append(True)
        return save(*args, **kwargs)

    monkeypatch.setattr(pipeline, "save_ownership", observe)
    pipeline.run_build(cli, config, site_root)
    assert not calls and path.read_bytes() == initial


@pytest.mark.parametrize("change", ["missing", "replaced", "modified"])
def test_review28_14_restores_changed_ownership_at_finalization(site_root, seo_config, monkeypatch, change):
    cli, config = seo_config
    pipeline.run_build(cli, config, site_root)
    path = pipeline.ownership_path(site_root / "output")
    expected = path.read_bytes()
    run_plan = pipeline._run_plan

    def change_state(plan, ctx):
        run_plan(plan, ctx)
        if change != "modified":
            path.unlink()
        if change != "missing":
            path.write_bytes(b"not a valid ownership record")

    monkeypatch.setattr(pipeline, "_run_plan", change_state)
    pipeline.run_build(cli, config, site_root)
    assert path.read_bytes() == expected


def test_review28_14_shared_paths_verify_live_ancestors_without_building_differences(tmp_path):
    class UnchangedPaths(dict):
        def keys(self):
            pytest.fail("An unchanged ownership mapping has no stale paths")

        def values(self):
            pytest.fail("An unchanged ownership mapping has no stale cache keys")

    ctx = pipeline.BuildCtx(tmp_path, tmp_path, tmp_path, tmp_path / "assets")
    paths = UnchangedPaths({"alias/current.html": "article:en:current"})
    (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError, match="Manifest output ancestor"):
        pipeline._OutputPaths(paths, paths).prune(ctx, {})


def test_review28_14_empty_selection_reconciles_replaced_cache_generation(site_root, seo_config):
    cli, config = seo_config
    pipeline.run_build(cli, config, site_root)
    output = site_root / "output"
    previous = pipeline.load_ownership(output)
    (site_root / ".build-cache.json").unlink()
    selection = BuildRequest(only_sections=["articles"], only_slugs=["absent"])
    pipeline.run_build(selection, config, site_root)
    restored = pipeline.load_ownership(output)
    assert restored.paths == previous.paths and restored.routes == previous.routes
    assert restored.generation != previous.generation
    cache, _ = pipeline._load_build_cache(site_root / ".build-cache.json", output)
    assert restored.generation == cache["__generation__"]


def test_review28_14_asset_only_journal_is_committed(site_root, seo_config):
    cli, config = seo_config
    pipeline.run_build(cli, config, site_root)
    (site_root / "assets/added.txt").write_text("new asset")
    pipeline.run_build(cli, config, site_root)
    output = site_root / "output"
    assert (output / "assets/added.txt").read_text() == "new asset"
    assert not pipeline.load_ownership(output).pending


def test_review28_14_route_rename_retains_only_pending_deletions(site_root, seo_config, monkeypatch):
    from dataclasses import replace

    class ObservedPaths(dict):
        pass

    cli, config = seo_config
    pipeline.run_build(cli, config, site_root)
    config["urls"]["rss"] = "/new.xml"
    original = pipeline._incremental_state
    run_plan = pipeline._run_plan
    previous = []

    def load(*args):
        cache, roots, ownership = original(*args)
        paths = ObservedPaths(ownership.paths)
        previous.append(ref(paths))
        return cache, roots, replace(ownership, paths=paths)

    def at_render(plan, ctx):
        assert previous[0]() is None
        run_plan(plan, ctx)

    monkeypatch.setattr(pipeline, "_incremental_state", load)
    monkeypatch.setattr(pipeline, "_run_plan", at_render)
    pipeline.run_build(cli, config, site_root)
    assert (site_root / "output/new.xml").is_file()
    assert not (site_root / "output/rss.xml").exists()
