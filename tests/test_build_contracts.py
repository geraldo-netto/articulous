"""API-001: opaque lifecycle handles and scoped read-only validation views."""
from itertools import product
from contextlib import ExitStack, contextmanager
from pathlib import Path
import subprocess
import sys
from typing import Any
from unittest.mock import Mock

import pytest

from articulous import builds
from articulous.publication import publish_validated
from articulous.build_contracts import (
    BuildAPI, BuildError, Diagnostic, StagedBuild, ValidationReport,
)
from articulous.configuration_contracts import BuildOptions, ConfigurationInput


def test_api001_contract_import_excludes_all_implementations():
    script = '''
import sys
sys.modules['fcntl'] = None
sys.modules['sqlite3'] = None
sys.modules['lxml'] = None
from articulous.build_contracts import PreparedBuild, StagedBuild, ValidatedBuild, Diagnostic, BuildAPI
assert Diagnostic('neutral').severity == 'error'
assert 'articulous.builds' not in sys.modules
assert 'articulous.pipeline' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_api001_handles_expose_only_contract_views(site_root, seo_config):
    cli, config = seo_config
    with builds.prepare_build(cli, config, site_root) as prepared:
        assert not prepared.closed
        for name in ('context', 'manifest', 'plan', 'cache', 'workspace', 'cache_path', 'destination'):
            assert not hasattr(prepared, name)
        assert not hasattr(prepared.routes, 'record')
        assert not hasattr(prepared.routes, 'close')
        with pytest.raises(AttributeError):
            setattr(prepared, 'state', 'validated')
        staged = builds.render_prepared(prepared)
        assert not hasattr(staged, 'prepared')
        assert not hasattr(staged, 'fingerprint')
        checked = builds.validate_generated(staged)
        assert checked.staged.root == staged.root
    assert prepared.closed


def test_api001_context_closes_retained_artifact_and_route_borrows(site_root, seo_config):
    cli, config = seo_config
    borrow = None
    try:
        with builds.prepare_build(cli, config, site_root) as prepared:
            staged = builds.render_prepared(prepared)
            borrow = staged.open_artifact('rss.xml')
            reader = borrow.__enter__()
            assert reader.read(1)
            routes = iter(staged.routes)
            assert next(routes).key
        assert reader.closed
        with pytest.raises(ValueError, match='closed'):
            reader.read(1)
        with pytest.raises(ValueError, match='closed'):
            next(routes)
    finally:
        if borrow is not None:
            borrow.__exit__(None, None, None)


@pytest.mark.parametrize('value', [None, {}, object()])
def test_api001_foreign_handles_reject_before_effects(site_root, value):
    from articulous.build_contracts import BuildError
    for operation in (builds.render_prepared, builds.validate_generated, publish_validated):
        with pytest.raises(BuildError, match='handle'):
            operation(value)
    assert not (site_root / 'output').exists()


@pytest.mark.parametrize('size', [-2, False, None, 1.5, '1', []])
def test_api001_artifact_read_sizes_reject_invalid_values(site_root, seo_config, size):
    cli, config = seo_config
    with builds.prepare_build(cli, config, site_root) as prepared:
        staged = builds.render_prepared(prepared)
        with staged.open_artifact('rss.xml') as source:
            with pytest.raises(ValueError, match='size'):
                source.read(size)


@pytest.mark.parametrize('size', [-1, 0, 1, 10**100])
def test_api001_artifact_reads_bound_allocations_to_admitted_file(site_root, seo_config, size):
    cli, config = seo_config
    with builds.prepare_build(cli, config, site_root) as prepared:
        staged = builds.render_prepared(prepared)
        expected = (staged.root / 'rss.xml').read_bytes()
        with staged.open_artifact('rss.xml') as source:
            assert source.read(size) == expected[:None if size == -1 else size]
            assert not hasattr(source, 'fileno')
        assert source.closed
        with pytest.raises(ValueError, match='closed'):
            source.read()


def api001_validator(staged: StagedBuild):
    with staged.open_artifact('rss.xml') as source:
        if not source.read(1):
            return (Diagnostic('Empty feed'),)
    return (Diagnostic('Checked', 'warning'),)


def api001_consumer(api: BuildAPI, request: BuildOptions, config: ConfigurationInput,
                    root: Path) -> ValidationReport:
    return api.check_build(request, config, root, validators=[api001_validator])


def test_api001_independent_consumer_uses_module_interface(site_root, seo_config):
    cli, config = seo_config
    report = api001_consumer(builds, cli, config, site_root)
    assert report.diagnostics == (Diagnostic('Checked', 'warning'),)
    (site_root / 'xsl/pages/rss.xsl').write_text(
        '<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
        '<xsl:template match="/"/></xsl:stylesheet>')
    with pytest.raises(BuildError, match='Empty feed'):
        api001_consumer(builds, cli, config, site_root)
    assert not (site_root / 'output').exists()


@pytest.mark.parametrize('schema,values', [
    (Diagnostic, {'message': None}), (Diagnostic, {'message': 'bad', 'path': False}),
    (ValidationReport, {'routes': True, 'diagnostics': ()}),
    (ValidationReport, {'routes': -1, 'diagnostics': ()}),
    (ValidationReport, {'routes': 0, 'diagnostics': []}),
    (ValidationReport, {'routes': 0, 'diagnostics': (1,)}),
])
def test_api001_diagnostic_report_schema_admission(schema, values):
    with pytest.raises(BuildError):
        schema(**values)


class LifecycleOracle:
    def __init__(self):
        self.state = 'rendered'
        self.revision = 0
        self.valid_revision = None

    def step(self, operation):
        if operation in ('validate', 'reject'):
            self.revision += 1
        if self.state in ('published', 'closed') and operation != 'close':
            return False
        if operation == 'publish':
            if self.state != 'validated':
                return False
            self.state = 'published'
            self.valid_revision = None
            return True
        if operation == 'close':
            self.state = 'closed'
            self.valid_revision = None
            return True
        self.state = 'validated' if operation == 'validate' else 'rendered'
        self.valid_revision = self.revision if operation == 'validate' else None
        return operation == 'validate'


class LifecycleDriver:
    def __init__(self, prepared, staged):
        self.prepared = prepared
        self.staged = staged
        self.revision = 0
        self.latest: Any = None
        self.tokens = []

    def apply(self, operation):
        if operation in ('validate', 'reject'):
            self.revision += 1
        if operation == 'close':
            self.prepared.close()
            return
        if operation == 'publish':
            publish_validated(self.latest)
            return
        if operation == 'reject':
            builds.validate_generated(self.staged, validators=[api001_reject])
            return
        self.latest = builds.validate_generated(self.staged)
        self.tokens.append((self.revision, self.latest))

    def check_tokens(self, oracle):
        for revision, token in self.tokens:
            if oracle.state == 'validated' and revision == oracle.valid_revision:
                token.assert_unchanged()
            else:
                with pytest.raises(BuildError):
                    token.assert_unchanged()


def api001_reject(staged):
    return (Diagnostic('Model rejection'),)


@pytest.mark.parametrize('sequence', list(product(('validate', 'reject', 'publish', 'close'), repeat=3)))
def test_api001_bounded_lifecycle_sequences(site_root, seo_config, sequence):
    cli, config = seo_config
    oracle = LifecycleOracle()
    with builds.prepare_build(cli, config, site_root) as prepared:
        driver = LifecycleDriver(prepared, builds.render_prepared(prepared))
        for operation in sequence:
            accepted = oracle.step(operation)
            if accepted:
                driver.apply(operation)
            else:
                with pytest.raises(BuildError):
                    driver.apply(operation)
            assert prepared.state == oracle.state
            driver.check_tokens(oracle)


def test_api001_reader_admission_failure_settles_open_file(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    opened = []
    original_open = builds.open_regular_file
    @contextmanager
    def observed(path):
        with original_open(path) as source:
            opened.append(source)
            yield source
    with builds.prepare_build(cli, config, site_root) as prepared:
        staged = builds.render_prepared(prepared)
        monkeypatch.setattr(builds, 'open_regular_file', observed)
        monkeypatch.setattr(builds, '_ArtifactReader', Mock(side_effect=MemoryError('admission failed')))
        with pytest.raises(MemoryError, match='admission failed'):
            with staged.open_artifact('rss.xml'):
                pytest.fail('reader admitted without funding')
        assert opened[-1].closed


class CleanupFault(ExitStack):
    def __init__(self, actual, mode):
        super().__init__()
        self.actual = actual
        self.mode = mode
        self.calls = 0

    def close(self):
        self.calls += 1
        if self.mode == 'missing':
            return
        if self.calls == 1:
            raise OSError('reader close needs retry')
        self.actual.close()


@pytest.mark.parametrize('mode', ['missing', 'retry'])
def test_api001_reader_cleanup_obligations_remain_owned(site_root, seo_config, monkeypatch, mode):
    cli, config = seo_config
    recorded = []
    original = builds._ArtifactReader
    def faulty(owner, source, cleanup, limit):
        sponsor = CleanupFault(cleanup, mode)
        recorded.append((source, sponsor))
        return original(owner, source, sponsor, limit)
    with builds.prepare_build(cli, config, site_root) as prepared:
        staged = builds.render_prepared(prepared)
        monkeypatch.setattr(builds, '_ArtifactReader', faulty)
        borrow = staged.open_artifact('rss.xml')
        reader = borrow.__enter__()
        try:
            api001_close_with_fault(prepared, reader, mode)
            assert recorded[0][0].closed
        finally:
            prepared.close()
            borrow.__exit__(None, None, None)
            recorded[0][1].actual.close()


def api001_close_with_fault(prepared, reader, mode):
    if mode == 'retry':
        with pytest.raises(OSError, match='needs retry'):
            prepared.close()
        assert reader.closed
        with pytest.raises(BuildError, match='closed'):
            reader.read()
    prepared.close()


@pytest.mark.parametrize('failure', [RuntimeError('caller failed'), KeyboardInterrupt('cancelled')])
def test_api001_caller_failure_closes_borrow_and_generation(site_root, seo_config, failure):
    cli, config = seo_config
    reader = staged = None
    with pytest.raises(type(failure)):
        with builds.prepare_build(cli, config, site_root) as prepared:
            staged = builds.render_prepared(prepared)
            with staged.open_artifact('rss.xml') as reader:
                assert reader.read(1)
                raise failure
    assert reader is not None
    assert staged is not None
    assert reader.closed
    assert not staged.root.exists()


def test_api001_publication_settles_readers_before_native_handoff(site_root, seo_config):
    cli, config = seo_config
    with builds.prepare_build(cli, config, site_root) as prepared:
        staged = builds.render_prepared(prepared)
        checked = builds.validate_generated(staged)
        with staged.open_artifact('rss.xml') as reader:
            publish_validated(checked)
            assert reader.closed
            with pytest.raises(BuildError, match='closed'):
                reader.read(1)
        assert (site_root / 'output/rss.xml').is_file()


def test_api001_native_settlement_rejects_wrong_validation_identity(site_root, seo_config):
    cli, config = seo_config
    with builds.prepare_build(cli, config, site_root) as prepared:
        staged = builds.render_prepared(prepared)
        checked = builds.validate_generated(staged)
        native = builds._owned_validated(checked)
        with pytest.raises(BuildError, match='superseded'):
            native._staged._owner.published(-1)
        checked.assert_unchanged()
        assert prepared.state == 'validated'
