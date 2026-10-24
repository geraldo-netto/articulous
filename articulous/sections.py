"""Section metadata and URL-pattern policy."""
from __future__ import annotations

from dataclasses import dataclass
from string import Formatter
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class SectionSpec:
    name: str
    url_key: str
    xsl_file: str
    output_kind: str
    scope: str
    placeholders: frozenset[str]
    # Placeholders a pattern may use but does not have to. A cross-language
    # section that names {lang} becomes per-language, so a site can choose one
    # feed or one per language without the engine deciding for it.
    optional_placeholders: frozenset[str] = frozenset()


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
    SectionSpec(
        "rss", "rss", "rss.xsl", "file", "cross-lang", frozenset(),
        frozenset({"lang"}),
    ),
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
    for _, field, specification, conversion in Formatter().parse(pattern):
        if field is None:
            continue
        if not field.isidentifier() or specification or conversion is not None:
            raise ValueError('URL pattern placeholders require plain names without conversion or formatting')
        fields.add(field)
    return fields


def _validate_placeholders(spec: SectionSpec, pattern: str) -> None:
    fields = _pattern_fields(pattern)
    unknown = fields - (spec.placeholders | spec.optional_placeholders)
    missing = spec.placeholders - fields
    if unknown or missing:
        allowed = f"{sorted(spec.placeholders)}"
        if spec.optional_placeholders:
            allowed += f" plus optional {sorted(spec.optional_placeholders)}"
        raise ValueError(
            f"config urls.{spec.url_key} placeholders must be "
            f"{allowed}; got {sorted(fields)}"
        )


def section_is_per_lang(section: str, pattern: str) -> bool:
    """True when this section produces one output per language.

    Either the section is per-language by nature, or its URL pattern opted in
    by naming {lang}.
    """
    spec = SECTION_BY_NAME[section]
    return spec.scope == "per-lang" or "lang" in _pattern_fields(pattern)


def bare_pattern(pattern: str) -> str:
    return pattern.replace("/{lang}/", "/", 1)


def validate_index_first_pattern(pattern) -> None:
    if not isinstance(pattern, str) or not pattern.startswith('/'):
        raise ValueError('index_first must be an absolute local directory pattern')
    _validate_url_syntax(pattern)
    fields = [(field, spec, conversion) for _, field, spec, conversion in Formatter().parse(pattern)
              if field is not None]
    if not fields or any(item != ('lang', '', None) for item in fields):
        raise ValueError('index_first requires only plain {lang} placeholders')
    path = pattern.format(lang='en')
    if Path(path).suffix or any(part in ('.', '..', '') for part in path.strip('/').split('/')):
        raise ValueError('index_first must be a local directory without dot or empty segments')
    if '//' in path or not pattern.endswith('/'):
        raise ValueError('index_first must end with a single slash')


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
    if spec.output_kind == "file" and (not suffix or pattern.endswith("/")):
        raise ValueError(
            f"config urls.{spec.url_key} must be a file-style pattern"
        )


def output_path_from_pattern(section: str, pattern: str, **kwargs) -> Path:
    rel = pattern.format(**kwargs).strip("/")
    if SECTION_BY_NAME[section].output_kind == "directory":
        return Path(rel) / "index.html"
    return Path(rel)


def _validate_absolute_web_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must be absolute HTTP(S) with a host")
    _validate_web_url_resource(url)


def _validate_web_url_resource(url: str) -> None:
    parsed = urlsplit(url)
    _validate_uri_encoding(url)
    if parsed.username is not None or "?" in url or "#" in url:
        raise ValueError("URL cannot contain credentials, queries, or fragments")
    if parsed.port == 0:
        raise ValueError("URL port must be positive")
    _validate_web_url_path(parsed.path)


def _validate_uri_encoding(url: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9:/?\[\]@!$&'()*+,;=._~%#-]+", url):
        raise ValueError("URL must be URI-encoded without whitespace or controls")
    if re.search(r"%(?![0-9A-Fa-f]{2})", url):
        raise ValueError("URL must use valid percent escapes")


def validate_image_url(url: str) -> None:
    _validate_absolute_web_url(url.split("?", 1)[0])
    _validate_uri_encoding(url)
    if "#" in url:
        raise ValueError("Image URLs cannot contain fragments")


def _validate_web_url_path(path: str) -> None:
    decoded = unquote(path)
    if "\\" in decoded or any(ord(char) < 32 or ord(char) == 127 for char in decoded):
        raise ValueError("URL paths cannot contain backslashes or controls")
    segments = decoded.removeprefix("/").removesuffix("/")
    if segments and any(part in {".", "..", ""} for part in segments.split("/")):
        raise ValueError("URL paths cannot contain dot or empty segments")


def validate_base_url(url: str) -> None:
    if not url:
        return
    if url.startswith("/") and not url.startswith("//"):
        _validate_web_url_resource(url)
    else:
        _validate_absolute_web_url(url)


def validate_sitemap_location(url: str) -> None:
    _validate_absolute_web_url(url)
    if len(url) >= 2048:
        raise ValueError("Native sitemap URLs must have fewer than 2048 characters")
