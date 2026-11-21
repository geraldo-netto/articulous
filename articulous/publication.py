"""Whole-site publication contracts and shared orchestration."""
from contextlib import contextmanager
from functools import partial
from pathlib import Path

from .publication_contracts import PublicationBackend
from .cache_store import lock_selected_cache
from .config import normalize_configuration
from .configuration_contracts import BuildOptions, ConfigurationInput
from .publication_adapter import _publish_current, publish_generation
from .build_contracts import ValidatedBuild, ValidationReport
from .builds import (
    prepare_build, _render_validated,
)


def _backend(backend, require_atomic, require_durable) -> PublicationBackend:
    from .backends import get_publication_backend
    backend = backend if backend is not None else get_publication_backend()
    if type(require_atomic) is not bool or type(require_durable) is not bool:
        raise ValueError('Publication requirements must be booleans')
    caps = backend.capabilities
    if not (caps.available and caps.staging and caps.rollback and caps.journal_recovery):
        raise ValueError('Required publication capabilities are unsupported')
    if require_atomic and not caps.atomic_visibility:
        raise ValueError('Atomic whole-site visibility is unsupported by this backend')
    if require_durable and not caps.power_loss_durability:
        raise ValueError('Power-loss durability is unsupported by this backend')
    return backend


def publish_validated(checked: ValidatedBuild, *, backend=None,
                      require_atomic=False, require_durable=False) -> None:
    selected = _backend(backend, require_atomic, require_durable)
    if backend is None:
        _publish_current(checked, selected)
    else:
        publish_generation(checked, selected)


def recover_publication(destination: Path, cache_path: Path, *, backend=None) -> None:
    selected = _backend(backend, False, False)
    with lock_selected_cache(cache_path, destination, partial(selected.locked, destination)) as cache:
        selected.recover(destination, cache.path)


def build_site(cli: BuildOptions, config: ConfigurationInput, project_root: Path, *, extra_pages=(), validators=(),
               backend=None, require_atomic=False, require_durable=False, composer=None,
               extra_artifacts=()) -> ValidationReport:
    selected = _backend(backend, require_atomic, require_durable)
    with prepare_build(cli, config, project_root, extra_pages=extra_pages, extra_artifacts=extra_artifacts,
                       backend=selected, composer=composer) as prepared:
        checked = _render_validated(prepared, validators)
        _publish_current(checked, selected)
        return ValidationReport(len(prepared.routes), checked.diagnostics)


@contextmanager
def lock_site(cli: BuildOptions, config: ConfigurationInput, project_root: Path, *, backend=None):
    from .pipeline import build_ctx_from_config, _cache_path_for
    selected = _backend(backend, False, False)
    context = build_ctx_from_config(normalize_configuration(config, cli, project_root), dry_run=False)
    lock = partial(selected.locked, context.output_dir)
    with lock_selected_cache(_cache_path_for(context, project_root), context.output_dir, lock):
        yield
