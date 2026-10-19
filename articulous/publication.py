"""Whole-site publication contracts and shared orchestration."""
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .builds import (
    ValidatedBuild, ValidationReport, prepare_build, render_prepared, validate_generated,
)


@dataclass(frozen=True)
class PublicationCapabilities:
    platform: str
    available: bool
    staging: bool
    rollback: bool
    journal_recovery: bool
    atomic_visibility: bool = False
    power_loss_durability: bool = False


class PublicationBackend(Protocol):
    @property
    def capabilities(self) -> PublicationCapabilities:
        ...

    def locked(self, destination: Path, cache_path: Path) -> AbstractContextManager:
        ...

    def recover(self, destination: Path, cache_path: Path) -> None:
        ...

    def publish(self, checked: ValidatedBuild) -> None:
        ...


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
    checked.assert_unchanged()
    prepared = checked.staged.prepared
    selected.recover(prepared.destination, prepared.cache_path)
    selected.publish(checked)
    prepared.state = 'published'


def recover_publication(destination: Path, cache_path: Path, *, backend=None) -> None:
    selected = _backend(backend, False, False)
    with selected.locked(destination, cache_path):
        selected.recover(destination, cache_path)


def build_site(cli, config, project_root: Path, *, extra_pages=(), validators=(),
               backend=None, require_atomic=False, require_durable=False, composer=None) -> ValidationReport:
    selected = _backend(backend, require_atomic, require_durable)
    with prepare_build(cli, config, project_root, extra_pages=extra_pages, backend=selected, composer=composer) as prepared:
        checked = validate_generated(render_prepared(prepared), validators=validators)
        publish_validated(checked, backend=selected, require_atomic=require_atomic, require_durable=require_durable)
        return ValidationReport(len(prepared.routes), checked.diagnostics)
