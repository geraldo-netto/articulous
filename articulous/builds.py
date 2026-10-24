"""Prepared whole-site builds with validation before publication."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
import shutil

from .articles import ArticleStats
from .composition import RouteCatalog
from .composition_contracts import ExtraPage, artifact_values
from .engines import StylesheetCapture
from .extensions import BuildComposition, TemplateInput
from .config import DEFAULT_CONFIG, apply_cli_overrides, deep_merge, validate_config
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


@dataclass(frozen=True)
class Diagnostic:
    message: str
    severity: str = 'error'
    path: str = ''

    def __post_init__(self):
        if self.severity not in ('error', 'warning'):
            raise ValueError('Diagnostic severity must be error or warning')


@dataclass(frozen=True)
class ValidationReport:
    routes: int
    diagnostics: tuple[Diagnostic, ...]


@dataclass
class PreparedBuild:
    context: BuildCtx
    destination: Path
    cache_path: Path
    routes: RouteCatalog
    manifest: OutputManifest
    plan: BuildPlan
    cache: dict
    workspace: TempWorkspace
    state: str = 'prepared'
    closed: bool = False
    validation_revision: int = 0

    def require_state(self, *states):
        if self.closed:
            raise ValueError('Prepared build is closed')
        if self.state not in states:
            raise ValueError(f'Invalid prepared build state: {self.state}')

    def close(self):
        self.closed = True


@dataclass(frozen=True)
class StagedBuild:
    prepared: PreparedBuild
    fingerprint: str

    @property
    def root(self) -> Path:
        return self.prepared.context.output_dir

    @property
    def routes(self) -> RouteCatalog:
        return self.prepared.routes

    def assert_unchanged(self):
        self.prepared.require_state('rendered', 'validated')
        if tree_fingerprint(self.root) != self.fingerprint:
            raise ValueError('Staged artifacts changed after rendering or validation')

    @contextmanager
    def open_artifact(self, relative: str):
        self.prepared.require_state('rendered', 'validated')
        if not isinstance(relative, str) or not relative:
            raise ValueError('Invalid artifact path')
        if any(char in relative for char in '\\:') or any(part in ('', '.', '..') for part in relative.split('/')):
            raise ValueError('Invalid artifact path')
        path = self.root / relative
        validate_output_path(path)
        with open_regular_file(path) as source:
            yield source


@dataclass(frozen=True)
class ValidatedBuild:
    staged: StagedBuild
    diagnostics: tuple[Diagnostic, ...]
    revision: int

    def assert_unchanged(self):
        self.staged.prepared.require_state('validated')
        if self.revision != self.staged.prepared.validation_revision:
            raise ValueError('Validation handle has been superseded')
        self.staged.assert_unchanged()


def _configuration(cli, config, root):
    if not isinstance(config, dict):
        raise ValueError('Configuration must be an object')
    result = deep_merge(deepcopy(DEFAULT_CONFIG), deepcopy(config))
    validate_config(result)
    validate_output_path(root / result['paths']['output_dir'])
    apply_cli_overrides(result, cli, root)
    return result


@contextmanager
def capture_site(cli, config, project_root: Path):
    context = build_ctx_from_config(_configuration(cli, config, project_root), dry_run=True)
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
    _finish_artifacts(context, snapshot, composition, routes, manifest, plan, cache)
    _finish_composition(context, snapshot, composition, routes)
    prepared = PreparedBuild(context, original.output_dir, _cache_path_for(original, root),
                             routes, manifest, plan, cache, workspace)
    stack.callback(prepared.close)
    return prepared


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
def prepare_build(cli, config, project_root: Path, *, extra_pages=(), extra_artifacts=(), backend=None, composer=None):
    pages = _full_build(cli, extra_pages)
    artifacts = artifact_values(extra_artifacts)
    original = build_ctx_from_config(_configuration(cli, config, project_root), dry_run=False)
    validate_output_path(original.output_dir)
    with ExitStack() as stack:
        stack.enter_context(_preparation_lock(original, project_root, backend))
        yield _prepare_locked(stack, cli, original, project_root, pages, composer, artifacts)


def render_prepared(prepared: PreparedBuild) -> StagedBuild:
    prepared.require_state('prepared')
    prepared.state = 'failed'
    prepared.context.output_dir.mkdir(parents=True)
    validate_output_path(prepared.context.assets_dir)
    if prepared.context.assets_dir.exists():
        prepared.context.assets_dir.rename(prepared.context.output_dir / 'assets')
    _run_plan(prepared.plan, prepared.context)
    _cleanup_stream_projection(prepared.plan.projection)
    prepared.workspace.cleanup()
    prepared.state = 'rendered'
    return StagedBuild(prepared, tree_fingerprint(prepared.context.output_dir))


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
        raise ValueError('Validators must return Diagnostic values or None') from error
    if not all(isinstance(item, Diagnostic) for item in diagnostics):
        raise ValueError('Validators must return Diagnostic values or None')
    return diagnostics


def validate_generated(staged: StagedBuild, *, validators=()) -> ValidatedBuild:
    staged.prepared.require_state('rendered', 'validated')
    staged.prepared.state = 'rendered'
    staged.prepared.validation_revision += 1
    staged.assert_unchanged()
    _validate_manifest(staged)
    diagnostics = []
    for validator in validators:
        diagnostics.extend(_validator_diagnostics(validator, staged))
    errors = [item.message for item in diagnostics if item.severity == 'error']
    if errors:
        raise ValueError('\n'.join(errors))
    staged.assert_unchanged()
    staged.prepared.state = 'validated'
    return ValidatedBuild(staged, tuple(diagnostics), staged.prepared.validation_revision)


def check_build(cli, config, project_root: Path, *, extra_pages=(), extra_artifacts=(), validators=(), composer=None) -> ValidationReport:
    with prepare_build(cli, config, project_root, extra_pages=extra_pages, extra_artifacts=extra_artifacts, composer=composer) as prepared:
        checked = validate_generated(render_prepared(prepared), validators=validators)
        return ValidationReport(len(prepared.routes), checked.diagnostics)
