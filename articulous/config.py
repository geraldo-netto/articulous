"""
Configuration loading, defaults, and CLI overrides.

This module is the single source of truth for the raw config dict
shape. Every other module consumes its output via :class:`BuildCtx`
(see :mod:`articulous.pipeline`).
"""
import json
from pathlib import Path

from .filesystem import write_text_atomic
from .sections import SECTION_NAMES


DEFAULT_CONFIG = {
    "paths": {
        "content_dir": "content",
        "output_dir": "output",
        "xsl_dir": "xsl",
        "assets_dir": "assets",
    },
    "engines": dict.fromkeys(SECTION_NAMES, "lxml"),
    "saxonc": {"home": None},
    "site": {
        "site_name": "My Site",
        "base_url": "https://example.com",
        "languages": ["en"],
        "default_language": "en",
        "pagination": {"per_page": 10, "rss_items": 20},
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


def load_or_create_config(path: Path) -> dict:
    """
    Load config from JSON file. Missing config creates defaults;
    malformed existing config fails fast.
    """
    if not path.exists():
        cfg = _default_config_copy()
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(path, json.dumps(cfg, indent=2))
        return cfg

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid config JSON at {path}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(
            f"Config at {path} is not a JSON object "
            f"(got {type(data).__name__})"
        )

    cfg = _default_config_copy()
    return deep_merge(cfg, data)


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
