"""Immutable packaged resource records, independent of resource providers."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceFile:
    path: str
    content: bytes
