"""Planning operation counts and preserved validation boundaries."""
from collections import Counter
from pathlib import Path

import pytest

from articulous import builds, pipeline
from articulous.composition_contracts import Route
from articulous.configuration_contracts import BuildRequest
from articulous.config import load_or_create_config
from articulous.engines import LxmlEngine
from test_composition import page


def test_perf10_admits_each_planned_output_once(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    hits = Counter()
    validate = pipeline.validate_path_length

    def count(path):
        hits[path] += 1
        validate(path)
    monkeypatch.setattr(pipeline, 'validate_path_length', count)
    pipeline.run_build(cli, config, site_root)
    assert hits
    assert set(hits.values()) == {1}


def test_perf10_rejects_route_metadata_that_disagrees_with_output(tmp_path):
    ctx = pipeline.BuildCtx(tmp_path, tmp_path, tmp_path, tmp_path / 'assets')
    route = Route('k', 'pages', 'https://example.test/x.html', 'x.html')
    with pytest.raises(ValueError, match='Route does not match planned output'):
        pipeline._record_planned_output(None, ctx, 'k', tmp_path / 'y.html', route)


def test_perf09_sorts_each_listing_language_once(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    cli.only_sections = ['index', 'tags', 'sitemap']
    config['sitemap']['include_listings'] = True
    counts = Counter()
    original = pipeline.ArticleStore.sorted

    def count(store, language):
        counts[language] += 1
        return original(store, language)
    monkeypatch.setattr(pipeline.ArticleStore, 'sorted', count)
    pipeline.run_build(cli, config, site_root)
    assert counts == dict.fromkeys(config['site']['languages'], 1)


def test_perf12_no_stale_paths_still_checks_current_ancestors(tmp_path):
    ctx = pipeline.BuildCtx(tmp_path, tmp_path, tmp_path, tmp_path / 'assets')
    (tmp_path / 'alias').symlink_to(tmp_path, target_is_directory=True)
    path = 'alias/current.html'
    with pytest.raises(OSError, match='Manifest output ancestor'):
        pipeline._prune_stale_outputs(ctx, {}, {path: 'old'}, {path: 'new'})


def test_perf12_keeps_cache_key_retirement_without_prune(tmp_path, monkeypatch):
    ctx = pipeline.BuildCtx(tmp_path, tmp_path, tmp_path, tmp_path / 'assets')

    def unexpected(*_args):
        pytest.fail('no stale paths should reach deletion planning')
    monkeypatch.setattr(pipeline, '_remove_stale_paths', unexpected)
    cache = {'old': 'retired'}
    path = 'current.html'
    pipeline._prune_stale_outputs(ctx, cache, {path: 'old'}, {path: 'new'})
    assert cache == {}


def test_perf15_force_skips_destination_content_comparison(site_root, monkeypatch):
    config = load_or_create_config(site_root / 'config.json')
    pipeline.run_build(BuildRequest(), config, site_root)
    copied = site_root / 'output/assets/style.css'
    copied.write_text('unreadable contents are unnecessary for force')

    def unexpected(*_args):
        pytest.fail('forced asset writes must not read destination bytes')
    monkeypatch.setattr(pipeline, '_asset_output_mismatches', unexpected)
    pipeline.run_build(BuildRequest(force_full_build=True), config, site_root)
    assert copied.read_bytes() == (site_root / 'assets/style.css').read_bytes()


def test_perf16_default_validators_use_one_validation_scan(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    calls = []
    actual = builds.tree_fingerprint

    def count(root):
        calls.append(root)
        return actual(root)
    monkeypatch.setattr(builds, 'tree_fingerprint', count)
    with builds.prepare_build(cli, config, site_root) as prepared:
        stage = builds.render_prepared(prepared)
        builds.validate_generated(stage)
    assert len(calls) == 2


def test_perf16_empty_custom_validator_iterable_still_checks_mutation(site_root, seo_config):
    cli, config = seo_config
    with builds.prepare_build(cli, config, site_root) as prepared:
        stage = builds.render_prepared(prepared)

        def mutating():
            (stage.root / 'rss.xml').write_text('changed')
            yield from ()
        with pytest.raises(ValueError, match='changed'):
            builds.validate_generated(stage, validators=mutating())


def test_perf22_extra_pages_share_one_stylesheet_capture(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    template = Path(config['paths']['xsl_dir']) / 'pages/index.xsl'
    calls = []
    capture = LxmlEngine.prepare_stylesheet

    def count(engine, path):
        if path == template:
            calls.append(path)
        return capture(engine, path)
    monkeypatch.setattr(LxmlEngine, 'prepare_stylesheet', count)
    cli.only_sections = ['rss']
    pages = [page(config, name) for name in ('about', 'help', 'legal')]
    pipeline.run_build(cli, config, site_root, extra_pages=pages)
    assert calls == [template]
    assert all((site_root / 'output' / p.route.output_path).is_file() for p in pages)


def test_perf13_clean_build_avoids_ownership_replacements(site_root, monkeypatch):
    from articulous import ownership

    config = load_or_create_config(site_root / 'config.json')
    pipeline.run_build(BuildRequest(), config, site_root)

    def unexpected(*_args):
        pytest.fail('settled no-op must not replace durable ownership')
    monkeypatch.setattr(ownership, 'write_text_atomic', unexpected)
    pipeline.run_build(BuildRequest(), config, site_root)


def test_perf13_asset_delta_journals_before_mutation(site_root, monkeypatch):
    from articulous.ownership import load_ownership

    config = load_or_create_config(site_root / 'config.json')
    pipeline.run_build(BuildRequest(), config, site_root)
    source = site_root / 'assets/style.css'
    source.write_text('p{color:red}')
    original = pipeline.copy_asset_file
    calls = []

    def check_pending(src, destination):
        assert load_ownership(site_root / 'output').pending
        calls.append(destination)
        return original(src, destination)
    monkeypatch.setattr(pipeline, 'copy_asset_file', check_pending)
    pipeline.run_build(BuildRequest(), config, site_root)
    assert calls == [site_root / 'output/assets/style.css']
    assert not load_ownership(site_root / 'output').pending


def test_perf13_missing_asset_tree_journals_before_prune(site_root, monkeypatch):
    from articulous.ownership import load_ownership

    config = load_or_create_config(site_root / 'config.json')
    pipeline.run_build(BuildRequest(), config, site_root)
    (site_root / 'assets/style.css').unlink()
    (site_root / 'assets').rmdir()
    before_delete = pipeline._delete_asset_entry

    def check_pending(path, root):
        assert load_ownership(site_root / 'output').pending
        before_delete(path, root)
    monkeypatch.setattr(pipeline, '_delete_asset_entry', check_pending)
    pipeline.run_build(BuildRequest(), config, site_root)
    assert not (site_root / 'output/assets').exists()
