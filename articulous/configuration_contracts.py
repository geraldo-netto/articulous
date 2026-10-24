"""Independent build requests, configuration schemas and engine admission."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol, TypeGuard, TypedDict, get_args

from .sections import SECTION_NAMES

EngineName = Literal['lxml', 'saxonc', 'native']
VALID_ENGINES = frozenset(get_args(EngineName))
NATIVE_SECTIONS = frozenset(('sitemap', 'search'))
ConfigurationInput = Mapping[str, object]


class ConfigurationError(ValueError):
    pass


class PathsConfiguration(TypedDict):
    content_dir: str
    output_dir: str
    xsl_dir: str
    assets_dir: str


class EngineConfiguration(TypedDict):
    articles: EngineName
    index: EngineName
    tags: EngineName
    rss: EngineName
    sitemap: EngineName
    search: EngineName


class SaxonConfiguration(TypedDict):
    home: str | None


class SitemapConfiguration(TypedDict):
    include_listings: bool


class RobotsConfiguration(TypedDict):
    enabled: bool


class PaginationConfiguration(TypedDict):
    per_page: int
    rss_items: int
    paginate_tags: bool
    empty_index: bool


class SiteSettings(TypedDict):
    site_name: str
    base_url: str
    languages: list[str]
    default_language: str
    bare_default_language: list[str]
    pagination: PaginationConfiguration


class UrlConfiguration(TypedDict):
    article: str
    index: str
    index_first: str | None
    tag: str
    rss: str
    sitemap: str
    search: str


class BuildConfiguration(TypedDict):
    cache_file: str
    parallelism: int | Literal['auto']
    force_full_build: bool


class LoggingConfiguration(TypedDict):
    level: str
    file: str | None


class SiteConfiguration(TypedDict):
    paths: PathsConfiguration
    engines: EngineConfiguration
    saxonc: SaxonConfiguration
    sitemap: SitemapConfiguration
    robots: RobotsConfiguration
    site: SiteSettings
    urls: UrlConfiguration
    build: BuildConfiguration
    logging: LoggingConfiguration


CONFIG_KEYS = SiteConfiguration.__required_keys__
CONFIG_BLOCK_KEYS = MappingProxyType({
    'paths': PathsConfiguration.__required_keys__, 'engines': EngineConfiguration.__required_keys__,
    'saxonc': SaxonConfiguration.__required_keys__, 'sitemap': SitemapConfiguration.__required_keys__,
    'robots': RobotsConfiguration.__required_keys__, 'site': SiteSettings.__required_keys__,
    'urls': UrlConfiguration.__required_keys__, 'build': BuildConfiguration.__required_keys__,
    'logging': LoggingConfiguration.__required_keys__, 'site.pagination': PaginationConfiguration.__required_keys__,
})


def valid_engine_name(value: object) -> TypeGuard[EngineName]:
    return isinstance(value, str) and value in VALID_ENGINES


def _engine_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ConfigurationError('Engines must be a mapping')
    if any(key not in SECTION_NAMES for key in value):
        raise ConfigurationError('Unknown engine section')
    return value


def validate_engines(values: object) -> None:
    engines = _engine_mapping(values)
    bad = {section: name for section, name in engines.items() if not valid_engine_name(name)}
    if bad:
        raise ConfigurationError(f'Unknown engine(s) configured: {bad}. Valid engines: {sorted(VALID_ENGINES)}')
    _validate_native_sections(engines)


def _validate_native_sections(engines):
    invalid = sorted(section for section, name in engines.items()
                     if name == 'native' and section not in NATIVE_SECTIONS)
    if invalid:
        raise ConfigurationError(f'Native engine is only supported for {sorted(NATIVE_SECTIONS)}; got {invalid}')


class ConfigurationOptions(Protocol):
    @property
    def config_path(self) -> Path:
        ...
    @property
    def force_full_build(self) -> bool:
        ...
    @property
    def verbose(self) -> bool:
        ...


class BuildOptions(ConfigurationOptions, Protocol):
    @property
    def only_sections(self) -> Sequence[str] | None:
        ...
    @property
    def only_langs(self) -> Sequence[str] | None:
        ...
    @property
    def only_slugs(self) -> Sequence[str] | None:
        ...
    @property
    def dry_run(self) -> bool:
        ...


def _selection_names(value, name):
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ConfigurationError(f'{name} must be a sequence of names')
    if any(not isinstance(item, str) or not item for item in value):
        raise ConfigurationError(f'{name} must contain nonempty string names')
    return tuple(dict.fromkeys(value))


@dataclass(frozen=True)
class BuildRequest:
    config_path: Path = Path('config.json')
    only_sections: Sequence[str] | None = None
    only_langs: Sequence[str] | None = None
    only_slugs: Sequence[str] | None = None
    dry_run: bool = False
    force_full_build: bool = False
    verbose: bool = False

    def __post_init__(self):
        for name in ('dry_run', 'force_full_build', 'verbose'):
            if type(getattr(self, name)) is not bool:
                raise ConfigurationError(f'{name} must be boolean')
        for name in ('only_sections', 'only_langs', 'only_slugs'):
            object.__setattr__(self, name, _selection_names(getattr(self, name), name))
        _request_sections(self.only_sections)
        if not isinstance(self.config_path, Path):
            raise ConfigurationError('config_path must be a Path')


def _request_sections(values):
    if values is not None and any(name not in SECTION_NAMES for name in values):
        raise ConfigurationError('Unknown build section')
