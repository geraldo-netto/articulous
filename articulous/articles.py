"""
Article XML parsing, discovery, and the :class:`Article` domain type.

``Article`` is a frozen dataclass: every consumer downstream sees the
same field set on every article, attribute-typed, with the URL already
attached. The previous mutable-dict representation made URL attachment
a side effect of the articles section builder; the dataclass closes
that loophole.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from lxml import etree

from .engines import safe_xml_parser


@dataclass(frozen=True)
class Article:
    """
    Parsed article. Immutable: once produced by :func:`parse_article_xml`,
    every field — including the public URL — is settled.
    """
    title: str
    slug: str
    lang: str
    date: str
    datetime: datetime
    description: str
    tags: tuple
    source_path: Path
    url: str


def normalize_slug(text: str) -> str:
    """Convert arbitrary text into a URL-safe slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def _read_article_fields(root) -> dict:
    """
    Single pass over the article's child elements. Replaces four
    separate ``root.find(...)`` XPath traversals with one walk.
    """
    title = ""
    date = ""
    description = ""
    lang = ""
    tags: list = []
    for child in root:
        tag = child.tag
        text = (child.text or "").strip()
        if tag == "title":
            title = text
        elif tag == "date":
            date = text
        elif tag == "description":
            description = text
        elif tag == "lang":
            lang = text
        elif tag == "tag" and text:
            tags.append(text)
    return {
        "title": title,
        "date": date,
        "description": description,
        "lang": lang,
        "tags": tags,
    }


def _validated_lang(
    raw_lang: str,
    default_lang: str,
    allowed_langs: Optional[frozenset],
    path: Path,
) -> str:
    """
    Apply the lang fallback and validation rules.

    Empty / missing ``<lang>`` falls back to ``default_lang``. If a
    whitelist is provided and the parsed lang isn't in it, we log and
    coerce back to the default rather than letting the value flow into
    URLs and filesystem paths unchecked (REL-11).
    """
    lang = raw_lang or default_lang
    if allowed_langs is not None and lang not in allowed_langs:
        logging.warning(
            f"Article {path} has lang {raw_lang!r} outside the configured "
            f"set {sorted(allowed_langs)} — falling back to {default_lang!r}"
        )
        lang = default_lang
    return lang


def parse_article_xml(
    path: Path,
    *,
    default_lang: str = "en",
    url_builder: Optional[Callable[[str, str], str]] = None,
    allowed_langs: Optional[frozenset] = None,
) -> Optional[Article]:
    """
    Parse a single article XML file. Returns the :class:`Article` or
    ``None`` when the file cannot be parsed, has no usable date, or
    cannot produce a slug.

    ``url_builder`` is a ``(lang, slug) -> url`` callable. When omitted
    (e.g. from tests that don't care about URLs), ``url`` is set to the
    empty string.

    Expected XML structure::

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

    fields = _read_article_fields(root)
    lang = _validated_lang(fields["lang"], default_lang, allowed_langs, path)

    try:
        dt = datetime.fromisoformat(fields["date"])
    except (ValueError, TypeError):
        logging.warning(
            f"Article {path} has missing/invalid date {fields['date']!r} — skipping"
        )
        return None

    title = fields["title"]
    slug = normalize_slug(title) if title else normalize_slug(path.stem)
    if not slug:
        logging.warning(
            f"Article {path} produced an empty slug from title={title!r} — skipping"
        )
        return None

    url = url_builder(lang, slug) if url_builder is not None else ""

    return Article(
        title=title,
        slug=slug,
        lang=lang,
        date=fields["date"],
        datetime=dt,
        description=fields["description"],
        tags=tuple(fields["tags"]),
        source_path=path,
        url=url,
    )


def _discover_article_files(content_dir: Path):
    """Recursively find all .xml files in ``content_dir``."""
    return sorted(content_dir.rglob("*.xml"))


def load_articles(
    content_dir: Path,
    *,
    default_lang: str = "en",
    url_builder: Optional[Callable[[str, str], str]] = None,
    allowed_langs: Optional[Iterable[str]] = None,
) -> list:
    """
    Load and parse every article under ``content_dir`` (newest first).

    The URL is computed once per article during parsing — no separate
    "attach URLs" pass is needed. Articles whose ``<lang>`` is not in
    ``allowed_langs`` fall back to ``default_lang`` with a warning.
    """
    allowed = frozenset(allowed_langs) if allowed_langs is not None else None
    articles: list = []
    for xml_file in _discover_article_files(content_dir):
        article = parse_article_xml(
            xml_file,
            default_lang=default_lang,
            url_builder=url_builder,
            allowed_langs=allowed,
        )
        if article is not None:
            articles.append(article)
    articles.sort(key=lambda a: a.datetime, reverse=True)
    return articles
