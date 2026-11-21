"""Planning operation counts and preserved validation boundaries."""
from collections import Counter
from dataclasses import asdict
import json
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


def test_perf33_models_are_shared_with_sitemap_and_routes_keep_section_order(site_root, seo_config, monkeypatch):
    from articulous.composition import RouteCatalog

    cli, config = seo_config
    config['sitemap']['include_listings'] = True
    counts = Counter()
    indexes, tags = pipeline.build_index_models, pipeline._iter_tag_pages

    def index(rows, lang, ctx):
        counts['index', lang] += 1
        return indexes(rows, lang, ctx)

    def tag(rows, lang, ctx, **options):
        counts['tags', lang] += 1
        return tags(rows, lang, ctx, **options)

    monkeypatch.setattr(pipeline, 'build_index_models', index)
    monkeypatch.setattr(pipeline, '_iter_tag_pages', tag)
    with RouteCatalog() as catalog:
        pipeline.run_build(cli, config, site_root, route_catalog=catalog)
        routes = list(catalog)
    assert counts == dict.fromkeys(((section, lang) for section in ('index','tags')
                                   for lang in config['site']['languages']),1)
    assert [route.section for route in routes[:3]] == ['rss','sitemap','search']


def test_perf39_publication_projects_the_catalog_once(site_root, seo_config, monkeypatch):
    from articulous.composition import RouteCatalog
    from articulous.publication_adapter import publication_input

    cli, config = seo_config
    calls = []
    read = RouteCatalog._reader

    def observe(catalog):
        calls.append(catalog)
        return read(catalog)

    with builds.prepare_build(cli, config, site_root) as prepared:
        expected = list(prepared.routes)
        checked = builds.validate_generated(builds.render_prepared(prepared))
        monkeypatch.setattr(RouteCatalog, '_reader', observe)
        publication = publication_input(checked)
    assert len(calls) == 1
    assert list(publication.output_routes.values()) == expected
    root_cache = json.loads(publication.cache_text)['__output_roots__'][str(publication.destination)]
    assert root_cache['__routes__'] == {route.key: asdict(route) for route in expected}
    assert not hasattr(publication.output_routes, 'clear')


def test_perf21_short_pread_completes_a_queued_payload(site_root, monkeypatch):
    import os

    read = os.pread

    def limited(fd, size, offset):
        return read(fd, min(size, 200), offset)
    monkeypatch.setattr(os, 'pread', limited)
    config = load_or_create_config(site_root / 'config.json')
    pipeline.run_build(BuildRequest(), config, site_root)
    assert (site_root / 'output/en/articles/first-post/index.html').is_file()


def test_perf21_truncated_payload_fails_before_write(site_root, monkeypatch):
    import os

    def empty(*_args):
        return b''
    monkeypatch.setattr(os, 'pread', empty)
    config = load_or_create_config(site_root / 'config.json')
    request = BuildRequest(only_sections=['articles'], only_slugs=['first-post'])
    with pytest.raises(ValueError, match='Task spool truncated'):
        pipeline.run_build(request, config, site_root)
    assert not (site_root / 'output/en/articles/first-post/index.html').exists()


def test_perf33_planner_without_manifest_discards_listing_records():
    from articulous.pipeline import _ListingRecords

    records = _ListingRecords()
    records.record('index:en:1', 'index.html')
    records.replay(None)


def test_review28_34_integrated_publish_only_hashes_render_and_install(site_root, seo_config, monkeypatch):
    from articulous.publication import build_site
    calls = []
    digest = builds.tree_fingerprint

    def measured(root):
        calls.append(root)
        return digest(root)

    monkeypatch.setattr(builds, 'tree_fingerprint', measured)
    cli, config = seo_config
    build_site(cli, config, site_root)
    assert len(calls) == 2
    assert calls[0] == calls[1]


@pytest.mark.parametrize('capacity,workers', [(1, 1), (2, 2), (32, 2)])
def test_review28_04_auto_worker_plateau(tmp_path, monkeypatch, capacity, workers):
    from articulous import runtime
    ctx = pipeline.BuildCtx(tmp_path, tmp_path, tmp_path, tmp_path)
    monkeypatch.setattr(runtime, 'available_cpus', lambda: capacity)
    assert pipeline._resolve_parallelism(ctx) == workers
    assert runtime._worker_count('auto') == workers
    assert runtime._worker_count(8) == 8


def test_review28_05_warm_build_reuses_route_admission(site_root, seo_config, monkeypatch):
    from articulous import runtime
    from articulous.migrations import OutputMigrations
    cli, config = seo_config
    pipeline.run_build(cli, config, site_root)
    admitted = Counter()
    check = OutputMigrations.admit_path

    def observe(self, path):
        admitted[path] += 1
        check(self, path)

    def duplicate(_path):
        pytest.fail('admitted route returned to public path validation')

    monkeypatch.setattr(OutputMigrations, 'admit_path', observe)
    monkeypatch.setattr(runtime, 'validate_output_path', duplicate)
    pipeline.run_build(cli, config, site_root)
    assert admitted and max(admitted.values()) == 1


def test_review28_34_fingerprint_rejects_replaced_and_special_entries(tmp_path, monkeypatch):
    import os
    from articulous.filesystem import tree_fingerprint
    root = tmp_path / 'stage'
    root.mkdir()
    entry = root / 'artifact'
    entry.symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(ValueError, match='regular file'):
        tree_fingerprint(root)
    entry.unlink()
    entry.write_bytes(b'original')
    opened = os.open

    def swap(name, flags, **kwargs):
        if name == 'artifact':
            replacement = root / 'replaced'
            replacement.write_bytes(b'different')
            replacement.replace(entry)
        return opened(name, flags, **kwargs)

    monkeypatch.setattr(os, 'open', swap)
    with pytest.raises(ValueError, match='changed'):
        tree_fingerprint(root)


def test_review28_05_missing_or_concurrently_created_directory(tmp_path, monkeypatch):
    import os
    from articulous.filesystem import _directory_handle
    absent = tmp_path / 'new'
    with pytest.raises(FileNotFoundError), _directory_handle(absent):
        pytest.fail('admitted missing directory')
    mkdir = os.mkdir

    def concurrent(name, *, dir_fd):
        mkdir(name, dir_fd=dir_fd)
        raise FileExistsError(name)

    monkeypatch.setattr(os, 'mkdir', concurrent)
    with _directory_handle(absent, create=True) as handle:
        assert os.path.samestat(absent.stat(), os.fstat(handle))


def test_review28_05_transient_parent_obstruction(tmp_path):
    from articulous.migrations import OutputMigrations
    mode = OutputMigrations(tmp_path, {}, {})
    assert not mode._obstructing_parent(tmp_path / 'now-missing/item')


def test_review28_34_staged_mode_changes_during_open(tmp_path, monkeypatch):
    import os
    from articulous.filesystem import tree_fingerprint
    entry = tmp_path / 'page'
    entry.write_text('checked')
    opened = os.open

    def change_mode(name, flags, **kwargs):
        if name == 'page':
            entry.chmod(entry.stat().st_mode ^ 0o004)
        return opened(name, flags, **kwargs)

    monkeypatch.setattr(os, 'open', change_mode)
    with pytest.raises(ValueError, match='changed'):
        tree_fingerprint(tmp_path)
