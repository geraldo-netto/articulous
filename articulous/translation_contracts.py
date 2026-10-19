"""Authoring contracts independent of HTTP, cache storage and document schemas."""
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class TranslationProvider(Protocol):
    model: str

    @property
    def identity(self) -> tuple:
        ...

    def post(self, system: str, user: str) -> str:
        ...


class TranslationCache(Protocol):
    def get(self, key: str) -> object:
        ...
    def put(self, key: str, value: str) -> None:
        ...
    def delete(self, key: str) -> None:
        ...


@dataclass(frozen=True)
class TranslationJob:
    source: Path
    target: Path
    source_language: str
    target_language: str
    label: str
    kind: str = 'document'


@dataclass(frozen=True)
class XmlTranslationLayout:
    prose_fields: tuple[str, ...]
    metadata_attributes: bool
    provenance_attributes: bool
    language_element: str | None
    digest: Callable[[bytes], str]
    source_element: str = 'translated-from'
    generator_element: str = 'translated-by'
    hash_element: str = 'source-hash'
    body_element: str = 'body'
