"""Native publication capability data, independent of lifecycle implementations."""
from dataclasses import dataclass
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol


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
    verify: Callable[[], None]


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

