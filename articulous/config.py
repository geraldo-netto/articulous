"""
Configuration loading, defaults, and CLI overrides.

This module is the single source of truth for the raw config dict
shape. Every other module consumes its output via :class:`BuildCtx`
(see :mod:`articulous.pipeline`).
"""
import json
import re
from pathlib import Path

from .engines import validate_engines
from .filesystem import (
    assert_disjoint_trees, cache_lock_path, open_regular_file,
    validate_regular_file, write_text_atomic,
)
from .sections import (
    PER_LANG_SECTIONS,
    SECTION_NAMES,
    url_key_for_section,
    validate_base_url,
    validate_url_pattern,
)
from .ownership import ownership_path


DEFAULT_CONFIG = {
    "paths": {
        "content_dir": "content",
        "output_dir": "output",
        "xsl_dir": "xsl",
        "assets_dir": "assets",
    },
    "engines": {
        **dict.fromkeys(SECTION_NAMES, "lxml"),
        "sitemap": "native",
        "search": "native",
    },
    "saxonc": {"home": None},
    "sitemap": {"include_listings": False},
    "robots": {"enabled": False},
    "site": {
        "site_name": "My Site",
        "base_url": "https://example.com",
        "languages": ["en"],
        "default_language": "en",
        "bare_default_language": [],
        "pagination": {"per_page": 10, "rss_items": 20, "paginate_tags": False},
    },
    "urls": {
        "article": "/{lang}/articles/{slug}/",
        "index": "/{lang}/page/{page}/",
        "tag": "/{lang}/tags/{tag}/",
        "rss": "/rss.xml",
        "sitemap": "/sitemap.xml",
        "search": "/search.json",
    },
    "build": {
        "cache_file": ".build-cache.json",
        "parallelism": "auto",
        "force_full_build": False,
    },
    "logging": {"level": "INFO", "file": None},
}

_BARE_SECTIONS = frozenset(PER_LANG_SECTIONS) | {"rss"}
_CONFIG_KEYS = frozenset(DEFAULT_CONFIG)
_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_URL_KEYS = frozenset(url_key_for_section(section) for section in SECTION_NAMES)


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base``. ``override`` wins."""
    for key, value in override.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _default_config_copy() -> dict:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def _require_object(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"config {name} must be an object")
    return value


def _require_exact_keys(value: dict, expected, name: str) -> None:
    actual = set(value)
    expected = set(expected)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(
            f"config {name} keys invalid; missing={missing}, unknown={unknown}"
        )


def _require_string(value, name: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        qualifier = "non-empty " if nonempty else ""
        raise ValueError(f"config {name} must be a {qualifier}string")
    return value


def _require_bool(value, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"config {name} must be a boolean")
    return value


def _require_positive_int(value, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"config {name} must be a positive int, got {value!r}")
    return value


def _require_non_negative_int(value, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(
            f"config {name} must be a non-negative int, got {value!r}"
        )
    return value


def _require_block(config: dict, key: str, expected) -> dict:
    block = _require_object(config[key], key)
    _require_exact_keys(block, expected, key)
    return block


def _validate_paths(config: dict) -> None:
    paths = _require_block(config, "paths", DEFAULT_CONFIG["paths"])
    for key, value in paths.items():
        _require_string(value, f"paths.{key}", nonempty=True)


def _validate_engines(config: dict) -> None:
    _require_block(config, "engines", SECTION_NAMES)
    validate_engines(config)


def _validate_saxonc(config: dict) -> None:
    saxonc = _require_block(config, "saxonc", DEFAULT_CONFIG["saxonc"])
    home = saxonc["home"]
    if home is not None:
        _require_string(home, "saxonc.home")


def _require_languages(languages, default_language) -> None:
    if not isinstance(languages, list) or not languages:
        raise ValueError("config site.languages must be a non-empty list of strings")
    if not all(isinstance(lang, str) and re.fullmatch(r"[A-Za-z0-9_-]+", lang) for lang in languages):
        raise ValueError(
            "config site.languages must contain non-empty identifiers using only "
            "ASCII letters, digits, hyphens, and underscores"
        )
    if len(languages) != len(set(languages)):
        raise ValueError("config site.languages must not contain duplicates")
    _require_string(default_language, "site.default_language", nonempty=True)
    if default_language not in languages:
        raise ValueError(
            "config site.default_language must be present in config site.languages"
        )


def _validate_site(config: dict) -> None:
    site = _require_block(config, "site", DEFAULT_CONFIG["site"])
    _require_string(site["site_name"], "site.site_name")
    _require_string(site["base_url"], "site.base_url")
    _validate_site_base_url(site["base_url"])
    _require_languages(site["languages"], site["default_language"])
    pagination = _require_object(site["pagination"], "site.pagination")
    _require_exact_keys(
        pagination, DEFAULT_CONFIG["site"]["pagination"], "site.pagination"
    )
    _require_positive_int(pagination["per_page"], "site.pagination.per_page")
    _require_bool(pagination["paginate_tags"], "site.pagination.paginate_tags")
    _require_non_negative_int(
        pagination["rss_items"], "site.pagination.rss_items"
    )


def _validate_site_base_url(value: str) -> None:
    try:
        validate_base_url(value)
    except ValueError as error:
        raise ValueError(f"config site.base_url: {error}") from error


def _validate_urls(config: dict) -> None:
    urls = _require_block(config, "urls", _URL_KEYS)
    for section in SECTION_NAMES:
        key = url_key_for_section(section)
        pattern = _require_string(urls[key], f"urls.{key}", nonempty=True)
        validate_url_pattern(section, pattern)


def _validate_build(config: dict) -> None:
    build = _require_block(config, "build", DEFAULT_CONFIG["build"])
    cache_file = _require_string(build["cache_file"], "build.cache_file", nonempty=True)
    if not Path(cache_file).name:
        raise ValueError("config build.cache_file must contain a filename")
    parallelism = build["parallelism"]
    if parallelism != "auto":
        _require_positive_int(parallelism, "build.parallelism")
    _require_bool(build["force_full_build"], "build.force_full_build")


def _validate_logging(config: dict) -> None:
    logging_config = _require_block(config, "logging", DEFAULT_CONFIG["logging"])
    level = _require_string(logging_config["level"], "logging.level", nonempty=True)
    if level.upper() not in _LOG_LEVELS:
        raise ValueError(f"config logging.level must be one of {sorted(_LOG_LEVELS)}")
    log_file = logging_config["file"]
    if log_file is not None:
        _require_string(log_file, "logging.file")


def _validate_sitemap(config: dict) -> None:
    sitemap = _require_block(config, "sitemap", DEFAULT_CONFIG["sitemap"])
    _require_bool(sitemap["include_listings"], "sitemap.include_listings")


def _validate_robots(config: dict) -> None:
    robots = _require_block(config, "robots", DEFAULT_CONFIG["robots"])
    _require_bool(robots["enabled"], "robots.enabled")


def _require_bare_default_language(sections, urls: dict) -> None:
    name = "site.bare_default_language"
    if not isinstance(sections, list) or not all(isinstance(s, str) for s in sections):
        raise ValueError(f"config {name} must be a list of section names")
    if len(sections) != len(set(sections)):
        raise ValueError(f"config {name} must not contain duplicates")
    for section in sections:
        if section not in _BARE_SECTIONS:
            raise ValueError(
                f"config {name} names unknown section {section!r}; "
                f"choose from {sorted(_BARE_SECTIONS)}"
            )
        key = url_key_for_section(section)
        if "/{lang}/" not in urls[key]:
            raise ValueError(
                f"config {name} lists {section!r}, but urls.{key} has no "
                "/{lang}/ segment to drop"
            )


def _validate_bare_default_language(config: dict) -> None:
    _require_bare_default_language(config["site"]["bare_default_language"], config["urls"])


def validate_config(config: dict) -> None:
    config = _require_object(config, "root")
    _require_exact_keys(config, _CONFIG_KEYS, "root")
    for validator in (
        _validate_paths,
        _validate_engines,
        _validate_saxonc,
        _validate_site,
        _validate_urls,
        _validate_bare_default_language,
        _validate_build,
        _validate_logging,
        _validate_sitemap,
        _validate_robots,
    ):
        validator(config)


def load_or_create_config(path: Path) -> dict:
    """
    Load config from JSON file. Missing config creates defaults;
    malformed existing config fails fast.
    """
    if not path.exists():
        cfg = _default_config_copy()
        validate_config(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(path, json.dumps(cfg, indent=2))
        return cfg

    try:
        with open_regular_file(path.resolve()) as source:
            data = json.loads(source.read().decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid config JSON at {path}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(
            f"Config at {path} is not a JSON object "
            f"(got {type(data).__name__})"
        )

    cfg = _default_config_copy()
    deep_merge(cfg, data)
    validate_config(cfg)
    return cfg


def validate_output_layout(paths: dict) -> None:
    output = Path(paths["output_dir"])
    for key in ("content_dir", "xsl_dir", "assets_dir"):
        assert_disjoint_trees(Path(paths[key]), output)


def _paths_alias(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve() or (
        left.exists() and right.exists() and left.samefile(right)
    )


def _validate_state_path(path: Path, root: Path, source: Path, trees) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Build state path resolves outside project root: {path}")
    if _paths_alias(path, source):
        raise ValueError(f"Build state path aliases the configuration input: {path}")
    metadata = validate_regular_file(path)
    if metadata is not None and metadata.st_nlink > 1:
        raise ValueError(f"Build state path contains multiple hardlinks: {path}")
    if any(resolved.is_relative_to(tree) for tree in trees):
        raise ValueError(f"Build state path overlaps a source or output tree: {path}")


def validate_state_paths(config: dict, cli, project_root: Path) -> None:
    root = project_root.resolve()
    source = root / getattr(cli, "config_path", "config.json")
    trees = [(root / path).resolve() for path in config["paths"].values()]
    output = (root / config["paths"]["output_dir"]).resolve()
    if any(path.is_relative_to(output) for path in (source.parent.resolve() / source.name, source.resolve())):
        raise ValueError(f"Configuration input must stay outside the output tree: {source}")
    cache = root / Path(config["build"]["cache_file"]).name
    state = [cache, cache_lock_path(cache),
             output.parent / f".{output.name}.articulous.lock", ownership_path(output)]
    if log_file := config["logging"].get("file"):
        state.append(root / log_file)
    for index, path in enumerate(state):
        _validate_state_path(path, root, source, trees)
        if any(_paths_alias(path, previous) for previous in state[:index]):
            raise ValueError(f"Build state paths must not alias each other: {path}")


def apply_cli_overrides(config: dict, cli, project_root: Path) -> None:
    """
    Apply CLI overrides to the loaded config, in place.

    Each configured directory is resolved relative to ``project_root``
    and then constrained to live underneath it — a config that sets
    ``content_dir: "../../etc"`` will be rejected with ValueError
    instead of silently resolving outside the project tree.
    """
    if cli.force_full_build:
        config["build"]["force_full_build"] = True
    if cli.verbose:
        config["logging"]["level"] = "DEBUG"

    root_resolved = project_root.resolve()
    for key in ["content_dir", "output_dir", "xsl_dir", "assets_dir"]:
        p = config["paths"][key]
        resolved = (project_root / p).resolve()
        if not resolved.is_relative_to(root_resolved):
            raise ValueError(
                f"Config path {key}={p!r} resolves outside project root: "
                f"{resolved} (project_root={root_resolved})"
            )
        config["paths"][key] = str(resolved)
    validate_output_layout(config["paths"])
    validate_state_paths(config, cli, project_root)
