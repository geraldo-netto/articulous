#!/usr/bin/env python3

# ================================================================
# MODULE 1 — CLI PARSING
# ================================================================

import argparse
from pathlib import Path
import json
import logging
import sys
from datetime import datetime


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


def apply_cli_overrides(config, cli: CliOptions, project_root: Path):
    """
    Apply CLI overrides to the loaded config.
    """
    if cli.force_full_build:
        config["build"]["force_full_build"] = True

    if cli.verbose:
        config["logging"]["level"] = "DEBUG"

    # Normalize paths relative to project root
    for key in ["content_dir", "output_dir", "xsl_dir", "assets_dir"]:
        p = config["paths"][key]
        config["paths"][key] = str((project_root / p).resolve())

    return config

# ================================================================
# MODULE 3 — LOGGING SETUP
# ================================================================

def setup_logging(config, project_root: Path, verbose=False):
    """
    Configure logging according to config + CLI overrides.
    """
    level = logging.DEBUG if verbose else getattr(logging, config["logging"]["level"])

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Optional file logging
    log_file = config["logging"].get("file")
    if log_file:
        file_path = project_root / log_file
        fh = logging.FileHandler(file_path, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(fh)

    logging.debug("Logging initialized")

# ================================================================
# MODULE 4 — TRANSFORM ENGINE (SaxonC + lxml)
# ================================================================

import subprocess
from lxml import etree


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


def run_transform(engine, saxonc_bin, xml_path, xsl_path, output_path, dry_run=False):
    """
    Run an XSLT transformation using either SaxonC or lxml.
    - engine: "saxonc" or "lxml"
    - saxonc_bin: path to SaxonC Transform binary (or None)
    - xml_path: input XML file
    - xsl_path: XSL stylesheet
    - output_path: output file path
    - dry_run: if True, do not write output
    """

    xml_path = Path(xml_path)
    xsl_path = Path(xsl_path)
    output_path = Path(output_path)

    if dry_run:
        logging.debug(f"[DRY RUN] Would transform {xml_path} using {xsl_path}")
        return

    if engine == "saxonc" and saxonc_bin:
        # ------------------------------------------------------------
        # SaxonC execution
        # ------------------------------------------------------------
        cmd = [
            str(saxonc_bin),
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

    # ------------------------------------------------------------
    # lxml fallback engine
    # ------------------------------------------------------------
    logging.debug(f"Running lxml transform: {xml_path} -> {output_path}")

    try:
        dom = etree.parse(str(xml_path), parser=_safe_xml_parser())
        xslt = etree.XSLT(etree.parse(str(xsl_path), parser=_safe_xml_parser()))
        result = xslt(dom)
    except Exception as e:
        logging.error(f"lxml transform failed: {e}")
        raise

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(str(result), encoding="utf-8")

# ================================================================
# MODULE 4.5 — DEPENDENCY CHECKER
# ================================================================

REQUIRED_XSL_FILES = [
    "article.xsl",
    "index.xsl",
    "tags.xsl",
    "rss.xsl",
    "sitemap.xsl",
    "search.xsl",
]


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


def parse_article_xml(path: Path):
    """
    Parse a single article XML file and return a dictionary of metadata.
    Expected structure:

    <article>
      <title>...</title>
      <date>YYYY-MM-DD</date>
      <description>...</description>
      <tag>...</tag>
      <tag>...</tag>
    </article>
    """
    try:
        tree = etree.parse(str(path), parser=_safe_xml_parser())
        root = tree.getroot()
    except Exception as e:
        logging.error(f"Failed to parse XML: {path} — {e}")
        return None

    def get_text(tag):
        el = root.find(tag)
        return el.text.strip() if el is not None and el.text else ""

    title = get_text("title")
    date = get_text("date")
    desc = get_text("description")

    tags = [el.text.strip() for el in root.findall("tag") if el.text]

    slug = normalize_slug(title) if title else normalize_slug(path.stem)

    try:
        dt = datetime.fromisoformat(date)
    except Exception:
        dt = datetime.now()

    return {
        "title": title,
        "date": date,
        "datetime": dt,
        "description": desc,
        "tags": tags,
        "slug": slug,
        "source_path": path,
    }


def discover_article_files(content_dir: Path):
    """
    Recursively find all .xml files in the content directory.
    """
    return sorted(content_dir.rglob("*.xml"))


def load_articles(content_dir: Path):
    """
    Load and parse all articles from the content directory.
    """
    articles = []
    for xml_file in discover_article_files(content_dir):
        meta = parse_article_xml(xml_file)
        if meta:
            articles.append(meta)

    # Sort newest first
    articles.sort(key=lambda a: a["datetime"], reverse=True)
    return articles

# ================================================================
# MODULE 7 — MODEL BUILDERS
# ================================================================

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

def build_index_models(articles, config):
    """
    Build paginated index models.
    Returns a list of dicts, each representing one index page.
    """
    per_page = config["site"]["pagination"]["per_page"]
    base_url = config["site"]["base_url"]
    pattern = config["urls"]["index"]

    pages = []
    total = len(articles)
    num_pages = (total + per_page - 1) // per_page

    for page in range(1, num_pages + 1):
        start = (page - 1) * per_page
        end = start + per_page
        subset = articles[start:end]

        model = {
            "page": page,
            "total_pages": num_pages,
            "articles": subset,
            "output_path": build_rel_path_from_pattern(pattern, lang="en", page=page),
            "url": build_url_from_pattern(base_url, pattern, lang="en", page=page),
        }
        pages.append(model)

    return pages


# ------------------------------------------------------------
# Tag Pages
# ------------------------------------------------------------

def build_tags_models(articles, config):
    """
    Build tag pages: one page per tag.
    """
    base_url = config["site"]["base_url"]
    pattern = config["urls"]["tag"]

    # Group by tag
    tag_map = {}
    for art in articles:
        for tag in art.get("tags", []):
            tag_map.setdefault(tag, []).append(art)

    models = []
    for tag, items in tag_map.items():
        model = {
            "tag": tag,
            "articles": items,
            "output_path": build_rel_path_from_pattern(pattern, lang="en", tag=tag),
            "url": build_url_from_pattern(base_url, pattern, lang="en", tag=tag),
        }
        models.append(model)

    return models


# ------------------------------------------------------------
# RSS Feed
# ------------------------------------------------------------

def build_rss_model(articles, config):
    """
    Build RSS feed model.
    """
    limit = config["site"]["pagination"]["rss_items"]
    base_url = config["site"]["base_url"]
    pattern = config["urls"]["rss"]

    model = {
        "articles": articles[:limit],
        "output_path": Path(pattern.lstrip("/")),
        "url": build_url_from_pattern(base_url, pattern),
    }
    return model


# ------------------------------------------------------------
# Sitemap
# ------------------------------------------------------------

def build_sitemap_model(articles, config):
    """
    Build sitemap model.
    """
    base_url = config["site"]["base_url"]
    pattern = config["urls"]["sitemap"]

    urls = []
    for art in articles:
        urls.append(art["url"])

    model = {
        "urls": urls,
        "output_path": Path(pattern.lstrip("/")),
        "url": build_url_from_pattern(base_url, pattern),
    }
    return model


# ------------------------------------------------------------
# Search Index (JSON)
# ------------------------------------------------------------

def build_search_model(articles, config):
    """
    Build search index model.
    """
    base_url = config["site"]["base_url"]
    pattern = config["urls"]["search"]

    items = []
    for art in articles:
        items.append({
            "title": art["title"],
            "description": art["description"],
            "url": art["url"],
            "tags": art["tags"],
        })

    model = {
        "items": items,
        "output_path": Path(pattern.lstrip("/")),
        "url": build_url_from_pattern(base_url, pattern),
    }
    return model

# ================================================================
# MODULE 8 — INCREMENTAL BUILD CACHE
# ================================================================

import hashlib
import json


def file_hash(path: Path) -> str:
    """
    Compute a SHA-256 hash of a file's contents.
    Returns a hex digest string.
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except FileNotFoundError:
        return ""
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


def update_cache(cache: dict, key: str, new_hashes: tuple):
    """
    Update the cache entry for a given page.
    """
    cache[key] = list(new_hashes)

# ================================================================
# MODULE 9 — PARALLEL EXECUTOR
# ================================================================

from concurrent.futures import ThreadPoolExecutor, as_completed


def run_parallel_tasks(tasks, max_workers="auto"):
    """
    Run a list of callables in parallel.
    Each task is a function with no arguments.
    Returns a list of results.
    """

    if max_workers == "auto":
        import os
        max_workers = max(4, os.cpu_count() or 4)

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fn): fn for fn in tasks}

        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                logging.error(f"Task failed: {e}")
                raise

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
# Section Builders — Articles
# ------------------------------------------------------------

def build_articles_section(articles, config, saxonc_bin, cache, dry_run):
    """
    Build all article pages.
    """
    tasks = []
    xsl_path = Path(config["paths"]["xsl_dir"]) / "pages" / "article.xsl"
    output_dir = Path(config["paths"]["output_dir"])
    engine = config["engines"]["articles"]
    force = config["build"]["force_full_build"]

    for art in articles:
        xml_path = art["source_path"]
        xml_hash = file_hash(xml_path)
        xsl_hash = file_hash(xsl_path)
        key = f"article:{art['slug']}"

        output_path = output_dir / f"en/articles/{art['slug']}/index.html"
        art["url"] = build_url_from_pattern(
            config["site"]["base_url"],
            config["urls"]["article"],
            lang="en",
            slug=art["slug"],
        )

        if not should_rebuild(key, cache, (xml_hash, xsl_hash), force):
            logging.debug(f"Skipping unchanged article: {art['slug']}")
            continue

        def make_task(xml_path=xml_path, xsl_path=xsl_path, output_path=output_path):
            return lambda: run_transform(
                engine,
                saxonc_bin,
                xml_path,
                xsl_path,
                output_path,
                dry_run=dry_run,
            )

        tasks.append(make_task())
        update_cache(cache, key, (xml_hash, xsl_hash))

    return tasks


# ------------------------------------------------------------
# Section Builders — Index Pages
# ------------------------------------------------------------

def build_index_section(articles, config, saxonc_bin, cache, dry_run):
    """
    Build paginated index pages.
    """
    tasks = []
    xsl_path = Path(config["paths"]["xsl_dir"]) / "pages" / "index.xsl"
    output_dir = Path(config["paths"]["output_dir"])
    engine = config["engines"]["index"]
    force = config["build"]["force_full_build"]

    models = build_index_models(articles, config)

    for model in models:
        xml_temp = output_dir / f"temp/index-{model['page']}.xml"
        xml_temp.parent.mkdir(parents=True, exist_ok=True)

        # Write model XML
        xml_content = "<index>" + "".join(
            f"<article><title>{a['title']}</title><url>{a['url']}</url></article>"
            for a in model["articles"]
        ) + "</index>"

        if not dry_run:
            xml_temp.write_text(xml_content, encoding="utf-8")

        xml_hash = file_hash(xml_temp)
        xsl_hash = file_hash(xsl_path)
        key = f"index:{model['page']}"

        output_path = output_dir / model["output_path"]

        if not should_rebuild(key, cache, (xml_hash, xsl_hash), force):
            logging.debug(f"Skipping unchanged index page {model['page']}")
            continue

        def make_task(xml_temp=xml_temp, xsl_path=xsl_path, output_path=output_path):
            return lambda: run_transform(
                engine,
                saxonc_bin,
                xml_temp,
                xsl_path,
                output_path,
                dry_run=dry_run,
            )

        tasks.append(make_task())
        update_cache(cache, key, (xml_hash, xsl_hash))

    return tasks

# ------------------------------------------------------------
# Section Builders — Tags
# ------------------------------------------------------------

def build_tags_section(articles, config, saxonc_bin, cache, dry_run):
    """
    Build tag pages.
    """
    tasks = []
    xsl_path = Path(config["paths"]["xsl_dir"]) / "pages" / "tags.xsl"
    output_dir = Path(config["paths"]["output_dir"])
    engine = config["engines"]["tags"]
    force = config["build"]["force_full_build"]

    models = build_tags_models(articles, config)

    for model in models:
        tag = model["tag"]
        xml_temp = output_dir / f"temp/tag-{tag}.xml"
        xml_temp.parent.mkdir(parents=True, exist_ok=True)

        # Write model XML
        xml_content = "<tag>" + "".join(
            f"<article><title>{a['title']}</title><url>{a['url']}</url></article>"
            for a in model["articles"]
        ) + "</tag>"

        if not dry_run:
            xml_temp.write_text(xml_content, encoding="utf-8")

        xml_hash = file_hash(xml_temp)
        xsl_hash = file_hash(xsl_path)
        key = f"tag:{tag}"

        output_path = output_dir / model["output_path"]

        if not should_rebuild(key, cache, (xml_hash, xsl_hash), force):
            logging.debug(f"Skipping unchanged tag page: {tag}")
            continue

        def make_task(xml_temp=xml_temp, xsl_path=xsl_path, output_path=output_path):
            return lambda: run_transform(
                engine,
                saxonc_bin,
                xml_temp,
                xsl_path,
                output_path,
                dry_run=dry_run,
            )

        tasks.append(make_task())
        update_cache(cache, key, (xml_hash, xsl_hash))

    return tasks


# ------------------------------------------------------------
# Section Builders — RSS
# ------------------------------------------------------------

def build_rss_section(articles, config, saxonc_bin, cache, dry_run):
    """
    Build RSS feed.
    """
    tasks = []
    xsl_path = Path(config["paths"]["xsl_dir"]) / "pages" / "rss.xsl"
    output_dir = Path(config["paths"]["output_dir"])
    engine = config["engines"]["rss"]
    force = config["build"]["force_full_build"]

    model = build_rss_model(articles, config)

    xml_temp = output_dir / "temp/rss.xml"
    xml_temp.parent.mkdir(parents=True, exist_ok=True)

    # Write model XML
    xml_content = "<rss>" + "".join(
        f"<item><title>{a['title']}</title><url>{a['url']}</url></item>"
        for a in model["articles"]
    ) + "</rss>"

    if not dry_run:
        xml_temp.write_text(xml_content, encoding="utf-8")

    xml_hash = file_hash(xml_temp)
    xsl_hash = file_hash(xsl_path)
    key = "rss"

    output_path = output_dir / model["output_path"]

    if not should_rebuild(key, cache, (xml_hash, xsl_hash), force):
        logging.debug("Skipping unchanged RSS feed")
        return tasks

    def make_task(xml_temp=xml_temp, xsl_path=xsl_path, output_path=output_path):
        return lambda: run_transform(
            engine,
            saxonc_bin,
            xml_temp,
            xsl_path,
            output_path,
            dry_run=dry_run,
        )

    tasks.append(make_task())
    update_cache(cache, key, (xml_hash, xsl_hash))

    return tasks


# ------------------------------------------------------------
# Section Builders — Sitemap
# ------------------------------------------------------------

def build_sitemap_section(articles, config, saxonc_bin, cache, dry_run):
    """
    Build sitemap.xml.
    """
    tasks = []
    xsl_path = Path(config["paths"]["xsl_dir"]) / "pages" / "sitemap.xsl"
    output_dir = Path(config["paths"]["output_dir"])
    engine = config["engines"]["sitemap"]
    force = config["build"]["force_full_build"]

    model = build_sitemap_model(articles, config)

    xml_temp = output_dir / "temp/sitemap.xml"
    xml_temp.parent.mkdir(parents=True, exist_ok=True)

    xml_content = "<sitemap>" + "".join(
        f"<url>{u}</url>" for u in model["urls"]
    ) + "</sitemap>"

    if not dry_run:
        xml_temp.write_text(xml_content, encoding="utf-8")

    xml_hash = file_hash(xml_temp)
    xsl_hash = file_hash(xsl_path)
    key = "sitemap"

    output_path = output_dir / model["output_path"]

    if not should_rebuild(key, cache, (xml_hash, xsl_hash), force):
        logging.debug("Skipping unchanged sitemap")
        return tasks

    def make_task(xml_temp=xml_temp, xsl_path=xsl_path, output_path=output_path):
        return lambda: run_transform(
            engine,
            saxonc_bin,
            xml_temp,
            xsl_path,
            output_path,
            dry_run=dry_run,
        )

    tasks.append(make_task())
    update_cache(cache, key, (xml_hash, xsl_hash))

    return tasks


# ------------------------------------------------------------
# Section Builders — Search Index
# ------------------------------------------------------------

def build_search_section(articles, config, cache, dry_run):
    """
    Build search.json.
    """
    tasks = []
    output_dir = Path(config["paths"]["output_dir"])
    force = config["build"]["force_full_build"]

    model = build_search_model(articles, config)

    output_path = output_dir / model["output_path"]

    # JSON output — no XSLT needed
    json_hash = hashlib.sha256(json.dumps(model["items"]).encode("utf-8")).hexdigest()
    key = "search"

    if not should_rebuild(key, cache, (json_hash, "json"), force):
        logging.debug("Skipping unchanged search index")
        return tasks

    def make_task(output_path=output_path, items=model["items"]):
        return lambda: write_json(output_path, items, dry_run=dry_run)

    tasks.append(make_task())
    update_cache(cache, key, (json_hash, "json"))

    return tasks

# ------------------------------------------------------------
# Full Build Pipeline
# ------------------------------------------------------------

def run_build(cli: CliOptions, config, project_root: Path):
    """
    Orchestrate the entire build process.
    """
    logging.info("Starting build...")

    content_dir = Path(config["paths"]["content_dir"])
    output_dir = Path(config["paths"]["output_dir"])
    # Reduce user-controlled config to a bare filename to prevent path traversal.
    cache_file_name = Path(config["build"]["cache_file"]).name
    cache_path = project_root / cache_file_name

    # Load cache
    cache = load_cache(cache_path)

    # Configure SaxonC (optional)
    saxonc_bin = configure_saxonc(config)

    # Load articles
    articles = load_articles(content_dir)

    # Build tasks
    tasks = []

    if not cli.only_sections or "articles" in cli.only_sections:
        tasks += build_articles_section(articles, config, saxonc_bin, cache, cli.dry_run)

    if not cli.only_sections or "index" in cli.only_sections:
        tasks += build_index_section(articles, config, saxonc_bin, cache, cli.dry_run)

    if not cli.only_sections or "tags" in cli.only_sections:
        tasks += build_tags_section(articles, config, saxonc_bin, cache, cli.dry_run)

    if not cli.only_sections or "rss" in cli.only_sections:
        tasks += build_rss_section(articles, config, saxonc_bin, cache, cli.dry_run)

    if not cli.only_sections or "sitemap" in cli.only_sections:
        tasks += build_sitemap_section(articles, config, saxonc_bin, cache, cli.dry_run)

    if not cli.only_sections or "search" in cli.only_sections:
        tasks += build_search_section(articles, config, cache, cli.dry_run)

    # Run tasks in parallel
    if tasks:
        logging.info(f"Running {len(tasks)} tasks in parallel...")
        run_parallel_tasks(tasks, config["build"]["parallelism"])
    else:
        logging.info("Nothing to build — all pages up to date.")

    # Save cache
    if not cli.dry_run:
        save_cache(cache_path, cache)

    logging.info("Build complete.")


# ------------------------------------------------------------
# CLI Entrypoint
# ------------------------------------------------------------

if __name__ == "__main__":
    args = parse_cli_args()
    cli = CliOptions(args)

    project_root = Path(__file__).parent.resolve()

    config = load_or_create_config(cli.config_path)
    config = apply_cli_overrides(config, cli, project_root)

    setup_logging(config, project_root, verbose=cli.verbose)

    check_dependencies(config, project_root)

    run_build(cli, config, project_root)

