"""Explicit translation groups and reciprocal-link consistency."""
import json
import re
import sqlite3
from html import escape

from .locale_data import LANGUAGES, REGIONS, SCRIPTS


def hreflang(locale: str) -> str:
    match = re.fullmatch(r"([A-Za-z]{2})(?:[-_]([A-Za-z]{4}))?(?:[-_]([A-Za-z]{2}))?", locale)
    if match is None:
        raise ValueError(f"Unsupported translation locale: {locale}")
    language, script, region = match.groups(default="")
    language, script, region = language.lower(), script.title(), region.upper()
    if language not in LANGUAGES or (script and script not in SCRIPTS) or (region and region not in REGIONS):
        raise ValueError(f"Unsupported translation locale: {locale}")
    return "-".join(part for part in (language, script, region) if part)


def _cached_metadata(fingerprint) -> dict:
    try:
        value = json.loads(fingerprint[-2])
    except (TypeError, ValueError, IndexError, KeyError):
        return {}
    return value if isinstance(value, dict) else {}


class TranslationStore:
    def __init__(self):
        self._database = sqlite3.connect("")
        self._database.execute("PRAGMA cache_size = -512")
        self._database.execute(
            "CREATE TABLE pages (id TEXT PRIMARY KEY, group_id TEXT, locale TEXT, url TEXT, selected INTEGER, eligible INTEGER)"
        )
        self._database.execute("CREATE UNIQUE INDEX translation_locale ON pages(group_id, locale) WHERE eligible = 1")

    def add(self, article, selected: bool) -> None:
        if not article.translation:
            return
        locale = hreflang(article.lang)
        eligible = article.indexable and article.url.startswith(("https://", "http://"))
        try:
            self._database.execute("INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?)", (
                f"article:{article.lang}:{article.slug}", article.translation, locale, article.url, selected, eligible,
            ))
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Duplicate translation identifier/locale: {article.translation}/{locale}") from error

    def markup(self, group: str) -> str:
        rows = self._database.execute("SELECT locale, url FROM pages WHERE group_id = ? AND eligible = 1 ORDER BY locale", (group,))
        return "".join(f'<link rel="alternate" hreflang="{locale}" href="{escape(url, quote=True)}"/>' for locale, url in rows)

    def validate_filters(self, cache: dict, selected) -> None:
        self._database.execute("CREATE TABLE previous (id TEXT PRIMARY KEY, group_id TEXT, markup TEXT, selected INTEGER)")
        self._load_previous(cache, selected)
        rows = self._database.execute(
            "WITH affected AS (SELECT group_id FROM pages WHERE selected = 1 UNION SELECT group_id FROM previous WHERE selected = 1) "
            "SELECT id FROM pages WHERE selected = 0 AND group_id IN affected "
            "UNION SELECT id FROM previous WHERE selected = 0 AND group_id IN affected"
        )
        for (key,) in rows:
            if self._current_markup(key) != self._previous_markup(key):
                raise ValueError("A full build is required to update reciprocal translation links")

    def _load_previous(self, cache: dict, selected) -> None:
        for key, fingerprint in cache.items():
            if not key.startswith("article:"):
                continue
            metadata = _cached_metadata(fingerprint)
            group = metadata.get("articulous-translation", "")
            if group:
                self._database.execute("INSERT INTO previous VALUES (?, ?, ?, ?)", (
                    key, group, metadata.get("articulous-alternates", ""), selected(key),
                ))

    def _current_markup(self, key: str) -> str:
        row = self._database.execute("SELECT group_id FROM pages WHERE id = ? AND eligible = 1", (key,)).fetchone()
        return self.markup(row[0]) if row else ""

    def _previous_markup(self, key: str) -> str:
        row = self._database.execute("SELECT markup FROM previous WHERE id = ?", (key,)).fetchone()
        return row[0] if row else ""

    def close(self) -> None:
        self._database.close()
