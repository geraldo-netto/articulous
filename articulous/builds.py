"""Prepared whole-site builds with validation before publication."""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import BinaryIO
import os
import shutil

from .articles import ArticleStats
from .composition import RouteCatalog
from .composition_contracts import ExtraArtifact, ExtraPage, RouteReader, artifact_values
from .build_contracts import (
    ArtifactReader, BuildError, Composer, Diagnostic, PreparedBuild, StagedBuild,
    ValidatedBuild, ValidationReport, Validator,
)
from .publication_contracts import PublicationBackend
from .extensions import CapturedSite
from .engines import StylesheetCapture
from .extensions import BuildComposition, TemplateInput
from .config import normalize_configuration
from .configuration_contracts import BuildOptions, ConfigurationInput
from .filesystem import (
    TempWorkspace, cache_lock_path, lock_file, open_regular_file, private_directory,
    tree_fingerprint, validate_output_path,
)
from .pipeline import (
    BuildCtx, BuildPlan, OutputManifest, _article_stream_factory, _cache_path_for,
    _cleanup_stream_projection, _close_task_queues, _collect_tasks, _lock_path_for,
    _run_plan, build_artifacts_section, build_ctx_from_config, copy_assets,
)
from .capture_adapter import Snapshot


@dataclass
class _BuildState:
    context: BuildCtx
    destination: Path
    cache_path: Path
    routes: RouteCatalog
    manifest: OutputManifest
    plan: BuildPlan
    cache: dict
    workspace: TempWorkspace
    state: str = 'prepared'
    validation_revision: int = 0
    readers: set[_ArtifactReader] = field(default_factory=set)

    def require_live(self):
        if self.state == 'closed':
            raise BuildError('Prepared build is closed')

    def require_state(self, *states):
        self.require_live()
        if self.state not in states:
            raise BuildError(f'Invalid prepared build state: {self.state}')

    def open_reader(self, path):
        self.require_state('rendered', 'validated')
        cleanup = ExitStack()
        try:
            source = cleanup.enter_context(open_regular_file(path))
            reader = _ArtifactReader(self, source, cleanup, os.fstat(source.fileno()).st_size)
            self.readers.add(reader)
        except BaseException:
            cleanup.close()
            raise
        return reader

    def release_reader(self, reader):
        if reader in self.readers:
            reader._cleanup.close()
            if not reader._source.closed:
                reader._source.close()
            self.readers.remove(reader)

    def settle_readers(self):
        for reader in tuple(self.readers):
            self.release_reader(reader)

    def close(self):
        self.state = 'closed'
        self.settle_readers()
        self.routes.close()

    def published(self, revision):
        self.require_state('validated')
        if revision != self.validation_revision:
            raise BuildError('Validation handle has been superseded')
        self.state = 'published'


@dataclass(frozen=True, eq=False)
class _ArtifactReader:
    _owner: _BuildState
    _source: BinaryIO
    _cleanup: ExitStack
    _limit: int

    @property
    def closed(self) -> bool:
        return self._owner.state == 'closed' or self not in self._owner.readers

    def read(self, size: int = -1) -> bytes:
        if self.closed:
            raise BuildError('Artifact reader is closed')
        self._owner.require_state('rendered', 'validated')
        if type(size) is not int or size < -1:
            raise BuildError('Artifact read size must be -1 or a nonnegative integer')
        remaining = max(0, self._limit - self._source.tell())
        amount = remaining if size == -1 else min(size, remaining)
        return self._source.read(amount)


@dataclass(frozen=True)
class _RouteView:
    _owner: _BuildState

    def __iter__(self):
        self._owner.require_live()
        with closing(iter(self._owner.routes)) as source:
            while True:
                self._owner.require_live()
                try:
                    route = next(source)
                except StopIteration:
                    return
                yield route

    def __len__(self):
        self._owner.require_live()
        return len(self._owner.routes)


@dataclass(frozen=True)
class _PreparedBuild:
    _owner: _BuildState

    @property
    def state(self) -> str:
        return self._owner.state

    @property
    def closed(self) -> bool:
        return self._owner.state == 'closed'

    @property
    def routes(self) -> RouteReader:
        return _RouteView(self._owner)

    def close(self) -> None:
        self._owner.close()


@dataclass(frozen=True)
class _StagedBuild:
    _owner: _BuildState
    _fingerprint: str

    @property
    def root(self) -> Path:
        return self._owner.context.output_dir

    @property
    def routes(self) -> RouteReader:
        return _RouteView(self._owner)

    def assert_unchanged(self):
        self._owner.require_state('rendered', 'validated')
        if tree_fingerprint(self.root) != self._fingerprint:
            raise BuildError('Staged artifacts changed after rendering or validation')

    @contextmanager
    def open_artifact(self, relative: str) -> Iterator[ArtifactReader]:
        self._owner.require_state('rendered', 'validated')
        if not isinstance(relative, str) or not relative:
            raise BuildError('Invalid artifact path')
        if any(char in relative for char in '\\:') or any(part in ('', '.', '..') for part in relative.split('/')):
            raise BuildError('Invalid artifact path')
        path = self.root / relative
        validate_output_path(path)
        reader = self._owner.open_reader(path)
        try:
            yield reader
        finally:
            self._owner.release_reader(reader)


@dataclass(frozen=True)
class _ValidatedBuild:
    _staged: _StagedBuild
    _diagnostics: tuple[Diagnostic, ...]
    _revision: int

    @property
    def staged(self) -> StagedBuild:
        return self._staged

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return self._diagnostics

    def assert_unchanged(self):
        self._staged._owner.require_state('validated')
        if self._revision != self._staged._owner.validation_revision:
            raise BuildError('Validation handle has been superseded')
        self._staged.assert_unchanged()


def _owned_prepared(value: PreparedBuild) -> _BuildState:
    if not isinstance(value, _PreparedBuild):
        raise BuildError('Unrecognized prepared build handle')
    return value._owner


def _owned_staged(value: StagedBuild) -> _StagedBuild:
    if not isinstance(value, _StagedBuild):
        raise BuildError('Unrecognized staged build handle')
    return value


def _owned_validated(value: ValidatedBuild) -> _ValidatedBuild:
    if not isinstance(value, _ValidatedBuild):
        raise BuildError('Unrecognized validated build handle')
    return value


@contextmanager
def capture_site(cli: BuildOptions, config: ConfigurationInput, project_root: Path) -> Iterator[CapturedSite]:
    context = build_ctx_from_config(normalize_configuration(config, cli, project_root), dry_run=True)
    with TempWorkspace() as workspace:
        snapshot = Snapshot(context, workspace)
        try:
            yield snapshot
        finally:
            snapshot.close()


def _full_build(cli, extra_pages):
    if cli.only_sections or cli.only_langs or cli.only_slugs:
        raise ValueError('Whole-site preparation requires an unfiltered build')
    pages = tuple(extra_pages)
    if not all(isinstance(page, ExtraPage) for page in pages):
        raise ValueError('extra_pages must contain ExtraPage values')
    return pages


def _capture_context(stack, original, extra_pages, cache, extra_artifacts=()):
    original.output_dir.parent.mkdir(parents=True, exist_ok=True)
    private = stack.enter_context(private_directory(original.output_dir.parent))
    capture = replace(original, output_dir=private / 'inputs', dry_run=False, force=True)
    copy_assets(capture, cache)
    return replace(capture, output_dir=private / 'output',
                   assets_dir=capture.output_dir / 'assets', extra_pages=extra_pages,
                   extra_artifacts=extra_artifacts)


def _composition_context(stack, context, composer, original):
    if composer is None:
        return context, None, None
    if not callable(composer):
        raise ValueError('Build composer must be callable')
    overlay = context.output_dir.parent / 'inputs/xsl'
    shutil.copytree(original.xsl_dir, overlay, symlinks=True)
    capture = StylesheetCapture()
    context = replace(context, xsl_dir=overlay, stylesheet_capture=capture,
                      engines={name: capture.wrap(engine) for name, engine in context.engines.items()})
    snapshot = Snapshot(context, stack.enter_context(TempWorkspace()))
    stack.callback(snapshot.close)
    composition = composer(snapshot)
    if not isinstance(composition, BuildComposition):
        raise ValueError('Build composer must return BuildComposition')
    pages = context.extra_pages + composition.pages
    mapped = tuple(_overlay_page(page, original.xsl_dir, overlay) for page in pages)
    return replace(context, extra_pages=mapped), snapshot, composition


def _overlay_page(page, source, overlay):
    stylesheet = Path(page.stylesheet).absolute()
    if stylesheet.is_relative_to(source):
        stylesheet = overlay / stylesheet.relative_to(source)
    return replace(page, stylesheet=stylesheet)


def _finish_composition(context, snapshot, composition, routes):
    if composition is None:
        return
    seen = set()
    inputs = composition.templates(snapshot, routes) if composition.templates is not None else ()
    for item in inputs:
        if not isinstance(item, TemplateInput) or item.path in seen:
            raise ValueError('Template inputs must be unique TemplateInput values')
        seen.add(item.path)
        target = context.xsl_dir / item.path
        validate_output_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.content)
    context.stylesheet_capture.freeze()


def _finish_artifacts(context, snapshot, composition, routes, manifest, plan, cache):
    if composition is None or composition.artifacts is None:
        return
    artifacts = artifact_values(composition.artifacts(snapshot, routes))
    tasks = build_artifacts_section(artifacts, context, cache, manifest)
    plan.setdefault('artifacts', []).extend(tasks)


def _prepare_locked(stack, cli, original, root, pages, composer=None, artifacts=()):
    cache = {}
    context = _capture_context(stack, original, pages, cache, artifacts)
    context, snapshot, composition = _composition_context(stack, context, composer, original)
    workspace = stack.enter_context(TempWorkspace())
    routes = stack.enter_context(RouteCatalog())
    manifest = OutputManifest(context, routes)
    stream = snapshot.original_articles if snapshot is not None else _article_stream_factory(context, ArticleStats())
    plan = _collect_tasks(stream, cli, context,
                          cache, workspace, manifest)
    stack.callback(_cleanup_stream_projection, plan.projection)
    stack.callback(_close_task_queues, plan)
    owner = _BuildState(context, original.output_dir, _cache_path_for(original, root),
                        routes, manifest, plan, cache, workspace)
    stack.callback(owner.close)
    view = _RouteView(owner)
    _finish_artifacts(context, snapshot, composition, view, manifest, plan, cache)
    _finish_composition(context, snapshot, composition, view)
    return _PreparedBuild(owner)


@contextmanager
def _preparation_lock(original, root, backend):
    cache = _cache_path_for(original, root)
    if backend is not None:
        with backend.locked(original.output_dir, cache):
            backend.recover(original.output_dir, cache)
            yield
    else:
        with lock_file(cache_lock_path(cache)), lock_file(_lock_path_for(original, root)):
            yield


@contextmanager
def prepare_build(cli: BuildOptions, config: ConfigurationInput, project_root: Path, *,
                  extra_pages: Iterable[ExtraPage] = (), extra_artifacts: Iterable[ExtraArtifact] = (),
                  backend: PublicationBackend | None = None, composer: Composer | None = None) -> Iterator[PreparedBuild]:
    pages = _full_build(cli, extra_pages)
    artifacts = artifact_values(extra_artifacts)
    original = build_ctx_from_config(normalize_configuration(config, cli, project_root), dry_run=False)
    validate_output_path(original.output_dir)
    with ExitStack() as stack:
        stack.enter_context(_preparation_lock(original, project_root, backend))
        yield _prepare_locked(stack, cli, original, project_root, pages, composer, artifacts)


def render_prepared(prepared: PreparedBuild) -> StagedBuild:
    owner = _owned_prepared(prepared)
    owner.require_state('prepared')
    owner.state = 'failed'
    owner.context.output_dir.mkdir(parents=True)
    validate_output_path(owner.context.assets_dir)
    if owner.context.assets_dir.exists():
        owner.context.assets_dir.rename(owner.context.output_dir / 'assets')
    _run_plan(owner.plan, owner.context)
    _cleanup_stream_projection(owner.plan.projection)
    owner.workspace.cleanup()
    owner.state = 'rendered'
    return _StagedBuild(owner, tree_fingerprint(owner.context.output_dir))

def _validate_manifest(staged):
    for route in staged.routes:
        with staged.open_artifact(route.output_path):
            pass


def _validator_diagnostics(validator, staged):
    values = validator(staged)
    if values is None:
        return ()
    try:
        diagnostics = tuple(values)
    except TypeError as error:
        raise BuildError('Validators must return Diagnostic values or None') from error
    if not all(isinstance(item, Diagnostic) for item in diagnostics):
        raise BuildError('Validators must return Diagnostic values or None')
    return diagnostics


def validate_generated(staged: StagedBuild, *, validators: Iterable[Validator] = ()) -> ValidatedBuild:
    handle = _owned_staged(staged)
    owner = handle._owner
    owner.require_state('rendered', 'validated')
    owner.state = 'rendered'
    owner.validation_revision += 1
    handle.assert_unchanged()
    _validate_manifest(handle)
    diagnostics = []
    for validator in validators:
        diagnostics.extend(_validator_diagnostics(validator, handle))
    errors = [item.message for item in diagnostics if item.severity == 'error']
    if errors:
        raise BuildError('\n'.join(errors))
    handle.assert_unchanged()
    owner.state = 'validated'
    return _ValidatedBuild(handle, tuple(diagnostics), owner.validation_revision)

def check_build(cli: BuildOptions, config: ConfigurationInput, project_root: Path, *,
                extra_pages: Iterable[ExtraPage] = (), extra_artifacts: Iterable[ExtraArtifact] = (),
                validators: Iterable[Validator] = (), composer: Composer | None = None) -> ValidationReport:
    with prepare_build(cli, config, project_root, extra_pages=extra_pages, extra_artifacts=extra_artifacts, composer=composer) as prepared:
        checked = validate_generated(render_prepared(prepared), validators=validators)
        return ValidationReport(len(prepared.routes), checked.diagnostics)
