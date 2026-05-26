#!/usr/bin/env python3

# ================================================================
# MODULE 1 — CLI PARSING
# ================================================================

import argparse
from pathlib import Path
import json
import logging
import sys
import tempfile
import threading
from dataclasses import dataclass, field, replace as _dc_replace
from datetime import datetime
from typing import Callable, Optional
from urllib.parse import quote
from xml.sax.saxutils import escape as _xml_escape


def parse_cli_args(argv=None):
    """
    Parse command-line arguments for the static site generator.
    """
    parser = argparse.ArgumentParser(
        description="Static Site Generator — XML + XSLT pipeline"
    )

    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Path to configuration file",
    )

    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Comma-separated list of sections to build (articles,index,tags,rss,sitemap,search)",
    )

    parser.add_argument(
        "--lang",
        action="append",
        help="Limit build to specific languages (can repeat)",
    )

    parser.add_argument(
        "--slug",
        action="append",
        help="Limit build to specific article slugs (can repeat)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without writing output files",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force full rebuild, ignoring cache",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser.parse_args(argv)


class CliOptions:
    """
    Wrapper around parsed CLI arguments.
    Normalizes lists and comma-separated values.
    """

    def __init__(self, args):
        self.config_path = Path(args.config)

        # Normalize --only
        if args.only:
            self.only_sections = [s.strip() for s in args.only.split(",") if s.strip()]
        else:
            self.only_sections = None

        # Normalize --lang
        self.only_langs = args.lang if args.lang else None

        # Normalize --slug
        self.only_slugs = args.slug if args.slug else None

        self.dry_run = args.dry_run
        self.force_full_build = args.force
        self.verbose = args.verbose

# ================================================================
# MODULE 2 — CONFIG LOADING + OVERRIDES
# ================================================================

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
    "saxonc": {
        "home": None,
    },
    "site": {
        "site_name": "My Site",
        "base_url": "https://example.com",
        "languages": ["en"],
        "default_language": "en",
        "pagination": {
            "per_page": 10,
            "rss_items": 20,
        },
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
    "logging": {
        "level": "INFO",
        "file": None,
    },
}


def deep_merge(base, override):
    """
    Recursively merge two dictionaries.
    Values in `override` take precedence.
    """
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


def load_or_create_config(path: Path):
    """
    Load config from JSON file.
    If missing or invalid, fall back to DEFAULT_CONFIG.
    """
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))

    try:
        data = json.loads(path.read_text())
    except Exception:
        return json.loads(json.dumps(DEFAULT_CONFIG))

    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    return deep_merge(cfg, data)


def apply_cli_overrides(config, cli: CliOptions, project_root: Path) -> None:
    """
    Apply CLI overrides to the loaded config, in place.
    """
    if cli.force_full_build:
        config["build"]["force_full_build"] = True

    if cli.verbose:
        config["logging"]["level"] = "DEBUG"

    for key in ["content_dir", "output_dir", "xsl_dir", "assets_dir"]:
        p = config["paths"][key]
        config["paths"][key] = str((project_root / p).resolve())

# ================================================================
# MODULE 3 — LOGGING SETUP
# ================================================================

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _resolve_log_level(level_name: str) -> int:
    name = (level_name or "INFO").upper()
    if name not in _VALID_LOG_LEVELS:
        name = "INFO"
    return getattr(logging, name)


def setup_logging(config, project_root: Path, verbose=False):
    """
    Configure logging idempotently. Safe to call multiple times.
    """
    level = logging.DEBUG if verbose else _resolve_log_level(config["logging"]["level"])

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(level)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(stream)

    log_file = config["logging"].get("file")
    if log_file:
        file_path = project_root / log_file
        fh = logging.FileHandler(file_path, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(fh)

    logging.debug("Logging initialized")

# ================================================================
# MODULE 4 — TRANSFORM ENGINE (SaxonC + lxml)
# ================================================================

import subprocess
import shutil
from lxml import etree

VALID_ENGINES = {"saxonc", "lxml"}

SECTION_XSL = {
    "articles": "article.xsl",
    "index": "index.xsl",
    "tags": "tags.xsl",
    "rss": "rss.xsl",
    "sitemap": "sitemap.xsl",
    "search": "search.xsl",
}


@dataclass(frozen=True)
class EngineSpec:
    """
    Pairs an engine name with the resources it needs to run.
    Replaces the old (engine_str, saxonc_bin) tuple plumbing.
    """
    name: str
    saxonc_bin: Optional[Path] = None


def validate_engines(config):
    """
    Ensure every section's configured engine is one we know how to run.
    Raises ValueError on unknown engine names.
    """
    bad = {
        section: name
        for section, name in config["engines"].items()
        if name not in VALID_ENGINES
    }
    if bad:
        raise ValueError(
            f"Unknown engine(s) configured: {bad}. "
            f"Valid engines: {sorted(VALID_ENGINES)}"
        )


def _safe_xml_parser():
    # Disable external entity resolution, DTD loading, and network access (XXE-safe).
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)


def configure_saxonc(config):
    """
    Validate SaxonC installation and return the path to the Transform binary.
    If SaxonC is not available, return None and the system will fall back to lxml.
    """
    saxon_home = config["saxonc"].get("home")
    if not saxon_home:
        logging.debug("SaxonC home not configured — using lxml engine")
        return None

    transform_bin = Path(saxon_home) / "bin" / "Transform"
    if not transform_bin.exists():
        logging.warning(f"SaxonC Transform binary not found at: {transform_bin}")
        return None

    logging.info(f"SaxonC detected at: {transform_bin}")
    return transform_bin


def run_transform(engine: EngineSpec, xml_path, xsl_path, output_path, dry_run=False):
    """
    Run an XSLT transformation using the engine specified by ``engine``.
    Falls through to the lxml engine when SaxonC was requested but its
    binary is not available.
    """

    xml_path = Path(xml_path)
    xsl_path = Path(xsl_path)
    output_path = Path(output_path)

    if dry_run:
        logging.debug(f"[DRY RUN] Would transform {xml_path} using {xsl_path}")
        return

    if engine.name == "saxonc" and engine.saxonc_bin:
        cmd = [
            str(engine.saxonc_bin),
            f"-s:{xml_path}",
            f"-xsl:{xsl_path}",
            f"-o:{output_path}",
        ]
        logging.debug(f"Running SaxonC: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            logging.error(f"SaxonC transform failed: {e}")
            raise
        return

    logging.debug(f"Running lxml transform: {xml_path} -> {output_path}")
    try:
        dom = etree.parse(str(xml_path), parser=_safe_xml_parser())
        xslt = etree.XSLT(etree.parse(str(xsl_path), parser=_safe_xml_parser()))
        result = xslt(dom)
    except Exception as e:
        logging.error(f"lxml transform failed: {e}")
        raise

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(str(result), encoding="utf-8")

# ================================================================
# MODULE 4.5 — DEPENDENCY CHECKER
# ================================================================

REQUIRED_XSL_FILES = sorted(set(SECTION_XSL.values()))


def check_dependencies(config, project_root: Path):
    """
    Ensure that required directories and XSL files exist.
    Raises exceptions if anything is missing.
    """

    paths = config["paths"]

    content_dir = project_root / paths["content_dir"]
    xsl_dir = project_root / paths["xsl_dir"]
    output_dir = project_root / paths["output_dir"]

    # ------------------------------------------------------------
    # Check directories
    # ------------------------------------------------------------
    for d, name in [
        (content_dir, "content_dir"),
        (xsl_dir, "xsl_dir"),
        (output_dir, "output_dir"),
    ]:
        if not d.exists():
            raise FileNotFoundError(f"Required directory '{name}' not found: {d}")

    # ------------------------------------------------------------
    # Check XSL files
    # ------------------------------------------------------------
    pages_dir = xsl_dir / "pages"
    if not pages_dir.exists():
        raise FileNotFoundError(f"Missing XSL pages directory: {pages_dir}")

    for fname in REQUIRED_XSL_FILES:
        f = pages_dir / fname
        if not f.exists():
            raise FileNotFoundError(f"Missing required XSL file: {f}")

    logging.debug("All dependencies verified successfully.")

# ================================================================
# MODULE 6 — ARTICLE PARSER
# ================================================================

def normalize_slug(text: str) -> str:
    """
    Convert arbitrary text into a URL-safe slug.
    """
    import re
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def parse_article_xml(path: Path, default_lang: str = "en"):
    """
    Parse a single article XML file and return a dictionary of metadata.
    Returns None if the article cannot be parsed or has no usable date.

    Expected structure:

    <article>
      <title>...</title>
      <date>YYYY-MM-DD</date>
      <description>...</description>
      <lang>en</lang>          <!-- optional, defaults to default_lang -->
      <tag>...</tag>
    </article>
    """
    try:
        tree = etree.parse(str(path), parser=_safe_xml_parser())
        root = tree.getroot()
    except (etree.XMLSyntaxError, OSError) as e:
        logging.error(f"Failed to parse XML: {path} — {e}")
        return None

    def get_text(tag):
        el = root.find(tag)
        return el.text.strip() if el is not None and el.text else ""

    title = get_text("title")
    date = get_text("date")
    desc = get_text("description")
    lang = get_text("lang") or default_lang

    tags = [el.text.strip() for el in root.findall("tag") if el.text]
    slug = normalize_slug(title) if title else normalize_slug(path.stem)

    try:
        dt = datetime.fromisoformat(date)
    except (ValueError, TypeError):
        logging.warning(
            f"Article {path} has missing/invalid date '{date}' — skipping"
        )
        return None

    return {
        "title": title,
        "date": date,
        "datetime": dt,
        "description": desc,
        "tags": tags,
        "slug": slug,
        "lang": lang,
        "source_path": path,
    }


def discover_article_files(content_dir: Path):
    """
    Recursively find all .xml files in the content directory.
    """
    return sorted(content_dir.rglob("*.xml"))


def load_articles(content_dir: Path, default_lang: str = "en"):
    """
    Load and parse all articles from the content directory.
    """
    articles = []
    for xml_file in discover_article_files(content_dir):
        meta = parse_article_xml(xml_file, default_lang=default_lang)
        if meta:
            articles.append(meta)

    articles.sort(key=lambda a: a["datetime"], reverse=True)
    return articles

# ================================================================
# MODULE 7 — BUILD CONTEXT + MODEL BUILDERS
# ================================================================

@dataclass(frozen=True)
class BuildCtx:
    """
    Narrow, typed view of the inputs a build step needs.

    Decouples model/section builders from the raw config dict shape:
    callers see fields with types, not ``config["site"]["pagination"]
    ["per_page"]`` chains.
    """
    # paths
    xsl_dir: Path
    output_dir: Path
    assets_dir: Path
    # per-build scratch directory; set by run_build after output_dir exists
    temp_dir: Optional[Path] = None
    # build flags
    force: bool = False
    dry_run: bool = False
    # engine map: section name -> EngineSpec
    engines: dict = field(default_factory=dict)
    # site / URL model
    base_url: str = ""
    languages: list = field(default_factory=list)
    default_language: str = "en"
    url_patterns: dict = field(default_factory=dict)
    per_page: int = 10
    rss_items: int = 20

    def xsl_for(self, section: str) -> Path:
        return self.xsl_dir / "pages" / SECTION_XSL[section]

    def engine_for(self, section: str) -> EngineSpec:
        return self.engines[section]


def build_ctx_from_config(config, saxonc_bin: Optional[Path], dry_run: bool) -> BuildCtx:
    """
    Project the raw config dict + resolved Saxon binary into a BuildCtx.

    This is the only place that reads the config dict's deep shape; every
    downstream function works against the BuildCtx fields.
    """
    engines = {
        section: EngineSpec(name=name, saxonc_bin=saxonc_bin)
        for section, name in config["engines"].items()
    }
    return BuildCtx(
        xsl_dir=Path(config["paths"]["xsl_dir"]),
        output_dir=Path(config["paths"]["output_dir"]),
        assets_dir=Path(config["paths"]["assets_dir"]),
        # temp_dir is None until run_build allocates a per-build scratch dir.
        temp_dir=None,
        force=config["build"]["force_full_build"],
        dry_run=dry_run,
        engines=engines,
        base_url=config["site"]["base_url"],
        languages=list(config["site"]["languages"]),
        default_language=config["site"]["default_language"],
        url_patterns=dict(config["urls"]),
        per_page=config["site"]["pagination"]["per_page"],
        rss_items=config["site"]["pagination"]["rss_items"],
    )


def build_rel_path_from_pattern(pattern: str, **kwargs):
    """
    Build a relative output path from a URL pattern.
    Example:
        pattern="/{lang}/articles/{slug}/"
        -> "en/articles/my-post/index.html"
    """
    url = pattern.format(**kwargs).strip("/")
    return Path(url) / "index.html"


def build_url_from_pattern(base_url: str, pattern: str, **kwargs):
    """
    Build a full absolute URL from a pattern.
    """
    rel = pattern.format(**kwargs).lstrip("/")
    return f"{base_url.rstrip('/')}/{rel}"


# ------------------------------------------------------------
# Index Pages (pagination)
# ------------------------------------------------------------

def build_index_models(articles, ctx: BuildCtx):
    """
    Build paginated index models, one set per configured language.
    """
    pattern = ctx.url_patterns["index"]

    pages = []
    for lang in ctx.languages:
        lang_articles = [a for a in articles if a["lang"] == lang]
        total = len(lang_articles)
        if total == 0:
            continue
        num_pages = (total + ctx.per_page - 1) // ctx.per_page
        for page in range(1, num_pages + 1):
            start = (page - 1) * ctx.per_page
            end = start + ctx.per_page
            subset = lang_articles[start:end]
            pages.append({
                "lang": lang,
                "page": page,
                "total_pages": num_pages,
                "articles": subset,
                "output_path": build_rel_path_from_pattern(pattern, lang=lang, page=page),
                "url": build_url_from_pattern(ctx.base_url, pattern, lang=lang, page=page),
            })

    return pages


# ------------------------------------------------------------
# Tag Pages
# ------------------------------------------------------------

def build_tags_models(articles, ctx: BuildCtx):
    """
    Build tag pages: one page per (language, tag) pair.
    Tag values are slugified for filesystem paths and URL-encoded for URLs.
    """
    pattern = ctx.url_patterns["tag"]

    models = []
    for lang in ctx.languages:
        lang_articles = [a for a in articles if a["lang"] == lang]
        tag_map = {}
        for art in lang_articles:
            for tag in art.get("tags", []):
                tag_map.setdefault(tag, []).append(art)

        for tag, items in tag_map.items():
            tag_slug = normalize_slug(tag)
            if not tag_slug:
                logging.warning(f"Tag {tag!r} slugifies to empty string — skipping")
                continue
            url_tag = quote(tag_slug, safe="")
            models.append({
                "lang": lang,
                "tag": tag,
                "tag_slug": tag_slug,
                "articles": items,
                "output_path": build_rel_path_from_pattern(pattern, lang=lang, tag=tag_slug),
                "url": build_url_from_pattern(ctx.base_url, pattern, lang=lang, tag=url_tag),
            })

    return models


# ------------------------------------------------------------
# RSS Feed
# ------------------------------------------------------------

def build_rss_model(articles, ctx: BuildCtx):
    """
    Build RSS feed model.
    """
    pattern = ctx.url_patterns["rss"]
    return {
        "articles": articles[:ctx.rss_items],
        "output_path": Path(pattern.lstrip("/")),
        "url": build_url_from_pattern(ctx.base_url, pattern),
    }


# ------------------------------------------------------------
# Sitemap
# ------------------------------------------------------------

def build_sitemap_model(articles, ctx: BuildCtx):
    """
    Build sitemap model.
    """
    pattern = ctx.url_patterns["sitemap"]
    return {
        "urls": [art["url"] for art in articles],
        "output_path": Path(pattern.lstrip("/")),
        "url": build_url_from_pattern(ctx.base_url, pattern),
    }


# ------------------------------------------------------------
# Search Index (JSON)
# ------------------------------------------------------------

def build_search_model(articles, ctx: BuildCtx):
    """
    Build search index model.
    """
    pattern = ctx.url_patterns["search"]
    items = [
        {
            "title": art["title"],
            "description": art["description"],
            "url": art["url"],
            "tags": art["tags"],
        }
        for art in articles
    ]
    return {
        "items": items,
        "output_path": Path(pattern.lstrip("/")),
        "url": build_url_from_pattern(ctx.base_url, pattern),
    }

# ================================================================
# MODULE 8 — INCREMENTAL BUILD CACHE
# ================================================================

import hashlib
import json


def file_hash(path: Path) -> str:
    """
    Compute a SHA-256 hash of a file's contents.
    Raises FileNotFoundError if the path does not exist.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_cache(cache_path: Path):
    """
    Load the build cache from disk.
    Returns an empty dict if missing or invalid.
    """
    if not cache_path.exists():
        logging.debug("Cache file not found — starting with empty cache")
        return {}

    try:
        data = json.loads(cache_path.read_text())
        if isinstance(data, dict):
            logging.debug("Cache loaded successfully")
            return data
    except Exception as e:
        logging.warning(f"Failed to load cache: {e}")

    logging.debug("Cache invalid — starting fresh")
    return {}


def save_cache(cache_path: Path, cache: dict):
    """
    Save the build cache to disk.
    """
    try:
        cache_path.write_text(json.dumps(cache, indent=2))
        logging.debug("Cache saved successfully")
    except Exception as e:
        logging.error(f"Failed to save cache: {e}")


def should_rebuild(key: str, cache: dict, new_hashes: tuple, force: bool) -> bool:
    """
    Determine whether a page should be rebuilt.

    key: unique identifier for the page (e.g., slug or output path)
    cache: dict of previous hashes
    new_hashes: (xml_hash, xsl_hash)
    force: force full rebuild flag
    """
    if force:
        return True

    old = cache.get(key)
    if not old:
        return True

    return old != list(new_hashes)


_cache_lock = threading.Lock()


def update_cache(cache: dict, key: str, new_hashes: tuple):
    """
    Update the cache entry for a given page. Thread-safe: workers
    commit their own entries on success.
    """
    with _cache_lock:
        cache[key] = list(new_hashes)

# ================================================================
# MODULE 9 — PARALLEL EXECUTOR
# ================================================================

from concurrent.futures import ThreadPoolExecutor, as_completed


def run_parallel_tasks(tasks, max_workers="auto"):
    """
    Run a list of callables in parallel.

    On failure: cancel any tasks that have not yet started, drain the
    rest, log every error, and re-raise. If more than one task failed,
    raise an ExceptionGroup so no individual error is lost.
    """

    if max_workers == "auto":
        import os
        max_workers = max(4, os.cpu_count() or 4)

    results = []
    errors = []
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {pool.submit(fn): fn for fn in tasks}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                logging.error(f"Task failed: {e}")
                errors.append(e)
                # Cancel anything still queued; in-flight tasks finish
                # naturally so their errors are captured too.
                for other in futures:
                    if not other.done():
                        other.cancel()
    finally:
        pool.shutdown(wait=True)

    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise ExceptionGroup("parallel task failures", errors)
    return results

# ================================================================
# MODULE 10 — BUILD PIPELINE
# ================================================================

def ensure_parent_dir(path: Path, dry_run=False):
    """
    Ensure the parent directory of a file exists.
    """
    parent = path.parent
    if not parent.exists() and not dry_run:
        parent.mkdir(parents=True, exist_ok=True)


def copy_assets(ctx: BuildCtx):
    """
    Mirror the configured assets directory into the output tree at
    ``<output_dir>/assets``. No-op if the assets directory is missing.
    """
    if not ctx.assets_dir.exists():
        logging.debug(f"Assets directory not present, skipping: {ctx.assets_dir}")
        return

    dest = ctx.output_dir / "assets"

    if ctx.dry_run:
        logging.debug(f"[DRY RUN] Would copy assets: {ctx.assets_dir} -> {dest}")
        return

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ctx.assets_dir, dest)
    logging.info(f"Copied assets: {ctx.assets_dir} -> {dest}")


def write_json(path: Path, data, dry_run=False):
    """
    Write JSON to disk.
    """
    if dry_run:
        logging.debug(f"[DRY RUN] Would write JSON: {path}")
        return
    ensure_parent_dir(path)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ------------------------------------------------------------
# Shared helpers for XSLT-driven sections
# ------------------------------------------------------------

def _xml_doc(root_tag: str, children: list) -> str:
    """
    Wrap a list of pre-rendered XML fragment strings in a single root
    element. Children are joined as-is; callers are responsible for
    escaping leaf text via _article_xml / _rss_item_xml / _sitemap_url_xml.
    """
    return f"<{root_tag}>{''.join(children)}</{root_tag}>"


def _article_xml(a: dict) -> str:
    return (
        f"<article><title>{_xml_escape(a['title'])}</title>"
        f"<url>{_xml_escape(a['url'])}</url></article>"
    )


def _rss_item_xml(a: dict) -> str:
    return (
        f"<item><title>{_xml_escape(a['title'])}</title>"
        f"<url>{_xml_escape(a['url'])}</url></item>"
    )


def _sitemap_url_xml(url: str) -> str:
    return f"<url>{_xml_escape(url)}</url>"


def _make_xslt_task(
    *,
    xml_path: Path,
    xsl_path: Path,
    output_path: Path,
    cache: dict,
    cache_key: str,
    engine: EngineSpec,
    ctx: BuildCtx,
) -> Optional[Callable]:
    """
    Build a transform task for an XSLT-driven section.
    Returns None if the cache says the output is up to date.

    The cache entry is committed *inside* the task closure, after a
    successful run_transform call. A failed transform leaves the prior
    cache entry untouched, so the next build will retry rather than
    silently skip the broken section.
    """
    xml_hash = file_hash(xml_path)
    xsl_hash = file_hash(xsl_path)
    if not should_rebuild(cache_key, cache, (xml_hash, xsl_hash), ctx.force):
        return None

    hashes = (xml_hash, xsl_hash)

    def task(xml_path=xml_path, xsl_path=xsl_path, output_path=output_path):
        run_transform(
            engine, xml_path, xsl_path, output_path, dry_run=ctx.dry_run,
        )
        update_cache(cache, cache_key, hashes)

    return task


def _make_xslt_task_with_temp(
    *,
    xml_temp: Path,
    xml_content: str,
    ctx: BuildCtx,
    **kwargs,
) -> Optional[Callable]:
    """
    Variant of _make_xslt_task for sections that synthesise their XML
    model into a temp file before transforming.

    The temp file is always written (even under dry-run) because
    hashing the model XML is part of the cache decision. dry_run is
    enforced inside run_transform, where it skips the actual output.
    """
    xml_temp.parent.mkdir(parents=True, exist_ok=True)
    xml_temp.write_text(xml_content, encoding="utf-8")
    return _make_xslt_task(xml_path=xml_temp, ctx=ctx, **kwargs)


# ------------------------------------------------------------
# Section Builders — Articles
# ------------------------------------------------------------

def build_articles_section(articles, ctx: BuildCtx, cache):
    """
    Build all article pages.
    """
    tasks = []
    xsl_path = ctx.xsl_for("articles")
    engine = ctx.engine_for("articles")
    pattern = ctx.url_patterns["article"]

    for art in articles:
        art["url"] = build_url_from_pattern(
            ctx.base_url, pattern, lang=art["lang"], slug=art["slug"],
        )
        output_path = ctx.output_dir / build_rel_path_from_pattern(
            pattern, lang=art["lang"], slug=art["slug"],
        )
        task = _make_xslt_task(
            xml_path=art["source_path"],
            xsl_path=xsl_path,
            output_path=output_path,
            cache=cache,
            cache_key=f"article:{art['lang']}:{art['slug']}",
            engine=engine,
            ctx=ctx,
        )
        if task is None:
            logging.debug(f"Skipping unchanged article: {art['slug']}")
            continue
        tasks.append(task)

    return tasks


# ------------------------------------------------------------
# Section Builders — Index Pages
# ------------------------------------------------------------

def build_index_section(articles, ctx: BuildCtx, cache):
    """
    Build paginated index pages.
    """
    tasks = []
    xsl_path = ctx.xsl_for("index")
    engine = ctx.engine_for("index")

    for model in build_index_models(articles, ctx):
        xml_content = _xml_doc(
            "index", [_article_xml(a) for a in model["articles"]],
        )
        task = _make_xslt_task_with_temp(
            xml_temp=ctx.temp_dir / f"index-{model['lang']}-{model['page']}.xml",
            xml_content=xml_content,
            xsl_path=xsl_path,
            output_path=ctx.output_dir / model["output_path"],
            cache=cache,
            cache_key=f"index:{model['lang']}:{model['page']}",
            engine=engine,
            ctx=ctx,
        )
        if task is None:
            logging.debug(f"Skipping unchanged index page {model['page']}")
            continue
        tasks.append(task)

    return tasks

# ------------------------------------------------------------
# Section Builders — Tags
# ------------------------------------------------------------

def build_tags_section(articles, ctx: BuildCtx, cache):
    """
    Build tag pages.
    """
    tasks = []
    xsl_path = ctx.xsl_for("tags")
    engine = ctx.engine_for("tags")

    for model in build_tags_models(articles, ctx):
        lang, tag_slug = model["lang"], model["tag_slug"]
        xml_content = _xml_doc(
            "tag", [_article_xml(a) for a in model["articles"]],
        )
        task = _make_xslt_task_with_temp(
            xml_temp=ctx.temp_dir / f"tag-{lang}-{tag_slug}.xml",
            xml_content=xml_content,
            xsl_path=xsl_path,
            output_path=ctx.output_dir / model["output_path"],
            cache=cache,
            cache_key=f"tag:{lang}:{tag_slug}",
            engine=engine,
            ctx=ctx,
        )
        if task is None:
            logging.debug(f"Skipping unchanged tag page: {lang}/{tag_slug}")
            continue
        tasks.append(task)

    return tasks


# ------------------------------------------------------------
# Section Builders — RSS
# ------------------------------------------------------------

def build_rss_section(articles, ctx: BuildCtx, cache):
    """
    Build RSS feed.
    """
    model = build_rss_model(articles, ctx)
    xml_content = _xml_doc("rss", [_rss_item_xml(a) for a in model["articles"]])
    task = _make_xslt_task_with_temp(
        xml_temp=ctx.temp_dir / "rss.xml",
        xml_content=xml_content,
        xsl_path=ctx.xsl_for("rss"),
        output_path=ctx.output_dir / model["output_path"],
        cache=cache,
        cache_key="rss",
        engine=ctx.engine_for("rss"),
        ctx=ctx,
    )
    if task is None:
        logging.debug("Skipping unchanged RSS feed")
        return []
    return [task]


# ------------------------------------------------------------
# Section Builders — Sitemap
# ------------------------------------------------------------

def build_sitemap_section(articles, ctx: BuildCtx, cache):
    """
    Build sitemap.xml.
    """
    model = build_sitemap_model(articles, ctx)
    xml_content = _xml_doc("sitemap", [_sitemap_url_xml(u) for u in model["urls"]])
    task = _make_xslt_task_with_temp(
        xml_temp=ctx.temp_dir / "sitemap.xml",
        xml_content=xml_content,
        xsl_path=ctx.xsl_for("sitemap"),
        output_path=ctx.output_dir / model["output_path"],
        cache=cache,
        cache_key="sitemap",
        engine=ctx.engine_for("sitemap"),
        ctx=ctx,
    )
    if task is None:
        logging.debug("Skipping unchanged sitemap")
        return []
    return [task]


# ------------------------------------------------------------
# Section Builders — Search Index
# ------------------------------------------------------------

def build_search_section(articles, ctx: BuildCtx, cache):
    """
    Build search.json. No XSLT needed; pure JSON write.
    """
    model = build_search_model(articles, ctx)
    items = model["items"]
    output_path = ctx.output_dir / model["output_path"]
    json_hash = hashlib.sha256(json.dumps(items).encode("utf-8")).hexdigest()

    if not should_rebuild("search", cache, (json_hash, "json"), ctx.force):
        logging.debug("Skipping unchanged search index")
        return []

    def task(output_path=output_path, items=items, json_hash=json_hash):
        write_json(output_path, items, dry_run=ctx.dry_run)
        update_cache(cache, "search", (json_hash, "json"))
    return [task]


# ------------------------------------------------------------
# Section dispatch table
# ------------------------------------------------------------

SECTION_BUILDERS = {
    "articles": build_articles_section,
    "index": build_index_section,
    "tags": build_tags_section,
    "rss": build_rss_section,
    "sitemap": build_sitemap_section,
    "search": build_search_section,
}


def _filter_articles(articles, cli: CliOptions):
    """Apply CLI language/slug filters."""
    if cli.only_langs:
        wanted = set(cli.only_langs)
        articles = [a for a in articles if a["lang"] in wanted]
    if cli.only_slugs:
        wanted = set(cli.only_slugs)
        articles = [a for a in articles if a["slug"] in wanted]
    return articles


def _collect_tasks(articles, ctx: BuildCtx, cache, only_sections):
    """
    Dispatch each requested section to its builder and collect the
    resulting task callables. ``only_sections`` is None (all sections)
    or an iterable of section names to keep.
    """
    wanted = set(only_sections) if only_sections else None
    tasks = []
    for name, builder in SECTION_BUILDERS.items():
        if wanted is not None and name not in wanted:
            continue
        tasks += builder(articles, ctx, cache)
    return tasks

# ------------------------------------------------------------
# Full Build Pipeline
# ------------------------------------------------------------

def _cache_path_for(config, project_root: Path) -> Path:
    # Reduce user-controlled config to a bare filename to prevent path traversal.
    cache_file_name = Path(config["build"]["cache_file"]).name
    return project_root / cache_file_name


def run_build(cli: CliOptions, config, project_root: Path):
    """
    Orchestrate the entire build process.
    """
    logging.info("Starting build...")

    validate_engines(config)
    cache_path = _cache_path_for(config, project_root)
    cache = load_cache(cache_path)

    saxonc_bin = configure_saxonc(config)
    ctx = build_ctx_from_config(config, saxonc_bin, dry_run=cli.dry_run)

    copy_assets(ctx)

    # Per-build scratch directory. Allocating under output_dir gives each
    # concurrent invocation of sitegen its own namespace for model XML
    # files, so they cannot collide on identical temp paths.
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=".sitegen-", dir=ctx.output_dir))
    ctx = _dc_replace(ctx, temp_dir=temp_dir)

    try:
        content_dir = Path(config["paths"]["content_dir"])
        articles = load_articles(content_dir, default_lang=ctx.default_language)
        articles = _filter_articles(articles, cli)

        tasks = _collect_tasks(articles, ctx, cache, cli.only_sections)

        if tasks:
            logging.info(f"Running {len(tasks)} tasks in parallel...")
            run_parallel_tasks(tasks, config["build"]["parallelism"])
        else:
            logging.info("Nothing to build — all pages up to date.")

        if not cli.dry_run:
            save_cache(cache_path, cache)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    logging.info("Build complete.")


# ------------------------------------------------------------
# CLI Entrypoint
# ------------------------------------------------------------

if __name__ == "__main__":
    args = parse_cli_args()
    cli = CliOptions(args)

    project_root = Path(__file__).parent.resolve()

    config = load_or_create_config(cli.config_path)
    apply_cli_overrides(config, cli, project_root)

    setup_logging(config, project_root, verbose=cli.verbose)

    check_dependencies(config, project_root)

    run_build(cli, config, project_root)

