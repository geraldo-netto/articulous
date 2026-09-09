"""
Article XML parsing, discovery, and the :class:`Article` domain type.

``Article`` is a frozen dataclass shared by section builders. The pipeline
supplies a URL builder during parsing; direct callers may omit it and
receive articles with an empty URL.
"""
from __future__ import annotations

import logging
import hashlib
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Callable, Iterable, Optional

from lxml import etree  # type: ignore[attr-defined]

from .engines import safe_xml_parser
from .filesystem import open_regular_file


@dataclass(frozen=True)
class PublicationPolicy:
    page: bool
    listing: bool
    rss: bool
    sitemap: bool
    search: bool


_PUBLICATION_POLICIES = {
    "published": PublicationPolicy(True, True, True, True, True),
    "unlisted": PublicationPolicy(True, False, False, False, False),
    "draft": PublicationPolicy(False, False, False, False, False),
    "private": PublicationPolicy(False, False, False, False, False),
    "scheduled": PublicationPolicy(False, False, False, False, False),
}
_SEO_FIELDS = frozenset({"indexing", "slug"})
_SINGLETON_FIELDS = frozenset({"title", "date", "description", "lang", "status", "publish-at"}) | _SEO_FIELDS


@dataclass(frozen=True)
class PublicationState:
    name: str = "published"
    publish_at: Optional[datetime] = None

    @property
    def policy(self) -> PublicationPolicy:
        if self.name == "scheduled" and self._published_now():
            return _PUBLICATION_POLICIES["published"]
        return _PUBLICATION_POLICIES[self.name]

    def _published_now(self) -> bool:
        if self.publish_at is None:
            return False
        now = datetime.now(tz=self.publish_at.tzinfo)
        return self.publish_at <= now


@dataclass(frozen=True)
class ArticleSnapshot:
    path: Path
    offset: int
    size: int
    fingerprint: str

    def read_bytes(self) -> bytes:
        with open_regular_file(self.path) as source:
            source.seek(self.offset)
            content = source.read(self.size)
        if hashlib.sha256(content).hexdigest() != self.fingerprint:
            raise ValueError(f"Article snapshot changed or truncated: {self.path}")
        return content


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
    publication: PublicationState | str = PublicationState()
    source_xml: bytes | ArticleSnapshot | None = field(default=None, repr=False)
    source_base_uri: str | None = None
    indexing: str = "index"

    @property
    def policy(self) -> PublicationPolicy:
        policy = self.publication_state.policy
        if self.indexing == "noindex":
            return replace(policy, sitemap=False)
        return policy

    @property
    def indexable(self) -> bool:
        return self.policy.page and self.indexing == "index"

    @property
    def publication_state(self) -> PublicationState:
        if isinstance(self.publication, PublicationState):
            return self.publication
        return PublicationState(self.publication)


@dataclass
class ArticleStats:
    scanned: int = 0
    parsed: int = 0
    skipped: int = 0


class _ScanProgress:
    def __init__(self, stats: ArticleStats):
        self._stats = stats
        self._reported_at = monotonic()

    def report(self) -> None:
        now = monotonic()
        if now - self._reported_at < 5:
            return
        logging.info(
            "Article scan progress: %d scanned, %d parsed, %d skipped",
            self._stats.scanned, self._stats.parsed, self._stats.skipped,
        )
        self._reported_at = now


def normalize_slug(text: str) -> str:
    """Convert arbitrary text into a URL-safe slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _track_singleton_field(tag, seen: set) -> None:
    if tag not in _SINGLETON_FIELDS:
        return
    if tag in seen:
        raise ValueError(f"duplicate singleton field <{tag}>")
    seen.add(tag)


def _field_text(child) -> str:
    if child.tag in _SEO_FIELDS and len(child):
        raise ValueError(f"<{child.tag}> must contain text only")
    return (child.text or "").strip()


def _validated_indexing(raw: str) -> str:
    if raw not in {"index", "noindex"}:
        raise ValueError("<indexing> must be index or noindex")
    return raw


def _validated_slug(raw: str | None) -> str | None:
    if raw is None:
        return None
    if len(raw) > 128 or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", raw) is None:
        raise ValueError("<slug> must contain 1–128 lowercase ASCII letters/digits separated by single hyphens")
    return raw


def _read_article_fields(root) -> dict:
    """
    Single pass over the article's child elements. Replaces four
    separate ``root.find(...)`` XPath traversals with one walk.
    """
    fields = {"title": "", "date": "", "description": "", "lang": "", "indexing": "index", "slug": None}
    tags: list = []
    publication = "published"
    publish_at = ""
    seen: set = set()
    for child in root:
        tag = child.tag
        _track_singleton_field(tag, seen)
        text = _field_text(child)
        if tag in fields:
            fields[tag] = text
        elif tag == "tag" and text:
            tags.append(text)
        elif tag == "status" and text:
            publication = text
        elif tag == "publish-at" and text:
            publish_at = text
    return {
        **fields,
        "indexing": _validated_indexing(fields["indexing"]),
        "slug": _validated_slug(fields["slug"]),
        "tags": tags,
        "publication": publication,
        "publish_at": publish_at,
    }


def _parse_publish_at(raw: str, path: Path) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return _as_utc(datetime.fromisoformat(raw))
    except (ValueError, OverflowError):
        logging.warning(
            f"Article {path} has invalid publish-at {raw!r} — treating as scheduled"
        )
        return datetime.max.replace(tzinfo=timezone.utc)


def _validated_publication(
    raw: str, publish_at: str, path: Path,
) -> Optional[PublicationState]:
    value = (raw or "published").strip().lower()
    if value in _PUBLICATION_POLICIES:
        if value == "scheduled" and not publish_at:
            logging.warning(
                f"Article {path} is scheduled without publish-at — skipping"
            )
        return PublicationState(value, _parse_publish_at(publish_at, path))
    logging.warning(
        f"Article {path} has unknown status {raw!r} — skipping"
    )
    return None


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
        with open_regular_file(path) as source:
            content = source.read()
        base_uri = path.resolve().as_uri()
        root = etree.fromstring(content, parser=safe_xml_parser(), base_url=base_uri)
    except (etree.XMLSyntaxError, OSError, ValueError):
        logging.exception(f"Failed to parse XML: {path}")
        return None

    if root.tag != "article":
        logging.warning(
            f"Article {path} has root tag {root.tag!r}, expected 'article' — skipping"
        )
        return None

    try:
        fields = _read_article_fields(root)
    except ValueError as error:
        logging.warning(f"Article {path} has {error} — skipping")
        return None
    lang = _validated_lang(fields["lang"], default_lang, allowed_langs, path)

    try:
        dt = _as_utc(datetime.fromisoformat(fields["date"]))
    except (ValueError, TypeError, OverflowError):
        logging.warning(
            f"Article {path} has missing/invalid date {fields['date']!r} — skipping"
        )
        return None

    title = fields["title"]
    slug = fields["slug"] or normalize_slug(title or path.stem)
    if not slug:
        logging.warning(
            f"Article {path} produced an empty slug from title={title!r} — skipping"
        )
        return None

    url = url_builder(lang, slug) if url_builder is not None else ""
    publication = _validated_publication(
        fields["publication"], fields["publish_at"], path,
    )
    if publication is None:
        return None

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
        source_xml=content,
        source_base_uri=base_uri,
        indexing=fields["indexing"],
    )


def _directory_entries(directory: bytes):
    with os.scandir(os.fsdecode(directory)) as entries:
        for entry in entries:
            directory_entry = entry.is_dir(follow_symlinks=False)
            if directory_entry or entry.name.endswith(".xml"):
                yield os.fsencode(entry.path), int(directory_entry)


def _spool_article_paths(database, content_dir: Path) -> None:
    database.execute("CREATE TABLE paths (path BLOB PRIMARY KEY, directory INTEGER)")
    database.execute("CREATE INDEX directories ON paths(path) WHERE directory = 1")
    database.execute("INSERT INTO paths VALUES (?, 1)", (os.fsencode(content_dir),))
    while row := database.execute("SELECT path FROM paths WHERE directory = 1 LIMIT 1").fetchone():
        database.execute("DELETE FROM paths WHERE path = ?", row)
        database.executemany("INSERT INTO paths VALUES (?, ?)", _directory_entries(row[0]))


def _discover_article_files(content_dir: Path):
    """Sort discovered paths on disk with a bounded SQLite page cache."""
    with closing(sqlite3.connect("")) as database:
        database.execute("PRAGMA temp_store = FILE")
        database.execute("PRAGMA cache_size = -512")
        _spool_article_paths(database, content_dir)
        for (path,) in database.execute("SELECT path FROM paths ORDER BY path"):
            yield Path(os.fsdecode(path))


def iter_articles(
    content_dir: Path,
    *,
    default_lang: str = "en",
    url_builder: Optional[Callable[[str, str], str]] = None,
    allowed_langs: Optional[Iterable[str]] = None,
    stats: Optional[ArticleStats] = None,
):
    """
    Yield :class:`Article` instances one at a time in sorted path order.

    Discovery uses a temporary disk index; parsing retains one article
    at a time. The lxml DOM is released between iterations and the
    previous ``Article`` is only retained if the caller holds onto it.

    The pipeline consumes this generator once per build, applies filters
    to article-page selection, and builds complete shared projections.
    """
    allowed = frozenset(allowed_langs) if allowed_langs is not None else None
    stats = stats or ArticleStats()
    progress = _ScanProgress(stats)
    for path in _discover_article_files(content_dir):
        stats.scanned += 1
        art = parse_article_xml(
            path,
            default_lang=default_lang,
            url_builder=url_builder,
            allowed_langs=allowed,
        )
        if art is None:
            stats.skipped += 1
        else:
            stats.parsed += 1
        progress.report()
        if art is not None:
            yield art
