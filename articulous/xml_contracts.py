"""Caller-owned XML source views, independent of native parser implementations."""
from __future__ import annotations
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class XmlElement(Protocol):
    tag: object
    text: str | None
    attrib: Mapping[str, str]

    def __iter__(self) -> Iterator[XmlElement]:
        ...

    def __len__(self) -> int:
        ...

    def iter(self) -> Iterator[XmlElement]:
        ...

    def get(self, name: str, default: str | None = None) -> str | None:
        ...

    def set(self, name: str, value: str) -> None:
        ...

    def find(self, name: str) -> XmlElement | None:
        ...

    def findtext(self, name: str, default: str = '') -> str:
        ...


@dataclass(frozen=True)
class XmlSource:
    """Original bytes and a matching owned tree; parse metadata before editing.

    The provider captures bytes/tree together. Metadata readers borrow the tree
    synchronously without mutation. Subsequent edits affect serialize(), never
    content. The serializer retains its own tree owner, not an open file handle.
    """
    content: bytes
    base_uri: str
    root: XmlElement
    serialize: Callable[[], bytes]

    def __post_init__(self):
        if not isinstance(self.content, bytes) or not self.content:
            raise ValueError('XML source requires nonempty captured bytes')
        if not isinstance(self.base_uri, str) or not self.base_uri:
            raise ValueError('XML source requires its captured base URI')
        if not isinstance(self.root, XmlElement) or not callable(self.serialize):
            raise ValueError('XML source requires a tree view and owned serializer')
