"""Native publication capability data, independent of lifecycle implementations."""
from dataclasses import dataclass, field
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol
from weakref import ReferenceType, ref

from .composition_contracts import Route


@dataclass(frozen=True)
class PublicationCapabilities:
    platform: str
    available: bool
    staging: bool
    rollback: bool
    journal_recovery: bool
    atomic_visibility: bool = False
    power_loss_durability: bool = False


@dataclass(frozen=True)
class PublicationInput:
    root: Path
    destination: Path
    cache_path: Path
    cache_text: str
    output_owners: Mapping[str, str]
    output_routes: Mapping[str, Route]
    verify: Callable[[], None]
    generation: str | None = None
    translations: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class StagedStateFile:
    path: Path
    digest: str


@dataclass(frozen=True)
class StagedPublicationInput:
    root: Path
    destination: Path
    cache_path: Path
    cache: StagedStateFile
    ownership: StagedStateFile
    verify: Callable[[], None]


def accepts_staged_publication(operation):
    """Opt this publish operation into borrowed, pre-serialized state files."""
    operation.staged_publication_owner = ref(operation)
    return operation


def uses_staged_publication(operation):
    owner = getattr(operation, 'staged_publication_owner', None)
    return isinstance(owner, ReferenceType) and owner() is getattr(operation, '__func__', operation)


class PublicationBackend(Protocol):
    @property
    def capabilities(self) -> PublicationCapabilities:
        ...

    def locked(self, destination: Path, cache_path: Path) -> AbstractContextManager:
        ...

    def recover(self, destination: Path, cache_path: Path) -> None:
        ...

    def publish(self, publication: PublicationInput) -> None:
        ...

