"""Build, ownership and publication regressions from the November project audit."""
from concurrent.futures import CancelledError
from pathlib import Path
import json
import os
import random
import stat
from unittest.mock import Mock
from typing import Any, cast

import pytest

from articulous import pipeline
from articulous.backends.posix import PosixPublicationBackend
from articulous.builds import prepare_build, render_prepared, validate_generated
from articulous.filesystem import lock_file
from articulous.ownership import load_ownership, ownership_path
from articulous.publication import build_site, publish_validated, recover_publication
from articulous.runtime import run_parallel_tasks
from articulous.source_transactions import source_transaction
from test_prepared_build import snapshot
from test_seo_translations import _translation_pair, _alternates


def deny_listing(monkeypatch, directory):
    original = os.scandir
    def listing(path):
        if not isinstance(path, int) and Path(path) == directory:
            raise PermissionError(str(directory))
        return original(path)
    monkeypatch.setattr(os, 'scandir', listing)


@pytest.mark.parametrize('partial', [False, True])
@pytest.mark.parametrize('restore', [False, True])
def test_audit26_01_stale_cache_rebuilds_current_outputs(site_root, seo_config, partial, restore):
    cli, config = seo_config
    source = site_root / 'content/en/first-post.xml'
    page = site_root / 'output/en/articles/first-post/index.html'
    cache = site_root / '.build-cache.json'
    original = source.read_bytes()
    pipeline.run_build(cli, config, site_root)
    cached, expected = cache.read_bytes(), page.read_bytes()
    cold_output = snapshot(site_root / 'output')
    source.write_bytes(original.replace(b'Inaugural article.', b'Different article.'))
    if not restore:
        config['build']['cache_file'] = 'second.json'
    pipeline.run_build(cli, config, site_root)
    assert page.read_bytes() != expected
    if restore:
        cache.write_bytes(cached)
    source.write_bytes(original)
    config['build']['cache_file'] = cache.name
    cli.only_sections = ['articles'] if partial else None
    pipeline.run_build(cli, config, site_root)
    assert page.read_bytes() == expected
    cli.only_sections = None
    pipeline.run_build(cli, config, site_root)
    assert snapshot(site_root / 'output') == cold_output


@pytest.mark.parametrize('build', [pipeline.run_build, build_site])
def test_audit26_02_asset_directory_read_failure(site_root, seo_config, monkeypatch, build):
    directory = site_root / 'assets/sub'
    directory.mkdir()
    (directory / 'keep').write_bytes(b'asset')
    pipeline.run_build(seo_config[0], seo_config[1], site_root)
    with monkeypatch.context() as fault:
        deny_listing(fault, directory)
        with pytest.raises(PermissionError):
            build(seo_config[0], seo_config[1], site_root)
    assert (site_root / 'output/assets/sub/keep').read_bytes() == b'asset'
    (directory / 'keep').unlink()
    build(seo_config[0], seo_config[1], site_root)
    assert not (site_root / 'output/assets/sub/keep').exists()


def test_audit26_03_partial_destination_inventory(site_root, seo_config, monkeypatch):
    build_site(seo_config[0], seo_config[1], site_root)
    output = site_root / 'output'
    manual = output / 'en/articles/manual.txt'
    manual.write_bytes(b'unowned')
    cache = site_root / '.build-cache.json'
    before = snapshot(output), ownership_path(output).read_bytes(), cache.read_bytes()
    with monkeypatch.context() as fault:
        deny_listing(fault, manual.parent)
        with pytest.raises(PermissionError):
            build_site(seo_config[0], seo_config[1], site_root)
    assert (snapshot(output), ownership_path(output).read_bytes(), cache.read_bytes()) == before


@pytest.mark.parametrize('bad', ['[' * 1200 + ']' * 1200, '8' * 5000], ids=['depth', 'integer'])
def test_audit26_04_disposable_cache_decode_limits(site_root, seo_config, bad):
    pipeline.run_build(seo_config[0], seo_config[1], site_root)
    output, cache = site_root / 'output', site_root / '.build-cache.json'
    before = snapshot(output)
    cache.write_text(bad)
    pipeline.run_build(seo_config[0], seo_config[1], site_root)
    assert snapshot(output) == before
    assert str(output) in json.loads(cache.read_bytes())['__output_roots__']


@pytest.mark.parametrize('publish', [pipeline.run_build, build_site])
def test_audit26_08_missing_translation_history(site_root, seo_config, publish):
    cli, config = seo_config
    _translation_pair(site_root)
    publish(cli, config, site_root)
    en = site_root / 'content/en/first-post.xml'
    en.write_text(en.read_text().replace('<translation>first</translation>', ''))
    (site_root / '.build-cache.json').unlink()
    before = snapshot(site_root / 'output')
    cli.only_langs = ['en']
    with pytest.raises(ValueError, match='full build.*translation'):
        pipeline.run_build(cli, config, site_root)
    assert snapshot(site_root / 'output') == before
    cli.only_langs = None
    pipeline.run_build(cli, config, site_root)
    assert set(_alternates(site_root / 'output/fr/articles/premier-article/index.html')) == {'fr'}


def test_audit26_09_missing_configuration_outside_output_only(site_root, run_sitegen):
    result = run_sitegen(['--dry-run', '--config', 'output/nested/site.json'], check=False)
    assert result.returncode != 0 and b'outside the output' in result.stderr
    assert not (site_root / 'output').exists()
    run_sitegen(['--dry-run', '--config', 'allowed/site.json'])
    assert (site_root / 'allowed/site.json').is_file()


def test_audit26_12_incomplete_source_transaction(tmp_path, monkeypatch):
    with pytest.raises(PermissionError):
        with source_transaction(tmp_path) as edit:
            edit.write('first', b'one')
            edit.write('sub/second', b'two')
            deny_listing(monkeypatch, edit.stage / 'sub')
    assert list(tmp_path.iterdir()) == []


def test_audit26_15_recover_malformed_lock(tmp_path):
    path = tmp_path / 'build.lock'
    path.write_text('[' * 1200 + ']' * 1200)
    with lock_file(path):
        assert json.loads(path.read_text())['pid'] == os.getpid()
        with pytest.raises(FileExistsError):
            with lock_file(path):
                pytest.fail('admitted concurrent holder')


@pytest.mark.parametrize('initial,updated', [(0o600, 0o644), (0o644, 0o600)])
def test_audit26_16_mirror_mode_changes(site_root, seo_config, initial, updated):
    source = site_root / 'assets/style.css'
    dest = site_root / 'output/assets/style.css'
    source.chmod(initial)
    pipeline.run_build(seo_config[0], seo_config[1], site_root)
    source.chmod(updated)
    pipeline.run_build(seo_config[0], seo_config[1], site_root)
    assert stat.S_IMODE(dest.stat().st_mode) == updated
    dest.chmod(initial)
    pipeline.run_build(seo_config[0], seo_config[1], site_root)
    assert stat.S_IMODE(dest.stat().st_mode) == updated


def test_audit26_19_worker_cancellation_preserves_recovery(site_root, seo_config, monkeypatch):
    monkeypatch.setattr(pipeline, '_write_native_search', Mock(side_effect=CancelledError('render cancelled')))
    with pytest.raises(CancelledError, match='render cancelled'):
        pipeline.run_build(seo_config[0], seo_config[1], site_root)
    assert load_ownership(site_root / 'output').pending


def test_audit26_20_executor_admission():
    task = Mock(return_value=7)
    for value in (True, False, 0, -1, None, '2', 'unknown', *random.Random(20).sample(range(32), 5)):
        invalid = value + 0.5 if type(value) is int and value > 0 else value
        with pytest.raises(ValueError):
            run_parallel_tasks([task], cast(Any, invalid))
    task.assert_not_called()
    for workers in (1, 'auto'):
        assert run_parallel_tasks([task], workers) == [7]


def test_audit26_25_unreadable_article_preserves_publication(site_root, seo_config, monkeypatch):
    from articulous import articles
    pipeline.run_build(seo_config[0], seo_config[1], site_root)
    original = articles.read_source
    source = site_root / 'content/en/first-post.xml'
    before = snapshot(site_root / 'output')
    def read(path):
        if path == source:
            raise PermissionError(str(path))
        return original(path)
    with monkeypatch.context() as fault:
        fault.setattr(articles, 'read_source', read)
        with pytest.raises(PermissionError):
            pipeline.run_build(seo_config[0], seo_config[1], site_root)
    assert snapshot(site_root / 'output') == before
    source.unlink()
    pipeline.run_build(seo_config[0], seo_config[1], site_root)
    assert not (site_root / 'output/en/articles/first-post/index.html').exists()


def test_audit26_26_incomplete_validated_tree(site_root, seo_config, monkeypatch):
    (site_root / 'assets/empty').mkdir()
    with prepare_build(seo_config[0], seo_config[1], site_root) as prepared:
        staged = render_prepared(prepared)
        checked = validate_generated(staged)
        hidden = staged.root / 'assets/empty/extra'
        hidden.write_bytes(b'after validation')
        with monkeypatch.context() as fault:
            deny_listing(fault, hidden.parent)
            with pytest.raises(PermissionError):
                publish_validated(checked)
        assert not (site_root / 'output').exists()
        hidden.unlink()
        publish_validated(checked)


def test_audit26_23_partial_cleanup_preserves_retry(site_root, seo_config, monkeypatch):
    from articulous.backends import posix
    backend = PosixPublicationBackend()
    build_site(seo_config[0], seo_config[1], site_root)
    transaction = site_root / '.output.articulous-transaction'
    remove = posix._remove_tree
    def interrupted(path):
        if path == transaction:
            (path / 'journal.json').unlink()
            raise OSError('interrupted recursive cleanup')
        if path == transaction / 'previous':
            raise OSError('interrupted recursive cleanup')
        remove(path)
    with monkeypatch.context() as fault:
        fault.setattr(posix, '_remove_tree', interrupted)
        build_site(seo_config[0], seo_config[1], site_root, backend=backend)
    before = snapshot(site_root / 'output')
    recover_publication(site_root / 'output', site_root / '.build-cache.json')
    assert not transaction.exists()
    assert snapshot(site_root / 'output') == before


def test_audit26_08_old_ownership_requires_full_translation_baseline(site_root, seo_config):
    cli, config = seo_config
    _translation_pair(site_root)
    pipeline.run_build(cli, config, site_root)
    state = ownership_path(site_root / 'output')
    legacy = json.loads(state.read_text())
    del legacy['generation'], legacy['translations']
    state.write_text(json.dumps(legacy))
    cli.only_sections = ['rss']
    pipeline.run_build(cli, config, site_root)
    assert load_ownership(site_root / 'output').translations is None
    cli.only_sections = None
    cli.only_langs = ['en']
    with pytest.raises(ValueError, match='full build.*translation'):
        pipeline.run_build(cli, config, site_root)
    cli.only_langs = None
    pipeline.run_build(cli, config, site_root)
    assert len(load_ownership(site_root / 'output').translations or {}) == 2


@pytest.mark.parametrize('invalid', [[], {'rss': 'bad'}, {'article:en:x': ['g', '']}, {'article:en:first-post': [1, '']},
                                      {'article:en:first-post': []}, {'article:en:first-post': True}])
def test_audit26_08_invalid_translation_history(site_root, seo_config, invalid):
    pipeline.run_build(seo_config[0], seo_config[1], site_root)
    path = ownership_path(site_root / 'output')
    state = json.loads(path.read_text())
    state['translations'] = invalid
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match='translation ownership'):
        load_ownership(site_root / 'output')


def test_audit26_25_discovered_source_disappears(site_root, seo_config, monkeypatch):
    from articulous import articles
    monkeypatch.setattr(articles, 'read_source', Mock(side_effect=FileNotFoundError('removed after enumeration')))
    with pytest.raises(FileNotFoundError):
        pipeline.run_build(seo_config[0], seo_config[1], site_root)
    assert not (site_root / 'output').exists()


def test_audit26_23_retry_after_journal_unlink(site_root, seo_config, monkeypatch):
    backend = PosixPublicationBackend()
    retired = site_root / '.output.articulous-transaction-retired'
    remove = Path.rmdir
    def interrupt(path):
        if path == retired:
            raise PermissionError('pending final directory removal')
        return remove(path)
    with monkeypatch.context() as fault:
        fault.setattr(Path, 'rmdir', interrupt)
        build_site(seo_config[0], seo_config[1], site_root, backend=backend)
    assert retired.is_dir() and not list(retired.iterdir())
    before = snapshot(site_root / 'output')
    recover_publication(site_root / 'output', site_root / '.build-cache.json')
    assert not retired.exists()
    assert snapshot(site_root / 'output') == before


def test_audit26_23_retirement_preserves_unknown_files(site_root):
    retired = site_root / '.output.articulous-transaction-retired'
    retired.mkdir()
    manual = retired / 'keep'
    manual.write_bytes(b'manual')
    with pytest.raises(ValueError, match='Unexpected files'):
        recover_publication(site_root / 'output', site_root / '.build-cache.json')
    assert manual.read_bytes() == b'manual'


def test_audit26_23_rolled_back_cleanup_resumes_without_snapshots(site_root, seo_config, monkeypatch):
    from articulous.backends import posix
    cli, config = seo_config
    build_site(cli, config, site_root)
    output = site_root / 'output'
    cache = site_root / '.build-cache.json'
    before = snapshot(output), ownership_path(output).read_bytes(), cache.read_bytes()
    backend = PosixPublicationBackend()
    remove = posix._remove_tree
    def interrupt(path):
        if path.name == 'discard':
            (path.parent / 'cache.before').unlink(missing_ok=True)
            raise OSError('rollback cleanup interrupted')
        remove(path)
    with monkeypatch.context() as fault:
        fault.setattr(backend, '_write_state', Mock(side_effect=OSError('failed to install')))
        fault.setattr(posix, '_remove_tree', interrupt)
        with pytest.raises(RuntimeError, match='needs recovery'):
            build_site(cli, config, site_root, backend=backend)
    recover_publication(output, cache)
    assert (snapshot(output), ownership_path(output).read_bytes(), cache.read_bytes()) == before


def test_audit26_23_preparation_error_after_journal_replace(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    build_site(cli, config, site_root)
    output = site_root / 'output'
    cache = site_root / '.build-cache.json'
    before = snapshot(output), ownership_path(output).read_bytes(), cache.read_bytes()
    backend = PosixPublicationBackend()
    persist = backend._set_phase
    def interrupt(transaction, data, phase):
        persist(transaction, data, phase)
        if phase == 'prepared':
            raise OSError('interrupted after journal replacement')
    monkeypatch.setattr(backend, '_set_phase', interrupt)
    with pytest.raises(OSError, match='after journal replacement'):
        build_site(cli, config, site_root, backend=backend)
    recover_publication(output, cache)
    assert (snapshot(output), ownership_path(output).read_bytes(), cache.read_bytes()) == before


@pytest.mark.parametrize('invalid', [True, 1, {}, [], 'z' * 32, '0' * 31, '1' * 33])
def test_audit26_01_invalid_ownership_generation(tmp_path, invalid):
    output = tmp_path / 'output'
    state = {'version': 2, 'output_dir': str(output), 'paths': {}, 'generation': invalid}
    ownership_path(output).write_text(json.dumps(state))
    with pytest.raises(ValueError, match='generation'):
        load_ownership(output)
