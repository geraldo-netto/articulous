"""Cross-component regressions from the post-publication project review."""

from pathlib import Path
import os
import pytest

from articulous import cache_store, complexity_gate, complexity_xslt, output_metrics, site_validation
from articulous.backends.posix import PosixPublicationBackend
from articulous.backends.translation_http import HttpProvider
from articulous.builds import prepare_build, render_prepared, validate_generated
from articulous.build_contracts import BuildError
from articulous.coverage_gate import check_report
from articulous.image_optimization import candidates, optimize
from articulous.publication import build_site, publish_validated, recover_publication
from articulous.publication_paths import transaction_path
from articulous.taxonomy_contracts import TaxonomyLayout
from articulous.taxonomy_editing import apply_map
from articulous.translation_jobs import collect_variants
from test_coverage_name_collisions import native_report
from test_image_optimization import FakeImages
from test_translation_http import response, running
from urllib.error import URLError


@pytest.mark.parametrize('already_migrated', [False, True])
def test_review27_01_partition_migration_waits_for_retirement(site_root, seo_config, monkeypatch, already_migrated):
    cli, config = seo_config
    config['build']['partition_cache'] = True
    cache = site_root / '.build-cache.json'
    output = site_root / 'output'
    backend = PosixPublicationBackend()
    finish = backend._finish_retirement
    def interrupt(retired, destination, selected):
        if (retired / 'journal.json').exists():
            raise PermissionError('retirement interrupted')
        finish(retired, destination, selected)
    monkeypatch.setattr(backend, '_finish_retirement', interrupt)
    with monkeypatch.context() as migration:
        if already_migrated:
            migration.setattr(cache_store, '_has_pending_journal', lambda _: False)
        build_site(cli, config, site_root, backend=backend)
    assert cache_store.select_cache(cache, output).partitioned is already_migrated
    recover_publication(output, cache)
    build_site(cli, config, site_root)
    assert cache_store.select_cache(cache, output).partitioned


def test_review27_02_branch_summary_uses_executable_lines(tmp_path):
    source = 'def work(items):\n    for item in items:\n        break\n    return 5\nwork([1])\n'
    report, entry = native_report(tmp_path, source)
    summary = entry['functions']['work']['summary']
    assert summary['missing_lines'] == 0 and summary['missing_branches'] == 1
    assert check_report(tmp_path, ['code'], report) == (1, [])


@pytest.mark.parametrize('scheme,default', [('https', 443), ('http', 80)])
def test_review27_03_zero_port_is_a_distinct_origin(tmp_path, scheme, default):
    origin = f'{scheme}://example.test'
    assert site_validation.local_path(tmp_path, origin + ':0/file', origin) is None
    assert site_validation.local_path(tmp_path, f'{origin}:{default}/file', origin) == tmp_path / 'file'


def listing_fault(original, directory):
    def list_directory(path):
        if not isinstance(path, int) and Path(path) == directory:
            raise PermissionError(str(directory))
        return original(path)
    return list_directory


def deny_listing(monkeypatch, directory):
    for name in ('scandir', 'listdir'):
        monkeypatch.setattr(os, name, listing_fault(getattr(os, name), directory))


def inaccessible(root, monkeypatch):
    directory = root / 'unreadable'
    directory.mkdir(parents=True)
    deny_listing(monkeypatch, directory)
    return directory


def test_review27_04_html_inventory_must_be_complete(tmp_path, monkeypatch):
    (inaccessible(tmp_path, monkeypatch) / 'extra.html').write_text('<a href="/missing">broken</a>')
    with pytest.raises(PermissionError):
        site_validation.read_pages(tmp_path, [])


def test_review27_05_size_inventory_must_be_complete(tmp_path, monkeypatch):
    (inaccessible(tmp_path, monkeypatch) / 'page.html').write_text('<html/>')
    with pytest.raises(PermissionError):
        output_metrics.scan(tmp_path)


def test_review27_06_image_inventory_must_be_complete(tmp_path, monkeypatch):
    (inaccessible(tmp_path, monkeypatch) / 'photo.png').write_bytes(b'image')
    with pytest.raises(PermissionError):
        list(candidates(tmp_path, 0, {'png'}))


def test_review27_07_variant_inventory_excludes_directories(tmp_path):
    lang = tmp_path / 'en'
    (lang / 'folder.xml').mkdir(parents=True)
    document = lang / 'page.xml'
    document.touch()
    assert collect_variants(tmp_path, ['en', 'fr']) == {'page.xml': {'en': document}}


def test_review27_08_variant_inventory_requires_readable_languages(tmp_path, monkeypatch):
    directory = inaccessible(tmp_path, monkeypatch)
    (directory / 'item.xml').touch()
    with pytest.raises(PermissionError):
        collect_variants(tmp_path, ['missing', directory.name])


def test_review27_09_taxonomy_batch_rejects_incomplete_selection(tmp_path, monkeypatch):
    doc = b'<article><tag>Old</tag></article>'
    (inaccessible(tmp_path, monkeypatch) / 'hidden.xml').write_bytes(doc)
    visible = tmp_path / 'en' / 'page.xml'
    visible.parent.mkdir()
    visible.write_bytes(doc)
    with pytest.raises(PermissionError):
        apply_map(tmp_path, {'Old': 'New'}, TaxonomyLayout('tag', '*/*.xml'))
    assert visible.read_bytes() == doc


@pytest.mark.parametrize('domain', ['python', 'xslt'])
def test_review27_10_complexity_evidence_requires_complete_inventory(tmp_path, monkeypatch, domain):
    (tmp_path / 'tests').mkdir()
    parent = tmp_path / ('articulous' if domain == 'python' else complexity_xslt.DIRECTORY)
    source = inaccessible(parent, monkeypatch) / ('code.py' if domain == 'python' else 'theme.xsl')
    source.touch()
    inventory = complexity_gate.source_paths if domain == 'python' else complexity_xslt.source_paths
    with pytest.raises(PermissionError):
        inventory(tmp_path)


def test_review27_11_nested_provider_json_remains_retryable():
    with running([response(b'[' * 1500 + b']' * 1500)]) as server:
        with pytest.raises(URLError, match='Invalid translation response'):
            HttpProvider(server.endpoint, 'test').post('system', 'text')


@pytest.mark.parametrize('raw', ['{}', '{"cache":12}', 'null', '[' * 1500 + ']' * 1500], ids=['missing', 'type', 'null', 'deep'])
def test_review27_12_unknown_journal_owner_defers_cache_migration(tmp_path, raw):
    path = transaction_path(tmp_path / 'output')
    path.mkdir()
    (path / 'journal.json').write_text(raw)
    assert cache_store._has_pending_journal(tmp_path / 'cache.json')


@pytest.mark.parametrize('entry', ['assets/style.css', 'assets', '.'])
def test_review27_13_validated_modes_survive_until_publication(site_root, seo_config, entry):
    cli, config = seo_config
    with prepare_build(cli, config, site_root) as prepared:
        staged = render_prepared(prepared)
        checked = validate_generated(staged)
        path = staged.root / entry
        mode = path.stat().st_mode
        path.chmod(mode ^ 0o004)
        with pytest.raises(BuildError, match='changed'):
            publish_validated(checked)
        assert not (site_root / 'output').exists()
        path.chmod(mode)
        publish_validated(checked)


def test_review27_14_conversion_cannot_reuse_previous_image(tmp_path):
    root, scratch = tmp_path / 'images', tmp_path / 'scratch'
    scratch.mkdir()
    for folder in ['a', 'b']:
        (root / folder).mkdir(parents=True)
        (root / folder / 'photo.jpg').write_bytes(folder.encode() * 10)
    backend = FakeImages(scratch, b'first')
    convert = backend.shrink
    def incomplete(path, target, largest, quality):
        if path.parent.name == 'a':
            convert(path, target, largest, quality)
    backend.shrink = incomplete
    with pytest.raises(FileNotFoundError):
        list(optimize(root, backend, largest=5, quality=80, threshold=0, kinds={'jpeg'}, apply=True))
    assert (root / 'b/photo.jpg').read_bytes() == b'b' * 10


def test_review27_16_region_iterator_counts_every_page(tmp_path):
    for name in ('a.html', 'b.html'):
        (tmp_path / name).write_bytes(b'<html><header>shared</header></html>')
    metrics = output_metrics.scan(tmp_path, regions=iter([('header', '//header')]))
    assert metrics['region_pages']['header'] == 2

def test_review27_17_incomplete_proc_inventory_cannot_settle_fence(monkeypatch):
    from articulous.backends.browser_fence import owned_members
    deny_listing(monkeypatch, Path('/proc'))
    with pytest.raises(PermissionError):
        list(owned_members(os.getpid()))


@pytest.mark.parametrize('pattern', ['**/*.xml', '**/*', '**/a/**/*.xml', '*/*.xml'])
def test_review27_09_scoped_globs_preserve_valid_selection(tmp_path, pattern):
    paths = ['x.xml', 'a/y.xml', 'deep/a/z.xml', 'deep/k.txt']
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('<article><tag>old</tag></article>')
    selected = {path for path in tmp_path.glob(pattern) if path.is_file()}
    stats = apply_map(tmp_path, {'old': 'new'}, TaxonomyLayout('tag', pattern))
    assert stats.rewritten == len(selected)
    assert all(('new' in (tmp_path / name).read_text()) == (tmp_path / name in selected) for name in paths)


@pytest.mark.parametrize('pattern', ['', '../*.xml', '/absolute/*.xml', '**bad.xml', 'a/**', '*/'])
def test_review27_09_reject_invalid_file_patterns(tmp_path, pattern):
    with pytest.raises(ValueError):
        apply_map(tmp_path, {}, TaxonomyLayout('tag', pattern))


@pytest.mark.parametrize('branches,taken', [(True, 1), (1, False), (1, 2), (-1, 0), (2, -1)])
def test_review27_02_invalid_branch_summary(branches, taken):
    from articulous.coverage_gate import check_summary_percentages
    with pytest.raises(ValueError, match='branch summary'):
        check_summary_percentages({'num_branches': branches, 'covered_branches': taken}, 3, 3)


def test_review27_01_unsettled_retired_journal_preserved(tmp_path):
    import json
    from articulous.publication_paths import retirement_path
    output, cache = tmp_path / 'output', tmp_path / 'cache'
    retired = retirement_path(transaction_path(output))
    retired.mkdir()
    path = retired / 'journal.json'
    path.write_text(json.dumps({'phase': 'installed', 'cache': str(cache)}))
    with pytest.raises(ValueError, match='Invalid publication journal'):
        recover_publication(output, cache)
    assert path.is_file()


@pytest.mark.parametrize('raw', ['[' * 1500 + ']' * 1500, '7' * 5000], ids=['depth', 'integer'])
def test_review27_19_invalid_journal_preserves_recovery_diagnostic(tmp_path, raw):
    output = tmp_path / 'output'
    transaction = transaction_path(output)
    transaction.mkdir()
    journal = transaction / 'journal.json'
    journal.write_text(raw)
    with pytest.raises(ValueError, match='Invalid publication journal.*preserve'):
        recover_publication(output, tmp_path / 'cache')
    assert journal.read_text() == raw


@pytest.mark.parametrize('raw', ['[' * 1500 + ']' * 1500, '7' * 5000], ids=['depth', 'integer'])
def test_review27_20_invalid_ownership_preserves_recovery_diagnostic(tmp_path, raw):
    from articulous.ownership import load_ownership, ownership_path
    output = tmp_path / 'output'
    state = ownership_path(output)
    state.write_text(raw)
    with pytest.raises(ValueError, match='Invalid output ownership.*restore'):
        load_ownership(output)
    assert state.read_text() == raw
