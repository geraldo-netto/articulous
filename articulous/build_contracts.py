"""Implementation-independent lifecycle capabilities and validation schemas."""
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .composition_contracts import ExtraArtifact, ExtraPage, RouteReader
from .configuration_contracts import BuildOptions, ConfigurationInput
from .extensions import BuildComposition, CapturedSite
from .publication_contracts import PublicationBackend


class BuildError(ValueError):
    pass


@dataclass(frozen=True)
class Diagnostic:
    message: str
    severity: str = 'error'
    path: str = ''

    def __post_init__(self):
        if self.severity not in ('error', 'warning'):
            raise BuildError('Diagnostic severity must be error or warning')
        if not isinstance(self.message, str) or not isinstance(self.path, str):
            raise BuildError('Diagnostic message and path must be strings')


@dataclass(frozen=True)
class ValidationReport:
    routes: int
    diagnostics: tuple[Diagnostic, ...]

    def __post_init__(self):
        if type(self.routes) is not int or self.routes < 0:
            raise BuildError('Report route count must be a nonnegative integer')
        if not isinstance(self.diagnostics, tuple):
            raise BuildError('Report diagnostics must be an immutable tuple')
        if not all(isinstance(item, Diagnostic) for item in self.diagnostics):
            raise BuildError('Report diagnostics must contain Diagnostic values')


class ArtifactReader(Protocol):
    @property
    def closed(self) -> bool:
        ...

    def read(self, size: int = -1) -> bytes:
        """Read at most the remaining admitted bytes; size is -1 or a nonnegative non-boolean integer."""
        ...


class PreparedBuild(Protocol):
    @property
    def state(self) -> str:
        ...

    @property
    def closed(self) -> bool:
        ...

    @property
    def routes(self) -> RouteReader:
        ...

    def close(self) -> None:
        """Retire capabilities and settle readers; retain the handle to retry a close failure."""
        ...


class StagedBuild(Protocol):
    @property
    def root(self) -> Path:
        ...

    @property
    def routes(self) -> RouteReader:
        ...

    def open_artifact(self, relative: str) -> AbstractContextManager[ArtifactReader]:
        ...

    def assert_unchanged(self) -> None:
        ...


class ValidatedBuild(Protocol):
    @property
    def staged(self) -> StagedBuild:
        ...

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        ...

    def assert_unchanged(self) -> None:
        ...


Validator = Callable[[StagedBuild], Iterable[Diagnostic] | None]
Composer = Callable[[CapturedSite], BuildComposition]


class BuildAPI(Protocol):
    def capture_site(self, cli: BuildOptions, config: ConfigurationInput,
                     project_root: Path) -> AbstractContextManager[CapturedSite]:
        ...

    def prepare_build(self, cli: BuildOptions, config: ConfigurationInput, project_root: Path,
                      *, extra_pages: Iterable[ExtraPage] = (), extra_artifacts: Iterable[ExtraArtifact] = (),
                      backend: PublicationBackend | None = None,
                      composer: Composer | None = None) -> AbstractContextManager[PreparedBuild]:
        ...

    def render_prepared(self, prepared: PreparedBuild) -> StagedBuild:
        ...

    def validate_generated(self, staged: StagedBuild, *, validators: Iterable[Validator] = ()) -> ValidatedBuild:
        ...

    def check_build(self, cli: BuildOptions, config: ConfigurationInput, project_root: Path,
                    *, extra_pages: Iterable[ExtraPage] = (), extra_artifacts: Iterable[ExtraArtifact] = (),
                    validators: Iterable[Validator] = (), composer: Composer | None = None) -> ValidationReport:
        ...
