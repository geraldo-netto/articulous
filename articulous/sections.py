"""Section metadata and URL-pattern policy."""
from __future__ import annotations

from dataclasses import dataclass
from string import Formatter
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class SectionSpec:
    name: str
    url_key: str
    xsl_file: str
    output_kind: str
    scope: str
    placeholders: frozenset[str]


SECTION_SPECS: tuple[SectionSpec, ...] = (
    SectionSpec(
        "articles", "article", "article.xsl", "directory", "per-lang",
        frozenset({"lang", "slug"}),
    ),
    SectionSpec(
        "index", "index", "index.xsl", "directory", "per-lang",
        frozenset({"lang", "page"}),
    ),
    SectionSpec(
        "tags", "tag", "tags.xsl", "directory", "per-lang",
        frozenset({"lang", "tag"}),
    ),
    SectionSpec("rss", "rss", "rss.xsl", "file", "cross-lang", frozenset()),
    SectionSpec("sitemap", "sitemap", "sitemap.xsl", "file", "cross-lang", frozenset()),
    SectionSpec("search", "search", "search.xsl", "file", "cross-lang", frozenset()),
)

SECTION_BY_NAME = {spec.name: spec for spec in SECTION_SPECS}
SECTION_NAMES = tuple(spec.name for spec in SECTION_SPECS)
PER_LANG_SECTIONS = tuple(spec.name for spec in SECTION_SPECS if spec.scope == "per-lang")
CROSS_LANG_SECTIONS = tuple(
    spec.name for spec in SECTION_SPECS if spec.scope == "cross-lang"
)
SECTION_XSL = {spec.name: spec.xsl_file for spec in SECTION_SPECS}
REQUIRED_XSL_FILES = sorted({spec.xsl_file for spec in SECTION_SPECS})
SECTION_HELP = ",".join(SECTION_NAMES)


def url_key_for_section(section: str) -> str:
    return SECTION_BY_NAME[section].url_key


def _pattern_fields(pattern: str) -> set[str]:
    fields = set()
    for _, field, _, _ in Formatter().parse(pattern):
        if field:
            fields.add(field.split(".", 1)[0].split("[", 1)[0])
    return fields


def _validate_placeholders(spec: SectionSpec, pattern: str) -> None:
    fields = _pattern_fields(pattern)
    unknown = fields - spec.placeholders
    missing = spec.placeholders - fields
    if unknown or missing:
        raise ValueError(
            f"config urls.{spec.url_key} placeholders must be "
            f"{sorted(spec.placeholders)}; got {sorted(fields)}"
        )


def _validate_url_syntax(pattern: str) -> None:
    if any(char in pattern for char in "?#%\\") or any(ord(char) < 32 or ord(char) == 127 for char in pattern):
        raise ValueError("URL patterns cannot contain queries, fragments, escapes, or control characters")
    parsed = urlsplit(pattern)
    if parsed.scheme or parsed.netloc:
        raise ValueError("URL patterns must be local paths, without a scheme or host")


def validate_url_pattern(section: str, pattern: str) -> None:
    _validate_url_syntax(pattern)
    spec = SECTION_BY_NAME[section]
    _validate_placeholders(spec, pattern)
    stripped = pattern.format(
        lang="en", slug="slug", page=1, tag="tag",
    ).lstrip("/")
    suffix = Path(stripped).suffix
    if spec.output_kind == "directory" and suffix:
        raise ValueError(
            f"config urls.{spec.url_key} must be a directory-style pattern"
        )
    if spec.output_kind == "file" and not suffix:
        raise ValueError(
            f"config urls.{spec.url_key} must be a file-style pattern"
        )


def output_path_from_pattern(section: str, pattern: str, **kwargs) -> Path:
    rel = pattern.format(**kwargs).strip("/")
    if SECTION_BY_NAME[section].output_kind == "directory":
        return Path(rel) / "index.html"
    return Path(rel)
