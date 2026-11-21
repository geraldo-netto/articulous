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


@pytest.mark.parametrize('relative', ['output', 'cache', 'both'])
def test_review28_35_relative_recovery_paths_create_no_locks(tmp_path, monkeypatch, relative):
    monkeypatch.chdir(tmp_path)
    output = Path('output') if relative != 'cache' else tmp_path / 'output'
    cache = Path('cache') if relative != 'output' else tmp_path / 'cache'
    with pytest.raises(ValueError, match='absolute'):
        recover_publication(output, cache)
    assert list(tmp_path.iterdir()) == []


def test_review28_35_recovery_normalizes_destination_and_configured_cache(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    cache = site_root / '.build-cache.json'
    cache.symlink_to('actual-cache.json')
    backend = PosixPublicationBackend()
    def interrupt(*_):
        raise OSError('cleanup interrupted')
    monkeypatch.setattr(backend, '_cleanup', interrupt)
    build_site(cli, config, site_root, backend=backend)
    transaction = site_root / '.output.articulous-transaction'
    assert transaction.is_dir()
    before = published(site_root)
    recover_publication(site_root / 'content/../output', cache)
    assert not transaction.exists()
    assert cache.is_symlink()
    assert published(site_root) == before


def test_review28_35_rejects_symlinked_destination_before_locking(tmp_path):
    (tmp_path / 'alias').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        recover_publication(tmp_path / 'alias/output', tmp_path / 'cache')
    assert list(tmp_path.iterdir()) == [tmp_path / 'alias']


@pytest.mark.parametrize('stage_path', ['ordinary', 'nested/.articulous-stage-private'])
def test_review28_36_reject_foreign_stage_before_publication(tmp_path, stage_path):
    from articulous.publication_contracts import PublicationInput
    stage = tmp_path / stage_path
    root = stage / 'output'
    root.mkdir(parents=True)
    (stage / 'unrelated').write_bytes(b'user data')
    publication = PublicationInput(root, tmp_path / 'live', tmp_path / 'cache', '{}', {}, {}, lambda: None)
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match='staging path'):
        PosixPublicationBackend().publish(publication)
    assert snapshot(tmp_path) == before
    assert root.is_dir()


def test_arch005_publish_replace_and_incremental_compatibility(site_root, seo_config, cache_clock):
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


@pytest.mark.parametrize('operation', [1, 2, 3, 4])
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
    # AUDIT26-14: an incremental writer must preserve journal recovery.
    from articulous.pipeline import run_build
    with pytest.raises(ValueError, match='publication.*recovery'):
        run_build(cli, config, site_root)
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
    (output / 'manual.txt').unlink()
    output.rmdir()
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
    {'version': 3}, {'destination': '/wrong'}, {'cache': '/wrong'}, {'phase': 'unknown'},
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
        'version': 2, 'cache_after': 'a' * 64, 'destination': str(destination), 'cache': str(cache),
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


def test_rel42_process_death_during_snapshot_recovers_previous_generation(site_root, seo_config):
    cli, config = seo_config
    build_site(cli, config, site_root)
    previous = published(site_root)
    script = '''
import os, sys
from pathlib import Path
from articulous.backends import publication_snapshots
from articulous.configuration_contracts import BuildRequest
from articulous.publication import build_site
original = publication_snapshots.snapshot
def interrupt(source, target):
    original(source, target)
    os._exit(92)
publication_snapshots.snapshot = interrupt
build_site(BuildRequest(), {}, Path(sys.argv[1]))
'''
    result = subprocess.run([sys.executable, '-c', script, str(site_root)],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True)
    assert result.returncode == 92, result.stderr.decode()
    assert published(site_root) == previous
    recover_publication(site_root / 'output', site_root / '.build-cache.json')
    assert published(site_root) == previous
    assert not list(site_root.glob('.articulous-stage-*'))
    assert not (site_root / '.output.articulous-transaction').exists()


@pytest.mark.parametrize('claimed', ['cache_before', 'ownership_before'])
def test_rel42_rejects_inconsistent_capture_intent(claimed):
    from articulous.backends.posix import _validate_phase

    with pytest.raises(ValueError, match='Invalid snapshot capture phase'):
        data = {'phase': 'capturing', 'cache_before': None, 'ownership_before': None}
        data[claimed] = [0, 1, 'a' * 64]
        _validate_phase(data)


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


def test_rel40_delayed_rollback_preserves_other_root_activity(site_root, seo_config, cache_clock):
    cli, config = seo_config
    run_build(cli, config, site_root)
    script = '''
import os, sys
from pathlib import Path
from articulous.backends.posix import PosixPublicationBackend
from articulous.configuration_contracts import BuildRequest
from articulous.publication import build_site
class Interrupted(PosixPublicationBackend):
    def _set_phase(self, path, data, phase):
        super()._set_phase(path, data, phase)
        if phase == "installed":
            os._exit(91)
build_site(BuildRequest(), {"paths":{"output_dir":"other"}}, Path(sys.argv[1]),
           backend=Interrupted())
'''
    result = subprocess.run([sys.executable, '-c', script, str(site_root)],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True)
    assert result.returncode == 91, result.stderr.decode()
    cache_clock[0] += 100
    run_build(cli, config, site_root)
    cache = site_root / '.build-cache.json'
    before = cache.read_bytes()
    recover_publication(site_root / 'other', cache)
    assert cache.read_bytes() == before
    assert not (site_root / 'other').exists()


@pytest.mark.parametrize('existing', [False, True])
def test_compat03_version_one_journal_preserves_state_for_manual_recovery(site_root, seo_config, existing):
    import base64

    cli, config = seo_config
    backend = PosixPublicationBackend()
    if existing:
        build_site(cli, config, site_root)
    before = published(site_root) if existing else (None, None, None)
    with prepare_build(cli, config, site_root) as prepared:
        checked = validate_generated(render_prepared(prepared))
        publication = publication_input(checked)
        transaction, data = backend._begin(publication)
        data['version'] = 1
        data.pop('cache_after')
        for key, value in zip(('cache_before', 'ownership_before'), before[1:]):
            data[key] = base64.b64encode(value).decode() if value is not None else None
        backend._set_phase(transaction, data, 'prepared')
        retained = snapshot(transaction), snapshot(publication.root)
        with pytest.raises(ValueError, match='preserve it for recovery'):
            backend.recover(publication.destination, publication.cache_path)
        assert (snapshot(transaction), snapshot(publication.root)) == retained
    if existing:
        assert published(site_root) == before
    else:
        assert not any((site_root / name).exists() for name in (
            'output', '.build-cache.json', '.output.articulous-ownership.json',
        ))


@pytest.mark.parametrize('mutation', ['bytes', 'identity', 'hardlink'])
def test_perf17_reject_damaged_snapshots_before_rollback(site_root, seo_config, mutation):
    cli, config = seo_config
    backend = PosixPublicationBackend()
    build_site(cli, config, site_root)
    with prepare_build(cli, config, site_root) as prepared:
        publication = publication_input(validate_generated(render_prepared(prepared)))
        transaction, _ = backend._begin(publication)
        saved = transaction / 'cache.before'
        if mutation == 'bytes':
            saved.write_bytes(b'changed')
        elif mutation == 'identity':
            other = transaction / 'other'
            other.write_bytes(saved.read_bytes())
            other.replace(saved)
        else:
            os.link(saved, transaction / 'other')
        before = published(site_root)
        with pytest.raises(ValueError, match='Invalid publication journal'):
            backend.recover(publication.destination, publication.cache_path)
        assert published(site_root) == before
        assert transaction.is_dir()


@pytest.mark.parametrize('changes', [{'version': 2, 'surplus': None}, []])
def test_perf17_reject_invalid_journal_shape(tmp_path, changes):
    from articulous.backends.posix import _validate_journal_header

    with pytest.raises(ValueError, match='Invalid journal fields'):
        _validate_journal_header(changes, tmp_path / 'output', tmp_path / 'cache')


@pytest.mark.parametrize('claim', [[0, 1], [-1, 2, 'a' * 64], [1, True, 'a' * 64], [1, 2, 'bad']])
def test_perf17_reject_invalid_snapshot_claims(claim):
    from articulous.backends.publication_snapshots import validate_claim

    with pytest.raises(ValueError, match='Invalid publication'):
        validate_claim(claim)


@pytest.mark.parametrize('during_merge', [False, True])
def test_perf17_changed_bytes_cannot_overwrite_current_state(tmp_path, during_merge):
    from articulous.backends import publication_snapshots as state

    cache, backup = tmp_path / 'cache', tmp_path / 'backup'
    cache.write_text('{"one":1}')
    claim = state.snapshot(cache, backup)
    backup.write_text('{"bad":1}')
    cache.write_text('{"one":2}')
    with pytest.raises(ValueError, match='snapshot bytes changed'):
        if during_merge:
            state.restore_cache(cache, backup, claim, 'x', 'active')
        else:
            state.restore_snapshot(cache, backup, claim)
    assert cache.read_text() == '{"one":2}'


@pytest.mark.parametrize('prior,current,merged', [
    ({'active': 1}, {'active': 2}, {'active': 1, 'other': 2}),
    ({'active': 1}, {'active': 1}, {'active': 1, 'other': 2}),
    ({'active': 1}, {}, {'active': 1, 'other': 2}),
    (None, {'active': 2}, {'other': 2}),
    (None, {}, {'other': 2}),
])
def test_rel40_merge_only_restores_the_recovering_root(tmp_path, prior, current, merged):
    from articulous.backends import publication_snapshots as state

    cache, backup = tmp_path / 'cache', tmp_path / 'backup'
    if prior is not None:
        cache.write_text(json.dumps({'__output_roots__': prior}))
    claim = state.snapshot(cache, backup)
    cache.write_text(json.dumps({'__output_roots__': {'other': 2, **current}}))
    state.restore_cache(cache, backup, claim, 'x', 'active')
    assert json.loads(cache.read_text()) == {'__output_roots__': merged}


def test_rel40_recovery_with_missing_or_invalid_cache(tmp_path):
    from articulous.backends import publication_snapshots as state

    cache, backup = tmp_path / 'cache', tmp_path / 'backup'
    cache.write_text('{"one":1}')
    claim = state.snapshot(cache, backup)
    cache.unlink()
    state.restore_cache(cache, backup, claim, 'x', 'active')
    assert cache.read_text() == '{"one":1}'
    cache.write_text('[]')
    with pytest.raises(ValueError, match='Invalid shared cache'):
        state.restore_cache(cache, backup, claim, 'x', 'active')


def test_review29_01_recheck_staged_bytes_after_journal_preparation(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    build_site(cli, config, site_root)
    before = published(site_root)
    backend = PosixPublicationBackend()
    begin = backend._begin
    with prepare_build(cli, config, site_root) as prepared:
        staged = render_prepared(prepared)
        checked = validate_generated(staged)
        feed = staged.root / 'rss.xml'
        verified = feed.read_bytes()

        def edit_after_capture(publication):
            journal = begin(publication)
            feed.write_bytes(b'late edit')
            return journal

        with monkeypatch.context() as changes:
            changes.setattr(backend, '_begin', edit_after_capture)
            with pytest.raises(ValueError, match='changed'):
                publish_validated(checked, backend=backend)
        assert published(site_root) == before
        assert prepared.state == 'validated'
        assert not (site_root / '.output.articulous-transaction').exists()
        feed.write_bytes(verified)
        publish_validated(checked, backend=backend)
        assert prepared.state == 'published'


def test_review28_39_native_handoff_streams_cache_and_routes(site_root, seo_config, monkeypatch, cache_clock):
    from uuid import uuid4
    from articulous.pipeline import OutputManifest
    from articulous.ownership import ownership_payload
    from articulous.composition import route_cache_data
    generation = uuid4()
    monkeypatch.setattr('articulous.publication_adapter.uuid4', lambda: generation)
    cli, config = seo_config
    with prepare_build(cli, config, site_root) as prepared:
        checked = validate_generated(render_prepared(prepared))
        expected = publication_input(checked)
        monkeypatch.setattr(OutputManifest, 'route_values', lambda *_: pytest.fail('materialized all publication routes'))
        publish_validated(checked)
        assert expected.cache_path.read_bytes() == expected.cache_text.encode()
        owners = ownership_payload(expected.destination, dict(expected.output_owners), route_cache_data(expected.output_routes),
                                   generation=expected.generation, translations=dict(expected.translations))
        assert (site_root / '.output.articulous-ownership.json').read_bytes() == json.dumps(owners, indent=2, sort_keys=True).encode()


def test_review28_39_wrapped_backend_keeps_materialized_contract(site_root, seo_config):
    from functools import update_wrapper
    from articulous.publication_contracts import PublicationInput
    class Recorder(PosixPublicationBackend):
        def publish(self, publication):
            assert isinstance(publication, PublicationInput)
            assert isinstance(publication.cache_text, str)
            super().publish(publication)

    update_wrapper(Recorder.publish, PosixPublicationBackend.publish)
    cli, config = seo_config
    assert build_site(cli, config, site_root, backend=Recorder()).routes > 0


@pytest.mark.parametrize('which', ['cache', 'ownership'])
def test_review28_39_changed_staged_state_rolls_back_exact_bytes(site_root, seo_config, monkeypatch, which):
    cli, config = seo_config
    build_site(cli, config, site_root)
    previous = published(site_root)
    backend = PosixPublicationBackend()
    write = backend._write_state
    def corrupt(publication):
        getattr(publication, which).path.write_bytes(b'changed')
        write(publication)
    monkeypatch.setattr(backend, '_write_state', corrupt)
    with pytest.raises(ValueError, match='Staged publication state changed'):
        build_site(cli, config, site_root, backend=backend)
    assert published(site_root) == previous
    assert not list(site_root.glob('.articulous-stage-*'))


def test_review28_39_failed_json_writes_release_catalog_readers(site_root, seo_config, monkeypatch):
    from contextlib import contextmanager
    from articulous import publication_adapter
    cli, config = seo_config
    original = Path.open
    retained = []
    with prepare_build(cli, config, site_root) as prepared:
        checked = validate_generated(render_prepared(prepared))
        routes = publication_adapter._owned_validated(checked)._staged._owner.routes

        @contextmanager
        def interrupt(path, *args, **kwargs):
            with original(path, *args, **kwargs) as stream:
                if path.name == 'cache.json' and args == ('xb',):
                    write = stream.write
                    def fail_when_reading(data):
                        if routes._readers:
                            raise OSError('interrupted state write')
                        return write(data)
                    stream.write = fail_when_reading
                yield stream

        with monkeypatch.context() as fault:
            fault.setattr(Path, 'open', interrupt)
            for _ in range(3):
                with pytest.raises(OSError, match='interrupted state write') as failure:
                    publish_validated(checked)
                retained.append(failure)
                assert not routes._readers
        publish_validated(checked)
        assert not routes._readers


@pytest.mark.parametrize('sorted_keys', [False, True])
def test_review28_39_streamed_json_preserves_serialized_bytes(tmp_path, sorted_keys):
    from hashlib import sha256
    from random import Random
    from articulous.publication_json import stage_json
    random = Random(39)
    keys = ['á', '\n', '"', '\\', '日', '']
    values = [None, 12, False, ['\n', {'⌛': True}], {}, [[], {'x': '\x00'}]]
    for case in range(24):
        sample = {key: random.choice(values) for key in random.sample(keys, random.randrange(len(keys) + 1))}
        expected = json.dumps(sample, indent=2, sort_keys=sorted_keys).encode()
        staged = stage_json(tmp_path / str(case), sample, sorted_keys=sorted_keys)
        assert staged.path.read_bytes() == expected
        assert staged.digest == sha256(expected).hexdigest()
    with pytest.raises(TypeError, match='keys must be strings'):
        stage_json(tmp_path / 'invalid', {2: None})
