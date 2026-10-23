"""Independent contract for a native command's owned process session."""
from dataclasses import dataclass
from typing import Protocol
import math


@dataclass(frozen=True)
class SessionOptions:
    tooling: bool = True
    checkpoint_output: bool = False

    def __post_init__(self):
        if type(self.tooling) is not bool or type(self.checkpoint_output) is not bool:
            raise ValueError('Native session options must be boolean')


class ProcessSession(Protocol):
    @property
    def returncode(self) -> int | None:
        ...

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        """Return complete output; checkpoint mode limits timeout snapshots to new stderr lines."""
        ...

    def stop(self) -> tuple[str, str]:
        ...


def deadline_seconds(value: object) -> float:
    if not isinstance(value, (int, float)) or type(value) not in (int, float):
        raise ValueError('Browser deadline must be a positive finite number')
    try:
        seconds = float(value)
    except OverflowError as error:
        raise ValueError('Browser deadline is not representable') from error
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('Browser deadline must be a positive finite number')
    return seconds





@dataclass(frozen=True, eq=False)
class RecoveryToken:
    pid: int
    workspace: str


class NativeCleanupError(RuntimeError):
    def __init__(self, token: RecoveryToken):
        self.token = token
        super().__init__(f'Native cleanup requires recovery: PID {token.pid}, retained {token.workspace}')
