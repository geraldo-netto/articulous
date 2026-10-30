"""Independent, read-only contracts for captured build composition."""
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from types import MappingProxyType

from .article_contracts import PublicationPolicy
from .composition_contracts import ExtraArtifact, ExtraPage, Route, validate_relative_output


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
    display_date: str


class CapturedReader(Protocol):
    def __iter__(self) -> Iterator[CapturedArticle]:
        ...

    def __next__(self) -> CapturedArticle:
        ...

    def close(self) -> None:
        ...


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

    def articles(self, language: str | None = None) -> CapturedReader:
        ...


@dataclass(frozen=True)
class TemplateInput:
    path: str
    content: bytes

    def __post_init__(self):
        validate_relative_output(self.path, reserved=())
        if not isinstance(self.content, bytes):
            raise ValueError('Template input must contain bytes')


TemplateFactory = Callable[[CapturedSite, Iterable[Route]], Iterable[TemplateInput]]
ArtifactFactory = Callable[[CapturedSite, Iterable[Route]], Iterable[ExtraArtifact]]


@dataclass(frozen=True)
class ModelInput:
    source: bytes
    output_path: str
    parameters: Mapping[str, str]

    def __post_init__(self):
        if not isinstance(self.source, bytes) or not self.source:
            raise ValueError('Model input requires captured XML bytes')
        validate_relative_output(self.output_path, reserved=())
        if not isinstance(self.parameters, Mapping):
            raise ValueError('Model parameters must be a string mapping')
        snapshot = dict(self.parameters)
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in snapshot.items()):
            raise ValueError('Model parameters must be a string mapping')
        object.__setattr__(self, 'parameters', MappingProxyType(snapshot))


ModelProjection = Callable[[ModelInput], bytes]


@dataclass(frozen=True)
class BuildComposition:
    pages: tuple[ExtraPage, ...] = ()
    templates: TemplateFactory | None = None
    artifacts: ArtifactFactory | None = None
    project_model: ModelProjection | None = None

    def __post_init__(self):
        if not isinstance(self.pages, tuple) or not all(isinstance(page, ExtraPage) for page in self.pages):
            raise ValueError('Composition pages must be an ExtraPage tuple')
        for name, factory in (('templates', self.templates), ('artifacts', self.artifacts),
                              ('model projection', self.project_model)):
            if factory is not None and not callable(factory):
                raise ValueError(f'Composition {name} must be callable')
