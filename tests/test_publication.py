"""ARCH-005: native publication, rollback, recovery and explicit capabilities."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from articulous.backends.posix import PosixPublicationBackend
from articulous.builds import prepare_build, render_prepared, validate_generated
from articulous.publication import build_site, publish_validated, recover_publication
from articulous.publication_adapter import publication_input
from articulous.pipeline import run_build
from test_composition import page
from test_prepared_build import snapshot


def published(root):
    return (snapshot(root / 'output'), (root / '.build-cache.json').read_bytes(),
            (root / '.output.articulous-ownership.json').read_bytes())


def test_arch005_publish_replace_and_incremental_compatibility(site_root, seo_config):
    cli, config = seo_config
    report = build_site(cli, config, site_root, extra_pages=[page(config)])
    assert report.routes > 0
    assert (site_root / 'output/about/index.html').is_file()
    build_site(cli, config, site_root)
    assert not (site_root / 'output/about').exists()
    before = published(site_root)
    run_build(cli, config, site_root)
    assert published(site_root) == before
    assert not list(site_root.glob('.output.articulous-transaction'))


@pytest.mark.parametrize('operation', [1, 2, 3])
def test_arch005_rename_failures_roll_back(site_root, seo_config, monkeypatch, operation):
    cli, config = seo_config
    build_site(cli, config, site_root)
    previous = published(site_root)
    backend = PosixPublicationBackend()
    original = backend._rename
    calls = []
    def fail(source, destination):
        calls.append(source)
        if len(calls) == operation:
            raise OSError('injected rename failure')
        original(source, destination)
    monkeypatch.setattr(backend, '_rename', fail)
    with pytest.raises(OSError, match='injected'):
        build_site(cli, config, site_root, backend=backend)
    assert published(site_root) == previous


def test_arch005_state_failure_and_rollback_retry(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    build_site(cli, config, site_root)
    previous = published(site_root)
    backend = PosixPublicationBackend()
    original = backend._write_state
    def fail(checked):
        original(checked)
        raise OSError('state write failure')
    monkeypatch.setattr(backend, '_write_state', fail)
    with pytest.raises(OSError, match='state write'):
        build_site(cli, config, site_root, backend=backend)
    assert published(site_root) == previous


@pytest.mark.parametrize('phase', ['prepared', 'old_moved', 'installed', 'committed'])
def test_arch005_process_death_recovery(site_root, seo_config, phase):
    cli, config = seo_config
    build_site(cli, config, site_root)
    previous = published(site_root)
    source = site_root / 'content/en/first-post.xml'
    source.write_text(source.read_text().replace('First Post', 'Changed after previous publication'))
    script = '''
import json, os, sys
from pathlib import Path
from articulous.cli import CliOptions, parse_cli_args
from articulous.backends.posix import PosixPublicationBackend
from articulous.publication import build_site
backend = PosixPublicationBackend()
original = backend._set_phase
def crash(transaction, data, phase):
    original(transaction, data, phase)
    if phase == sys.argv[2]:
        os._exit(91)
backend._set_phase = crash
root = Path(sys.argv[1])
build_site(CliOptions(parse_cli_args([])), json.loads((root/'config.json').read_text()), root, backend=backend)
'''
    result = subprocess.run([sys.executable, '-c', script, str(site_root), phase],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True)
    assert result.returncode == 91, result.stderr.decode()
    expected = published(site_root) if phase == 'committed' else previous
    assert (expected[0] != previous[0]) == (phase == 'committed')
    recover_publication(site_root / 'output', site_root / '.build-cache.json')
    assert published(site_root) == expected
    assert not (site_root / '.output.articulous-transaction').exists()
    assert not list(site_root.glob('.articulous-stage-*'))


def test_arch005_failed_rollback_retains_recovery_data(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    build_site(cli, config, site_root)
    previous = published(site_root)
    backend = PosixPublicationBackend()
    original = backend._rename
    def fail(source, destination):
        if source.name in ('new', 'previous'):
            raise OSError('rename unavailable')
        original(source, destination)
    monkeypatch.setattr(backend, '_rename', fail)
    with pytest.raises(RuntimeError, match='recovery'):
        build_site(cli, config, site_root, backend=backend)
    transaction = site_root / '.output.articulous-transaction'
    assert (transaction / 'previous').is_dir()
    recover_publication(site_root / 'output', site_root / '.build-cache.json')
    assert published(site_root) == previous


def test_arch005_unowned_output_and_changed_stage_are_preserved(site_root, seo_config):
    cli, config = seo_config
    output = site_root / 'output'
    output.mkdir()
    (output / 'manual.txt').write_text('keep')
    with pytest.raises(ValueError, match='ownership'):
        build_site(cli, config, site_root)
    assert (output / 'manual.txt').read_text() == 'keep'
    with prepare_build(cli, config, site_root) as prepared:
        staged = render_prepared(prepared)
        checked = validate_generated(staged)
        (staged.root / 'rss.xml').write_text('tampered')
        with pytest.raises(ValueError, match='changed'):
            publish_validated(checked)


@pytest.mark.parametrize('requirement', ['require_atomic', 'require_durable'])
def test_arch005_unavailable_guarantee_rejected_before_staging(site_root, seo_config, requirement):
    cli, config = seo_config
    with pytest.raises(ValueError, match='unsupported'):
        build_site(cli, config, site_root, **{requirement: True})
    assert not list(site_root.glob('.articulous-stage-*'))


def test_arch005_unsupported_platform_and_capability_contract(site_root, seo_config, monkeypatch):
    import articulous.backends as adapters
    cli, config = seo_config
    monkeypatch.setattr(adapters.sys, 'platform', 'win32')
    assert not adapters.publication_capabilities().available
    with pytest.raises(RuntimeError, match='unsupported'):
        build_site(cli, config, site_root)
    with pytest.raises(RuntimeError, match='unsupported'):
        PosixPublicationBackend()


def test_arch005_unknown_files_in_owned_tree_prevent_replacement(site_root, seo_config):
    cli, config = seo_config
    build_site(cli, config, site_root)
    (site_root / 'output/manual.txt').write_text('keep')
    with pytest.raises(ValueError, match='unowned'):
        build_site(cli, config, site_root)
    assert (site_root / 'output/manual.txt').read_text() == 'keep'


@pytest.mark.parametrize('journal', [{}, {'version': 0}, {'destination': '../escape'}])
def test_arch005_invalid_journals_preserve_files(site_root, journal):
    transaction = site_root / '.output.articulous-transaction'
    transaction.mkdir()
    (transaction / 'journal.json').write_text(json.dumps(journal))
    with pytest.raises(ValueError, match='journal'):
        recover_publication(site_root / 'output', site_root / '.build-cache.json')
    assert transaction.is_dir()


@pytest.mark.parametrize('value', [None, 0, 'yes', [], {}])
def test_arch005_invalid_capability_requirements(site_root, seo_config, value):
    cli, config = seo_config
    with pytest.raises(ValueError, match='booleans'):
        build_site(cli, config, site_root, require_atomic=value)


def test_arch005_backend_contract_and_lock_alias(site_root, seo_config):
    cli, config = seo_config
    backend = PosixPublicationBackend()
    backend.capabilities = replace(backend.capabilities, staging=False)
    with pytest.raises(ValueError, match='unsupported'):
        build_site(cli, config, site_root, backend=backend)
    with pytest.raises(ValueError, match='alias'):
        with backend.locked(site_root / 'output', site_root / '.output.articulous.lock'):
            pytest.fail('lock alias accepted')


def test_arch005_first_publication_state_failure_restores_absence(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    backend = PosixPublicationBackend()
    original = backend._write_state
    def fail(checked):
        original(checked)
        raise OSError('state failed')
    monkeypatch.setattr(backend, '_write_state', fail)
    with pytest.raises(OSError, match='state failed'):
        build_site(cli, config, site_root, backend=backend)
    assert not (site_root / 'output').exists()
    assert not (site_root / '.build-cache.json').exists()
    assert not (site_root / '.output.articulous-ownership.json').exists()


def test_arch005_destination_swap_preserves_unknown_tree(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    build_site(cli, config, site_root)
    previous = published(site_root)
    backend = PosixPublicationBackend()
    original = backend._rename
    output = site_root / 'output'
    def swap(source, destination):
        original(source, destination)
        if destination.name == 'new':
            output.rename(site_root / 'saved-original')
            output.mkdir()
            (output / 'manual.txt').write_text('unowned replacement')
    monkeypatch.setattr(backend, '_rename', swap)
    with pytest.raises(RuntimeError, match='recovery'):
        build_site(cli, config, site_root, backend=backend)
    assert (output / 'manual.txt').read_text() == 'unowned replacement'
    assert snapshot(site_root / 'saved-original') == previous[0]


@pytest.mark.parametrize('failure', [OSError, ValueError])
def test_arch005_committed_cleanup_failure_is_reported_and_recoverable(
    site_root, seo_config, monkeypatch, caplog, failure,
):
    cli, config = seo_config
    backend = PosixPublicationBackend()
    def fail(*args):
        raise failure('cleanup unavailable')
    monkeypatch.setattr(backend, '_cleanup', fail)
    assert build_site(cli, config, site_root, backend=backend).routes > 0
    previous = published(site_root)
    assert 'cleanup pending' in caplog.text
    recover_publication(site_root / 'output', site_root / '.build-cache.json')
    assert published(site_root) == previous


@pytest.mark.parametrize('shared', ['output', 'cache'])
def test_arch005_native_locks_cover_shared_resources_and_release(tmp_path, shared):
    backend = PosixPublicationBackend()
    output, cache = tmp_path / 'output', tmp_path / 'cache.json'
    other_output = output if shared == 'output' else tmp_path / 'other-output'
    other_cache = cache if shared == 'cache' else tmp_path / 'other-cache.json'
    with backend.locked(output, cache):
        with pytest.raises(FileExistsError):
            with backend.locked(other_output, other_cache):
                pytest.fail('concurrent publication accepted')
    with backend.locked(other_output, other_cache):
        pass


@pytest.mark.parametrize('changes', [
    {'version': 2}, {'destination': '/wrong'}, {'cache': '/wrong'}, {'phase': 'unknown'},
    {'stage': '/wrong'}, {'new': [1]}, {'previous': 'bad'}, {'stage_identity': [1, True]},
    {'cache_before': 'not base64'}, {'ownership_before': 42},
])
def test_arch005_journal_field_fuzz_preserves_stage(site_root, seo_config, changes):
    cli, config = seo_config
    backend = PosixPublicationBackend()
    with prepare_build(cli, config, site_root) as prepared:
        checked = validate_generated(render_prepared(prepared))
        publication = publication_input(checked)
        transaction, data = backend._begin(publication)
        data.update(changes)
        (transaction / 'journal.json').write_text(json.dumps(data))
        with pytest.raises(ValueError, match='journal'):
            backend.recover(publication.destination, publication.cache_path)
        assert checked.staged.root.is_dir()
        assert transaction.is_dir()


@pytest.mark.parametrize('phase', ['prepared', 'old_moved', 'installed', 'committed'])
@pytest.mark.parametrize('changes', [
    {'new': None}, {'stage_identity': None}, {'version': True},
    {'new': [-1, 1]}, {'new': [0, -1]}, {'new': [False, 1]},
])
def test_api007_invalid_identity_preserves_recovery_obligations(tmp_path, phase, changes):
    destination, cache = tmp_path / 'output', tmp_path / 'cache.json'
    transaction = tmp_path / '.output.articulous-transaction'
    previous = transaction / 'previous'
    previous.mkdir(parents=True)
    (previous / 'index.html').write_bytes(b'last good generation')
    stage = tmp_path / '.articulous-stage-api007'
    stage.mkdir()
    (stage / 'input.xml').write_bytes(b'captured input')
    data = api007_journal(destination, cache, previous, stage, phase)
    data.update(changes)
    journal = transaction / 'journal.json'
    journal.write_text(json.dumps(data))
    before = snapshot(transaction), snapshot(stage)
    with pytest.raises(ValueError, match='journal'):
        recover_publication(destination, cache)
    assert (snapshot(transaction), snapshot(stage)) == before
    assert not destination.exists()


def api007_journal(destination, cache, previous, stage, phase):
    prior, staged = previous.stat(), stage.stat()
    return {
        'version': 1, 'destination': str(destination), 'cache': str(cache),
        'previous': [prior.st_dev, prior.st_ino], 'new': [staged.st_dev, staged.st_ino],
        'stage': str(stage), 'stage_identity': [staged.st_dev, staged.st_ino],
        'cache_before': None, 'ownership_before': None, 'phase': phase,
    }


def test_arch005_state_hardlink_is_rejected_after_preparation(site_root, seo_config):
    cli, config = seo_config
    with prepare_build(cli, config, site_root) as prepared:
        checked = validate_generated(render_prepared(prepared))
        source = site_root / 'keep.json'
        source.write_text('{}')
        os.link(source, site_root / '.build-cache.json')
        with pytest.raises(ValueError, match='hardlink'):
            publish_validated(checked)
        assert source.read_text() == '{}'


def test_arch005_failed_journal_creation_leaves_previous_generation(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    build_site(cli, config, site_root)
    previous = published(site_root)
    backend = PosixPublicationBackend()
    def fail(*args):
        raise OSError('journal unavailable')
    monkeypatch.setattr(backend, '_set_phase', fail)
    with pytest.raises(OSError, match='journal unavailable'):
        build_site(cli, config, site_root, backend=backend)
    assert published(site_root) == previous
    assert not (site_root / '.output.articulous-transaction').exists()


def test_arch005_rename_never_overwrites_unexpected_destination(tmp_path):
    source, destination = tmp_path / 'source', tmp_path / 'destination'
    source.mkdir()
    destination.mkdir()
    with pytest.raises(ValueError, match='already exists'):
        PosixPublicationBackend()._rename(source, destination)
    assert source.is_dir() and destination.is_dir()


def test_arch005_output_root_must_remain_a_directory(site_root, seo_config):
    cli, config = seo_config
    build_site(cli, config, site_root)
    output = site_root / 'output'
    shutil.rmtree(output)
    output.write_text('manual replacement')
    with pytest.raises(ValueError, match='directory'):
        build_site(cli, config, site_root)
    assert output.read_text() == 'manual replacement'


@pytest.mark.parametrize('relative,directory', [('en/articles/first-post/index.html', True), ('en/articles', False)])
def test_arch005_owned_path_type_changes_are_preserved(site_root, seo_config, relative, directory):
    cli, config = seo_config
    build_site(cli, config, site_root)
    path = site_root / 'output' / relative
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    if directory:
        path.mkdir()
    else:
        path.write_text('manual replacement')
    with pytest.raises(ValueError, match='unowned|regular file'):
        build_site(cli, config, site_root)
    assert path.is_dir() == directory
