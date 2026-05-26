"""
Article XML parsing and discovery.
"""
import logging
import re
from datetime import datetime
from pathlib import Path

from lxml import etree

from .engines import safe_xml_parser


def normalize_slug(text: str) -> str:
    """Convert arbitrary text into a URL-safe slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def parse_article_xml(path: Path, default_lang: str = "en"):
    """
    Parse a single article XML file and return a dictionary of
    metadata. Returns ``None`` if the file cannot be parsed or has
    no usable date.

    Expected structure::

        <article>
          <title>...</title>
          <date>YYYY-MM-DD</date>
          <description>...</description>
          <lang>en</lang>          <!-- optional, defaults to default_lang -->
          <tag>...</tag>
        </article>
    """
    try:
        tree = etree.parse(str(path), parser=safe_xml_parser())
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
    """Recursively find all .xml files in ``content_dir``."""
    return sorted(content_dir.rglob("*.xml"))


def load_articles(content_dir: Path, default_lang: str = "en"):
    """Load and parse every article under ``content_dir`` (newest first)."""
    articles = []
    for xml_file in discover_article_files(content_dir):
        meta = parse_article_xml(xml_file, default_lang=default_lang)
        if meta:
            articles.append(meta)
    articles.sort(key=lambda a: a["datetime"], reverse=True)
    return articles
