"""
Configuration loading, defaults, and CLI overrides.

This module is the single source of truth for the raw config dict
shape. Every other module consumes its output via :class:`BuildCtx`
(see :mod:`articulous.build`).
"""
import json
import logging
from pathlib import Path


DEFAULT_CONFIG = {
    "paths": {
        "content_dir": "content",
        "output_dir": "output",
        "xsl_dir": "xsl",
        "assets_dir": "assets",
    },
    "engines": {
        "articles": "lxml",
        "index": "lxml",
        "tags": "lxml",
        "rss": "lxml",
        "sitemap": "lxml",
        "search": "lxml",
    },
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


def load_or_create_config(path: Path) -> dict:
    """
    Load config from JSON file; fall back to :data:`DEFAULT_CONFIG`
    if missing or invalid.
    """
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        logging.warning(f"Invalid config JSON at {path}: {e}. Using defaults.")
        return json.loads(json.dumps(DEFAULT_CONFIG))

    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    return deep_merge(cfg, data)


def apply_cli_overrides(config: dict, cli, project_root: Path) -> None:
    """Apply CLI overrides to the loaded config, in place."""
    if cli.force_full_build:
        config["build"]["force_full_build"] = True
    if cli.verbose:
        config["logging"]["level"] = "DEBUG"

    for key in ["content_dir", "output_dir", "xsl_dir", "assets_dir"]:
        p = config["paths"][key]
        config["paths"][key] = str((project_root / p).resolve())
