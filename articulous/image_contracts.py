"""Image maintenance inputs and native adapter boundary."""
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

KINDS = {'.jpg': 'jpeg', '.jpeg': 'jpeg', '.png': 'png'}


def validate_options(largest, quality, threshold=0):
    if type(largest) is not int or largest < 1:
        raise ValueError('--max must be a positive integer')
    if type(quality) is not int or not 0 <= quality <= 100:
        raise ValueError('--quality must be an integer from 0 through 100')
    if type(threshold) is not int or threshold < 0:
        raise ValueError('--min-bytes must be a nonnegative integer')


@dataclass(frozen=True)
class ImageResult:
    path: Path
    width: int
    height: int
    before: int
    after: int


class ImageBackend(Protocol):
    def dimensions(self, path: Path) -> tuple[int, int]:
        ...

    def shrink(self, path: Path, target: Path, largest: int, quality: int) -> None:
        ...

    def workspace(self) -> AbstractContextManager[Path]:
        ...
