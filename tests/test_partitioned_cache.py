"""PERF-31 and PERF-37: root-local fingerprints, migration and isolation."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from articulous import cache_store, cache_usage_index, pipeline, publication_adapter
from articulous.backends.posix import PosixPublicationBackend
from articulous.builds import check_build
from articulous.cache_activity import CacheActivity, activity_path, retirement_queue
from articulous.config import normalize_configuration
from articulous.configuration_contracts import BuildRequest, ConfigurationError
from articulous.filesystem import cache_lock_path, lock_file
from articulous.ownership import ownership_path
from articulous.publication import build_site, lock_site, recover_publication
from articulous.publication_contracts import PublicationInput
from articulous.publication_paths import transaction_path

DAY = 86_400
REQUEST = BuildRequest()


def _config(name='output', enable=True, days=3):
    return {'paths': {'output_dir': name},
            'build': {'partition_cache': enable, 'cache_retention_days': days, 'parallelism': 2}}


def _base(root):
    return root / '.build-cache.json'


def _selected(root, name):
    return cache_store.select_cache(_base(root), root / name)


def _record(root, name):
    return json.loads(_selected(root, name).path.read_text())['__output_roots__'][str(root / name)]


def _used(site_root, name):
    cache = _selected(site_root, name).path
    return CacheActivity(cache, _base(site_root)).used(str(site_root / name), _record(site_root, name))


@pytest.mark.parametrize('seed', range(4))
def test_perf31_partition_setting_rejects_non_boolean_values(site_root, seed):
    rng = random.Random(seed)
    for invalid in (None, 0, 1, rng.getrandbits(256), rng.random(), [], {}, 'true'):
        with pytest.raises(ConfigurationError, match='build.partition_cache'):
            normalize_configuration({'build': {'partition_cache': invalid}}, REQUEST, site_root)
    for value in (False, True):
        config = normalize_configuration({'build': {'partition_cache': value}}, REQUEST, site_root)
        assert config['build']['partition_cache'] is value


def test_perf31_migrates_shared_roots_and_admits_only_active_records(site_root, cache_clock, monkeypatch):
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    pipeline.run_build(REQUEST, _config('second', enable=False), site_root)
    second = _record(site_root, 'second')
    cache_clock[0] += DAY
    pipeline.run_build(REQUEST, _config(), site_root)
    assert _selected(site_root, 'output').partitioned
    assert _record(site_root, 'second') == second
    old = _base(site_root).read_bytes()
    reads = []
    load = pipeline.load_cache

    def observe(path):
        reads.append(path)
        return load(path)

    monkeypatch.setattr(pipeline, 'load_cache', observe)
    cache_clock[0] += 1
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    assert reads == [_selected(site_root, 'output').path]
    assert _base(site_root).read_bytes() == old
    assert _used(site_root, 'output') == cache_clock[0]


def test_perf31_custom_backend_keeps_cache_text_and_active_path_contract(site_root, monkeypatch):
    class Recorder(PosixPublicationBackend):
        def publish(self, publication):
            assert isinstance(publication, PublicationInput)
            assert isinstance(publication.cache_text, str)
            assert publication.cache_path == _selected(site_root, 'output').path
            roots = json.loads(publication.cache_text)['__output_roots__']
            assert set(roots) == {str(publication.destination)}
            super().publish(publication)

    pipeline.run_build(REQUEST, _config('second'), site_root)
    cache = _selected(site_root, 'second').path
    before = cache.read_bytes()
    loads = []
    load = publication_adapter.load_cache

    def observe(path):
        loads.append(path)
        return load(path)

    monkeypatch.setattr(publication_adapter, 'load_cache', observe)
    build_site(REQUEST, _config(), site_root, backend=Recorder())
    assert loads == [_selected(site_root, 'output').path]
    assert cache.read_bytes() == before


def test_perf31_dry_run_and_check_leave_layout_and_fingerprints_unchanged(site_root, cache_clock):
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    prior = _base(site_root).read_bytes()
    cache_clock[0] += 4 * DAY
    pipeline.run_build(BuildRequest(dry_run=True), _config('second'), site_root)
    check_build(REQUEST, _config('second'), site_root)
    assert not _selected(site_root, 'output').partitioned
    assert _base(site_root).read_bytes() == prior
    pipeline.run_build(REQUEST, _config(), site_root)
    active = _selected(site_root, 'output').path
    before = active.read_bytes()
    cache_clock[0] += 4 * DAY
    pipeline.run_build(BuildRequest(dry_run=True), _config('second'), site_root)
    check_build(REQUEST, _config('second'), site_root)
    assert active.read_bytes() == before


@pytest.mark.parametrize('age,days,expired', [(3 * DAY - 1, 3, False), (3 * DAY, 3, True), (0, 0, True)])
def test_perf31_partition_retention_preserves_ownership(site_root, cache_clock, age, days, expired):
    pipeline.run_build(REQUEST, _config(), site_root)
    output = site_root / 'output'
    owner = ownership_path(output).read_bytes()
    page = (output / 'rss.xml').read_bytes()
    cache_clock[0] += age
    build_site(REQUEST, _config('second', days=days), site_root)
    assert _selected(site_root, 'output').path.exists() is not expired
    assert ownership_path(output).read_bytes() == owner
    assert (output / 'rss.xml').read_bytes() == page
    if expired:
        pipeline.run_build(BuildRequest(only_sections=('rss',)), _config(), site_root)
        assert _selected(site_root, 'output').path.is_file()


def test_perf31_undated_records_remain_available_after_migration(site_root, cache_clock):
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    raw = json.loads(_base(site_root).read_text())
    raw['__output_roots__'][str(site_root / 'output')].pop('__last_used__')
    owner = ownership_path(site_root / 'output').read_bytes()
    _base(site_root).write_text(json.dumps(raw))
    cache_clock[0] += 4 * DAY
    pipeline.run_build(REQUEST, _config('second', days=0), site_root)
    assert '__last_used__' not in _record(site_root, 'output')
    pipeline.run_build(REQUEST, _config('third', days=0), site_root)
    assert _selected(site_root, 'output').path.is_file()
    assert ownership_path(site_root / 'output').read_bytes() == owner
    pipeline.run_build(REQUEST, _config(), site_root)
    assert json.loads(ownership_path(site_root / 'output').read_bytes())["paths"] == json.loads(owner)["paths"]


def test_rel43_losing_partitions_cannot_reuse_retired_shared_fingerprints(site_root):
    pipeline.run_build(REQUEST, _config(), site_root)
    page = site_root / 'output/en/articles/first-post/index.html'
    original_output = page.read_bytes()
    source = site_root / 'content/en/first-post.xml'
    original_source = source.read_text()
    source.write_text(original_source.replace('Inaugural article.', 'Changed after partitioning.'))
    pipeline.run_build(REQUEST, _config(), site_root)
    assert page.read_bytes() != original_output
    source.write_text(original_source)
    shutil.rmtree(cache_store.cache_namespace(_base(site_root)))
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    assert page.read_bytes() == original_output


def test_perf37_disjoint_builds_overlap_and_same_root_is_excluded(site_root):
    pipeline.run_build(REQUEST, _config(), site_root)
    concurrent = Barrier(2)

    def validate(_stage):
        concurrent.wait(timeout=20)

    with ThreadPoolExecutor(max_workers=2) as pool:
        submissions = [pool.submit(build_site, REQUEST, _config(name), site_root, validators=(validate,))
                       for name in ('output', 'second')]
        assert all(task.result().routes > 0 for task in submissions)
    with lock_site(REQUEST, _config(), site_root):
        with pytest.raises(FileExistsError):
            build_site(REQUEST, _config(), site_root)
        pipeline.run_build(REQUEST, _config('third', days=0), site_root)
        assert _selected(site_root, 'output').path.is_file()
    pipeline.run_build(REQUEST, _config('third', days=0), site_root)
    assert not _selected(site_root, 'output').path.exists()


def _interrupt_publication(site_root, output, phase='installed'):
    script = '''
import os, sys
from pathlib import Path
from articulous.backends.posix import PosixPublicationBackend
from articulous.configuration_contracts import BuildRequest
from articulous.publication import build_site
class Interrupted(PosixPublicationBackend):
    def _set_phase(self, path, data, phase):
        super()._set_phase(path, data, phase)
        if phase == sys.argv[3]:
            os._exit(91)
build_site(BuildRequest(), {"paths":{"output_dir":sys.argv[2]}}, Path(sys.argv[1]),
           backend=Interrupted())
'''
    result = subprocess.run([sys.executable, '-c', script, str(site_root), output, phase],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True)
    assert result.returncode == 91, result.stderr.decode()


def test_perf37_publication_recovery_uses_active_root_after_interruption(site_root, cache_clock):
    pipeline.run_build(REQUEST, _config(), site_root)
    build_site(REQUEST, _config('second'), site_root)
    second = _selected(site_root, 'second').path
    before = second.read_bytes()
    _interrupt_publication(site_root, 'second')
    cache_clock[0] += 4 * DAY
    pipeline.run_build(REQUEST, _config(), site_root)
    first = _selected(site_root, 'output').path
    newer = first.read_bytes()
    assert second.exists()
    recover_publication(site_root / 'second', _base(site_root))
    assert second.read_bytes() == before
    assert first.read_bytes() == newer
    assert not transaction_path(site_root / 'second').exists()


def test_perf31_migration_waits_for_pending_legacy_journals(site_root, caplog):
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    _interrupt_publication(site_root, 'nested/second', 'prepared')
    pipeline.run_build(REQUEST, _config(), site_root)
    assert not _selected(site_root, 'output').partitioned
    assert 'partitioning pending recovery' in caplog.text
    recover_publication(site_root / 'nested/second', _base(site_root))
    pipeline.run_build(REQUEST, _config(), site_root)
    assert _selected(site_root, 'output').partitioned


def test_perf37_lock_selection_retries_if_layout_changes_before_lock(site_root):
    base = _base(site_root)
    root = site_root / 'output'
    paths = []

    @contextmanager
    def lock(path):
        paths.append(path)
        with lock_file(cache_lock_path(path)):
            if path == base:
                cache_store.finish_cache_update(_selected(site_root, 'output'), 3, True)
            yield

    with cache_store.lock_selected_cache(base, root, lock) as selected:
        assert selected.partitioned
    assert paths == [base, selected.path]


def test_perf31_refuses_aliased_cache_namespace_and_partitions(site_root):
    namespace = cache_store.cache_namespace(_base(site_root))
    overlap = _config(namespace.name + '/html')
    with pytest.raises(ValueError, match='overlaps fingerprint cache'):
        pipeline.run_build(REQUEST, overlap, site_root)
    namespace.mkdir()
    with pytest.raises(ValueError, match='Unrecognized fingerprint cache'):
        pipeline.run_build(REQUEST, _config(), site_root)
    namespace.rmdir()
    pipeline.run_build(REQUEST, _config(), site_root)
    cache = _selected(site_root, 'output').path
    os.link(cache, site_root / 'unexpected')
    with pytest.raises(ValueError, match='multiple hardlinks'):
        pipeline.run_build(REQUEST, _config(), site_root)


@pytest.mark.parametrize('raw,blocks', [('invalid', True), ('[]', True), ('{"cache":"/other"}', False)])
def test_perf31_activation_distinguishes_pending_journal_identity(tmp_path, raw, blocks):
    base = _base(tmp_path)
    pending = transaction_path(tmp_path / 'other')
    pending.mkdir()
    (pending / 'journal.json').write_text(raw)
    assert cache_store._has_pending_journal(base, tmp_path) is blocks


def test_perf31_activation_preserves_state_if_directory_cannot_be_scanned(tmp_path, monkeypatch, caplog):
    base = _base(tmp_path)
    base.write_text('{"fingerprint": [1]}')
    selected = cache_store.select_cache(base, tmp_path / 'output')

    def unreadable(*args, onerror):
        onerror(PermissionError('unreadable directory'))

    monkeypatch.setattr(cache_store.os, 'walk', unreadable)
    cache_store.finish_cache_update(selected, 3, True)
    assert base.read_text() == '{"fingerprint": [1]}'
    assert 'cache maintenance failed: unreadable directory' in caplog.text


@pytest.mark.parametrize('value', [None, '{"fingerprint":[1]}', '{"__output_roots__": []}'])
def test_compat01_partition_activation_discards_unscoped_fingerprints(tmp_path, value):
    base = _base(tmp_path)
    if value is not None:
        base.write_text(value)
    destination = tmp_path / 'output'
    cache_store.finish_cache_update(cache_store.select_cache(base, destination), 3, True)
    selected = cache_store.select_cache(base, destination)
    assert selected.partitioned
    assert not selected.path.exists()
    assert json.loads(base.read_text()) == {'__output_roots__': {}}


def test_perf31_malformed_root_paths_are_ignored(tmp_path):
    base = _base(tmp_path)
    invalid_paths = ('relative', str(tmp_path.parent), str(tmp_path / 'bad\0path'))
    value = {'__output_roots__': dict.fromkeys(invalid_paths, {'fingerprint': [1]})}
    base.write_text(json.dumps(value))
    assert cache_store._migration_records(base, tmp_path) == {}


@pytest.mark.parametrize('fault', ['hardlink', 'wrong-root', 'not-string', 'missing'])
def test_perf31_does_not_expire_unverified_cache_headers(tmp_path, fault):
    namespace = cache_store.cache_namespace(_base(tmp_path))
    namespace.mkdir()
    path = cache_store._root_path(namespace, str(tmp_path / 'output'))
    if fault != 'missing':
        other = 42 if fault == 'not-string' else str(tmp_path / 'other')
        path.write_text(json.dumps({'__output_roots__': {other: {'__last_used__': 0}}}, indent=2))
    if fault == 'hardlink':
        os.link(path, namespace / 'unknown')
    cache_store._prune_root(path, None, tmp_path, _base(tmp_path))
    assert path.exists() is (fault != 'missing')


def _seed_partition(active, name, timestamp):
    root = str(active.parent.parent / name)
    path = cache_store._root_path(active.parent, root)
    value = cache_store.partitioned_payload({root: {'__last_used__': timestamp}})
    path.write_text(json.dumps(value, indent=2))
    return path


def _expiry_fixture(tmp_path):
    namespace = cache_store.cache_namespace(_base(tmp_path))
    namespace.mkdir()
    active = cache_store._root_path(namespace, str(tmp_path / 'active'))
    return active, namespace / 'expiry-v1'


def test_perf41_reuses_stable_headers_and_invalidates_in_place_updates(tmp_path, cache_clock, monkeypatch):
    active, index = _expiry_fixture(tmp_path)
    path = _seed_partition(active, 'other', cache_clock[0])
    cache_store._expire_partitions(active, 3, tmp_path, _base(tmp_path))
    expected = cache_usage_index.read_usage_index(index)
    assert expected[path.name][-1] == cache_clock[0]
    reads = []
    read = cache_store._read_usage

    def observe(candidate, project):
        reads.append(candidate)
        return read(candidate, project)

    monkeypatch.setattr(cache_store, '_read_usage', observe)
    cache_store._expire_partitions(active, 3, tmp_path, _base(tmp_path))
    assert reads == []
    metadata = path.stat()
    _seed_partition(active, 'other', cache_clock[0] - 4 * DAY)
    os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    assert path.stat().st_size == metadata.st_size
    cache_store._expire_partitions(active, 3, tmp_path, _base(tmp_path))
    assert reads == [path, path]
    assert not path.exists()
    assert cache_usage_index.read_usage_index(index) == {}


def test_perf41_expiry_hint_cannot_delete_a_refreshed_partition(tmp_path, cache_clock, monkeypatch):
    active, _ = _expiry_fixture(tmp_path)
    target = _seed_partition(active, 'other', cache_clock[0])
    expired = cache_clock[0] - 4 * DAY
    monkeypatch.setattr(cache_store, 'reusable_usage', lambda *_: [0, 0, 0, 0, 0, expired])
    cache_store._expire_partitions(active, 3, tmp_path, _base(tmp_path))
    assert target.is_file()


def test_perf41_retention_still_visits_all_partitions_when_index_is_full(tmp_path, cache_clock, monkeypatch):
    monkeypatch.setattr(cache_usage_index, '_MAX_ENTRIES', 1)
    active, index = _expiry_fixture(tmp_path)
    fresh = [_seed_partition(active, f'fresh-{i}', cache_clock[0]) for i in range(4)]
    expired = [_seed_partition(active, f'old-{i}', cache_clock[0] - 4 * DAY) for i in range(4)]
    cache_store._expire_partitions(active, 3, tmp_path, _base(tmp_path))
    assert all(path.is_file() for path in fresh)
    assert not any(path.exists() for path in expired)
    assert len(cache_usage_index.read_usage_index(index)) == 1


def _index_message(payload):
    return sha256(payload).hexdigest().encode() + b'\n' + payload


@pytest.mark.parametrize('payload', [b'[]', b'{oops', b'[' * 2000 + b']' * 2000],
                         ids=['array', 'invalid-json', 'deeply-nested'])
def test_rel44_bad_index_payloads_fall_back_to_authoritative_headers(tmp_path, cache_clock, payload):
    active, index = _expiry_fixture(tmp_path)
    target = _seed_partition(active, 'other', cache_clock[0] - 4 * DAY)
    index.write_bytes(_index_message(payload))
    cache_store._expire_partitions(active, 3, tmp_path, _base(tmp_path))
    assert not target.exists()


def test_perf41_index_corruption_rebuilds_hints(tmp_path, cache_clock):
    active, index = _expiry_fixture(tmp_path)
    target = _seed_partition(active, 'other', cache_clock[0])
    cache_store._expire_partitions(active, 3, tmp_path, _base(tmp_path))
    expected = index.read_bytes()
    index.write_bytes(expected[:-1] + b' ')
    cache_store._expire_partitions(active, 3, tmp_path, _base(tmp_path))
    assert target.is_file()
    assert index.read_bytes() == expected


def test_perf41_changes_during_header_read_do_not_admit_a_partition(tmp_path, cache_clock, monkeypatch):
    active, index = _expiry_fixture(tmp_path)
    target = _seed_partition(active, 'other', cache_clock[0] - 4 * DAY)
    generations = iter(([1], [2]))
    monkeypatch.setattr(cache_store, 'file_generation', lambda _: next(generations))
    cache_store._expire_partitions(active, 3, tmp_path, _base(tmp_path))
    assert target.is_file()
    assert not index.exists()


def test_perf41_missing_candidate_makes_its_hint_unusable(tmp_path, cache_clock):
    active, _ = _expiry_fixture(tmp_path)
    path = _seed_partition(active, 'other', cache_clock[0])
    observation = [*cache_usage_index.file_generation(path.stat()), cache_clock[0]]
    with os.scandir(path.parent) as directory:
        entry = next(directory)
        path.unlink()
        assert cache_usage_index.reusable_usage(entry, observation) is None


def test_perf41_oversized_index_is_optional(tmp_path, cache_clock, monkeypatch):
    monkeypatch.setattr(cache_usage_index, '_MAX_FILE_BYTES', 32)
    active, index = _expiry_fixture(tmp_path)
    _seed_partition(active, 'fresh', cache_clock[0])
    expired = _seed_partition(active, 'old', cache_clock[0] - 4 * DAY)
    original = b'x' * 33
    index.write_bytes(original)
    cache_store._expire_partitions(active, 3, tmp_path, _base(tmp_path))
    assert not expired.exists()
    assert index.read_bytes() == original


def test_perf41_index_size_change_during_read_discards_hints(tmp_path, monkeypatch):
    _, index = _expiry_fixture(tmp_path)
    index.write_bytes(_index_message(b'{"root":[1,2,3,4,5,6]}'))
    fstat = os.fstat

    def observe(fd):
        metadata = fstat(fd)
        return SimpleNamespace(st_mode=metadata.st_mode, st_size=metadata.st_size + 1,
                               st_nlink=metadata.st_nlink)

    monkeypatch.setattr(cache_usage_index.os, 'fstat', observe)
    assert cache_usage_index.read_usage_index(index) == {}


def test_perf41_index_failure_preserves_cache_authority(tmp_path, cache_clock):
    active, index = _expiry_fixture(tmp_path)
    _seed_partition(active, 'fresh', cache_clock[0])
    expired = _seed_partition(active, 'old', cache_clock[0] - 4 * DAY)
    unrelated = tmp_path / 'keep'
    unrelated.write_text('untouched')
    index.symlink_to(unrelated)
    cache_store._expire_partitions(active, 3, tmp_path, _base(tmp_path))
    assert not expired.exists()
    assert unrelated.read_text() == 'untouched'
    assert index.is_symlink()


def test_review28_23_symlinked_cache_migration_and_retention(site_root, cache_clock):
    base = site_root / 'state/cache.json'
    base.parent.mkdir()
    _base(site_root).symlink_to(base)
    pipeline.run_build(REQUEST, _config('first', enable=False), site_root)
    pipeline.run_build(REQUEST, _config(), site_root)
    first = cache_store.partition_path(base, site_root / 'first')
    assert str(site_root / 'first') in json.loads(first.read_bytes())['__output_roots__']
    cache_clock[0] += 4 * DAY
    pipeline.run_build(REQUEST, _config(), site_root)
    assert not first.exists()


def test_review28_23_journal_blocks_aliased_cache_activation(site_root):
    target = site_root / 'state/cache.json'
    target.parent.mkdir()
    _base(site_root).symlink_to(target)
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    _interrupt_publication(site_root, 'nested/second', 'prepared')
    pipeline.run_build(REQUEST, _config(), site_root)
    assert not cache_store.select_cache(target, site_root / 'output').partitioned
    recover_publication(site_root / 'nested/second', _base(site_root))
    pipeline.run_build(REQUEST, _config(), site_root)
    assert cache_store.select_cache(target, site_root / 'output').partitioned


@pytest.mark.parametrize('partitioned', [False, True], ids=['migration', 'retention'])
def test_review29_02_unrelated_cyclic_output_does_not_abort_cache_update(site_root, cache_clock, partitioned):
    pipeline.run_build(REQUEST, _config('former', enable=partitioned), site_root)
    prior = site_root / 'former'
    shard = cache_store.partition_path(_base(site_root), prior)
    prior.rename(site_root / 'moved')
    prior.symlink_to(prior.name)
    pipeline.run_build(REQUEST, _config('active'), site_root)
    cache_clock[0] += 4 * DAY
    pipeline.run_build(REQUEST, _config('current'), site_root)
    assert _record(site_root, 'current')['__last_used__'] == cache_clock[0]
    assert not _selected(site_root, 'active').path.exists()
    assert shard.exists() is partitioned
    assert prior.is_symlink()


@pytest.mark.parametrize('build', [pipeline.run_build, build_site])
def test_review28_24_nested_partition_headers_do_not_fail_committed_builds(site_root, cache_clock, build):
    pipeline.run_build(REQUEST, _config('expired'), site_root)
    old = _selected(site_root, 'expired')
    cache_clock[0] += 4 * DAY
    for i, depth in enumerate((1, 64, sys.getrecursionlimit() * 2)):
        junk = old.path.with_name(f'{i:064x}.json')
        junk.write_bytes(b'{\n  "__output_roots__": {\n' + b'[' * depth + b']' * depth + b'\n')
    build(REQUEST, _config(), site_root)
    assert (site_root / 'output/rss.xml').is_file()
    assert not old.path.exists()
    assert _used(site_root, 'output') == cache_clock[0]
    assert all(old.path.with_name(f'{i:064x}.json').exists() for i in range(3))


def test_review28_25_build_admission_during_partition_expiry(site_root, cache_clock, monkeypatch):
    pipeline.run_build(REQUEST, _config(), site_root)
    cache_clock[0] += 4 * DAY
    root = site_root / 'output'
    checking, selected, release = Event(), Event(), Event()
    eligible = cache_store._eligible_for_pruning
    select = cache_store.select_cache

    def pause_expiry(usage, cutoff):
        if usage and usage[0] == str(root):
            checking.set()
            assert release.wait(10)
        return eligible(usage, cutoff)

    def observe_selection(base, destination, project=None):
        result = select(base, destination, project)
        if destination == root:
            selected.set()
        return result

    monkeypatch.setattr(cache_store, '_eligible_for_pruning', pause_expiry)
    monkeypatch.setattr(cache_store, 'select_cache', observe_selection)
    with ThreadPoolExecutor(max_workers=2) as pool:
        maintenance = pool.submit(pipeline.run_build, REQUEST, _config('second'), site_root)
        try:
            assert checking.wait(10)
            build = pool.submit(pipeline.run_build, REQUEST, _config(), site_root)
            assert selected.wait(10)
            with pytest.raises(TimeoutError):
                build.result(timeout=0.1)
        finally:
            release.set()
        maintenance.result()
        build.result()
    assert _used(site_root, 'output') == cache_clock[0]
    assert _record(site_root, 'second')['__last_used__'] == cache_clock[0]


def test_review28_25_expiry_skips_namespace_during_writer_admission(site_root, cache_clock):
    from articulous.filesystem import partition_directory_lock
    pipeline.run_build(REQUEST, _config(), site_root)
    active = _selected(site_root, 'output').path
    cache_clock[0] += 4 * DAY
    with partition_directory_lock(active.parent):
        assert not cache_store._prune_root(active, None, site_root, _base(site_root))
        assert active.is_file()
    assert cache_store._prune_root(active, None, site_root, _base(site_root))
    assert not active.exists()


@pytest.mark.parametrize('partitioned', [False, True], ids=['shared', 'partitioned'])
@pytest.mark.parametrize('stamp,rebuild', [
    ({}, True), ({'__last_used__': None}, True), ({'__last_used__': -1}, True),
    ({'__last_used__': False}, True), ({'__last_used__': '0'}, True),
    ({'__last_used__': 0}, False),
])
def test_compat06_active_cache_requires_valid_activity(site_root, cache_clock, partitioned, stamp, rebuild):
    config = _config(enable=partitioned)
    pipeline.run_build(REQUEST, config, site_root)
    output = site_root / 'output'
    cache_path = _selected(site_root, 'output').path
    cache = json.loads(cache_path.read_text())
    record = cache['__output_roots__'][str(output)]
    del record['__last_used__']
    record.update(stamp)
    cache_path.write_text(json.dumps(cache, indent=2))
    page = output / 'en/articles/first-post/index.html'
    os.utime(page, ns=(1_000_000_000, 1_000_000_000))

    pipeline.run_build(REQUEST, config, site_root)
    assert (page.stat().st_mtime_ns != 1_000_000_000) is rebuild
    assert _used(site_root, 'output') == cache_clock[0]


@pytest.mark.parametrize('partitioned', [False, True])
def test_review28_27_noop_refresh_keeps_fingerprints_and_owners_untouched(site_root, cache_clock, partitioned):
    config = _config(enable=partitioned)
    pipeline.run_build(REQUEST, config, site_root)
    root = site_root / 'output'
    state = (_selected(site_root, 'output').path, ownership_path(root))
    before = [(path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in state]
    cache_clock[0] += 2 * DAY
    pipeline.run_build(REQUEST, config, site_root)
    assert [(path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in state] == before
    cache_clock[0] += 2 * DAY
    pipeline.run_build(REQUEST, _config('second', enable=partitioned), site_root)
    assert str(root) in json.loads(_selected(site_root, 'output').path.read_bytes())['__output_roots__']
    cache_clock[0] += DAY
    pipeline.run_build(REQUEST, _config('second', enable=partitioned), site_root)
    current = _selected(site_root, 'output').path
    assert not current.exists() or str(root) not in json.loads(current.read_bytes())['__output_roots__']


def test_review28_27_other_output_cannot_retire_activity_during_shared_rollback(site_root, cache_clock):
    root = site_root / 'output'
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    cache_clock[0] += 2 * DAY
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    marker = activity_path(_base(site_root), str(root))
    stamp = marker.read_bytes()
    cache_clock[0] += 2 * DAY
    pipeline.run_build(REQUEST, _config('third', enable=False), site_root)
    cache_clock[0] += DAY
    script = """
import os, sys
from pathlib import Path
from articulous import output_cache
from articulous.backends.posix import PosixPublicationBackend
from articulous.configuration_contracts import BuildRequest
from articulous.publication import build_site
output_cache._now = lambda: int(sys.argv[2])
class Interrupted(PosixPublicationBackend):
    def _write_state(self, publication):
        super()._write_state(publication)
        os._exit(92)
build_site(BuildRequest(), {'paths': {'output_dir': 'second'}}, Path(sys.argv[1]), backend=Interrupted())
"""
    result = subprocess.run([sys.executable, '-c', script, str(site_root), str(cache_clock[0])],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True)
    assert result.returncode == 92, result.stderr.decode()
    assert str(root) not in json.loads(_base(site_root).read_text())['__output_roots__']
    pipeline.run_build(REQUEST, _config('third', enable=False, days=4), site_root)
    assert marker.read_bytes() == stamp
    recover_publication(site_root / 'second', _base(site_root))
    pipeline.run_build(REQUEST, _config('third', enable=False, days=4), site_root)
    assert _used(site_root, 'output') == cache_clock[0] - 3 * DAY


@pytest.mark.parametrize('partitioned', [False, True])
def test_review28_27_resume_activity_retirement_after_pruning(site_root, cache_clock, monkeypatch, partitioned):
    config = _config(enable=partitioned)
    pipeline.run_build(REQUEST, config, site_root)
    root = site_root / 'output'
    cache_clock[0] += DAY
    pipeline.run_build(REQUEST, config, site_root)
    marker = activity_path(_base(site_root), str(root))
    old = json.loads(marker.read_text())
    old[1] = 'stale-generation'
    marker.write_text(json.dumps(old))

    def interrupted(self, project, roots=None):
        if self.queue.exists():
            raise OSError('interrupted after pruning')

    cache_clock[0] += 3 * DAY
    with monkeypatch.context() as fault:
        fault.setattr(CacheActivity, 'recover', interrupted)
        pipeline.run_build(REQUEST, _config('second', enable=partitioned), site_root)
    assert marker.exists()
    pipeline.run_build(REQUEST, _config('second', enable=partitioned), site_root)
    assert not marker.exists()


@pytest.mark.parametrize('partitioned', [False, True])
def test_review28_27_unreadable_inactive_activity_retains_fingerprints(site_root, cache_clock, partitioned):
    pipeline.run_build(REQUEST, _config(enable=partitioned), site_root)
    root = site_root / 'output'
    stamp = activity_path(_base(site_root), str(root))
    path = _selected(site_root, 'output').path
    stamp.write_text('[]')
    pipeline.run_build(REQUEST, _config('other', enable=partitioned, days=0), site_root)
    assert str(root) in json.loads(path.read_text())['__output_roots__']
    with pytest.raises(ValueError, match='Invalid cache activity'):
        pipeline.run_build(REQUEST, _config(enable=partitioned), site_root)
    assert stamp.read_text() == '[]'


@pytest.mark.parametrize('partitioned', [False, True])
def test_review28_27_activity_belongs_to_resolved_cache_and_root(site_root, cache_clock, partitioned):
    config = _config(enable=partitioned)
    real = site_root / 'state.json'
    _base(site_root).symlink_to(real.name)
    pipeline.run_build(REQUEST, config, site_root)
    cache_clock[0] += DAY
    pipeline.run_build(REQUEST, config, site_root)
    stamp = activity_path(real, str(site_root / 'output'))
    assert stamp.stat().st_size < 256
    assert not activity_path(_base(site_root), str(site_root / 'output')).exists()
    previous = stamp.read_bytes()
    config['build']['cache_file'] = 'alternate.json'
    pipeline.run_build(REQUEST, config, site_root)
    assert stamp.read_bytes() == previous


@pytest.mark.parametrize('key', ['output_dir', 'cache_file', 'file'])
@pytest.mark.parametrize('retiring', [False, True])
def test_review28_27_activity_state_cannot_overlap_configured_paths(site_root, key, retiring):
    base = _base(site_root)
    name = (retirement_queue(base) if retiring else activity_path(base, str(site_root / 'other'))).name
    config = _config(enable=False)
    groups = {'output_dir': 'paths', 'cache_file': 'build', 'file': 'logging'}
    config.setdefault(groups[key], {})[key] = name
    with pytest.raises(ConfigurationError, match='reserved fingerprint cache activity'):
        pipeline.run_build(REQUEST, config, site_root)
    assert not (site_root / name).exists()


@pytest.mark.parametrize('kind', ['hardlink', 'symlink', 'oversized'])
def test_review28_27_active_activity_rejects_unsafe_files(site_root, kind):
    path = activity_path(_base(site_root), str(site_root / 'output'))
    foreign = site_root / 'reference'
    foreign.write_text('keep me')
    if kind == 'hardlink':
        os.link(foreign, path)
    elif kind == 'symlink':
        path.symlink_to(foreign)
    else:
        path.write_bytes(b'x' * 513)
    with pytest.raises(ValueError, match='hardlink|symlink|Oversized'):
        pipeline.run_build(REQUEST, _config(enable=False), site_root)
    assert foreign.read_text() == 'keep me'
    assert not (site_root / 'output').exists()


def test_review28_27_touched_partition_with_reordered_generation_survives_expiry(site_root, cache_clock):
    pipeline.run_build(REQUEST, _config(), site_root)
    root = site_root / 'output'
    cache_clock[0] += 2 * DAY
    pipeline.run_build(REQUEST, _config(), site_root)
    cache = _selected(site_root, 'output').path
    data = json.loads(cache.read_text())
    record = data['__output_roots__'][str(root)]
    record['__generation__'] = record.pop('__generation__')
    cache.write_text(json.dumps(data, indent=2))
    cache_clock[0] += 2 * DAY
    pipeline.run_build(REQUEST, _config('second'), site_root)
    assert cache.is_file()
    assert _used(site_root, 'output') == cache_clock[0] - 2 * DAY


@pytest.mark.parametrize('expire', [False, True])
def test_review28_27_incremental_activity_write_failure_is_recoverable(site_root, cache_clock, monkeypatch, caplog, expire):
    from articulous import cache_activity
    pipeline.run_build(REQUEST, _config(enable=False), site_root)
    base = _base(site_root)
    if expire:
        cache_clock[0] += DAY
        pipeline.run_build(REQUEST, _config(enable=False), site_root)
    before = base.read_bytes()
    cache_clock[0] += 4 * DAY
    config = _config('second' if expire else 'output', enable=False)

    def full_disk(*args, **kwargs):
        raise OSError('disk full')

    with monkeypatch.context() as fault:
        fault.setattr(cache_activity, 'atomic_output', full_disk)
        pipeline.run_build(REQUEST, config, site_root)
    assert base.read_bytes() == before
    assert 'Cache activity update failed' in caplog.text
    pipeline.run_build(REQUEST, config, site_root)
    assert _used(site_root, config['paths']['output_dir']) == cache_clock[0]
