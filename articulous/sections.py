"""Section metadata and URL-pattern policy."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SectionSpec:
    name: str
    url_key: str
    xsl_file: str
    output_kind: str
    scope: str


SECTION_SPECS: tuple[SectionSpec, ...] = (
    SectionSpec("articles", "article", "article.xsl", "directory", "per-lang"),
    SectionSpec("index", "index", "index.xsl", "directory", "per-lang"),
    SectionSpec("tags", "tag", "tags.xsl", "directory", "per-lang"),
    SectionSpec("rss", "rss", "rss.xsl", "file", "cross-lang"),
    SectionSpec("sitemap", "sitemap", "sitemap.xsl", "file", "cross-lang"),
    SectionSpec("search", "search", "search.xsl", "file", "cross-lang"),
)

SECTION_BY_NAME = {spec.name: spec for spec in SECTION_SPECS}
SECTION_NAMES = tuple(spec.name for spec in SECTION_SPECS)
PER_LANG_SECTIONS = tuple(spec.name for spec in SECTION_SPECS if spec.scope == "per-lang")
CROSS_LANG_SECTIONS = tuple(
    spec.name for spec in SECTION_SPECS if spec.scope == "cross-lang"
)
SECTION_XSL = {spec.name: spec.xsl_file for spec in SECTION_SPECS}
REQUIRED_XSL_FILES = sorted({spec.xsl_file for spec in SECTION_SPECS})


def url_key_for_section(section: str) -> str:
    return SECTION_BY_NAME[section].url_key


def validate_url_pattern(section: str, pattern: str) -> None:
    spec = SECTION_BY_NAME[section]
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
