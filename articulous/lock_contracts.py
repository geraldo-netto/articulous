"""Resource-lock capability and adapter contracts; imports no native modules."""
from dataclasses import dataclass
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

LockBackend = Callable[[Path], AbstractContextManager[None]]


@dataclass(frozen=True)
class LockCapability:
    name: str | None
    available: bool
    validated: bool
    detail: str

