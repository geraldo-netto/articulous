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

from lxml import etree  # type: ignore[attr-defined]

from .engines import safe_xml_parser


@dataclass(frozen=True)
class PublicationPolicy:
    page: bool
    listing: bool
    rss: bool
    sitemap: bool
    search: bool


PUBLICATION_POLICIES = {
    "published": PublicationPolicy(True, True, True, True, True),
    "unlisted": PublicationPolicy(True, False, False, False, False),
    "draft": PublicationPolicy(False, False, False, False, False),
    "private": PublicationPolicy(False, False, False, False, False),
}


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
    publication: str = "published"

    @property
    def policy(self) -> PublicationPolicy:
        return PUBLICATION_POLICIES[self.publication]


@dataclass
class ArticleStats:
    scanned: int = 0
    parsed: int = 0
    skipped: int = 0


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
    publication = "published"
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
        elif tag == "status" and text:
            publication = text
    return {
        "title": title,
        "date": date,
        "description": description,
        "lang": lang,
        "tags": tags,
        "publication": publication,
    }


def _validated_publication(raw: str, path: Path) -> str:
    value = (raw or "published").strip().lower()
    if value in PUBLICATION_POLICIES:
        return value
    logging.warning(
        f"Article {path} has unknown status {raw!r} — using 'published'"
    )
    return "published"


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
    except (etree.XMLSyntaxError, OSError):
        logging.exception(f"Failed to parse XML: {path}")
        return None

    if root.tag != "article":
        logging.warning(
            f"Article {path} has root tag {root.tag!r}, expected 'article' — skipping"
        )
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
    publication = _validated_publication(fields["publication"], path)

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
        publication=publication,
    )


def _discover_article_files(content_dir: Path):
    """Recursively find all .xml files in ``content_dir``."""
    return sorted(content_dir.rglob("*.xml"))


def iter_articles(
    content_dir: Path,
    *,
    default_lang: str = "en",
    url_builder: Optional[Callable[[str, str], str]] = None,
    allowed_langs: Optional[Iterable[str]] = None,
    stats: Optional[ArticleStats] = None,
):
    """
    Yield :class:`Article` instances one at a time, in directory-walk
    order (no sort applied).

    Memory footprint is bounded to a single article — the lxml DOM is
    released between iterations and the previous ``Article`` is only
    retained if the caller holds onto it.

    The pipeline consumes this generator once per build and partitions
    the filtered articles by language while building cross-language
    projections.
    """
    allowed = frozenset(allowed_langs) if allowed_langs is not None else None
    for path in _discover_article_files(content_dir):
        if stats is not None:
            stats.scanned += 1
        art = parse_article_xml(
            path,
            default_lang=default_lang,
            url_builder=url_builder,
            allowed_langs=allowed,
        )
        if art is not None:
            if stats is not None:
                stats.parsed += 1
            yield art
        elif stats is not None:
            stats.skipped += 1
