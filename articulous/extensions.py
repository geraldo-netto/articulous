"""Independent, read-only contracts for captured build composition."""
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .articles import PublicationPolicy
from .composition import ExtraPage, Route, _validate_relative_output


@dataclass(frozen=True)
class CapturedArticle:
    title: str
    slug: str
    lang: str
    date: str
    datetime: datetime
    description: str
    tags: tuple[str, ...]
    url: str
    policy: PublicationPolicy
    source_xml: bytes
    modified: str
    author: str
    image: str
    indexing: str
    translation: str


class CapturedSite(Protocol):
    @property
    def languages(self) -> tuple[str, ...]:
        ...

    @property
    def captured_at(self) -> datetime:
        ...

    @property
    def invalid_articles(self) -> int:
        ...

    def articles(self, language: str | None = None) -> Iterator[CapturedArticle]:
        ...


@dataclass(frozen=True)
class TemplateInput:
    path: str
    content: bytes

    def __post_init__(self):
        _validate_relative_output(self.path, reserved=())
        if not isinstance(self.content, bytes):
            raise ValueError('Template input must contain bytes')


TemplateFactory = Callable[[CapturedSite, Iterable[Route]], Iterable[TemplateInput]]


@dataclass(frozen=True)
class BuildComposition:
    pages: tuple[ExtraPage, ...] = ()
    templates: TemplateFactory | None = None

    def __post_init__(self):
        if not isinstance(self.pages, tuple) or not all(isinstance(page, ExtraPage) for page in self.pages):
            raise ValueError('Composition pages must be an ExtraPage tuple')
        if self.templates is not None and not callable(self.templates):
            raise ValueError('Composition templates must be callable')
