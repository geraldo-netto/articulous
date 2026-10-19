"""Immutable publication metadata projections, independent of theme XML and storage."""
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Generic, Protocol, TypeVar

from .article_contracts import PublicationPolicy
from .slugs import normalize_slug


class TaggedRecord(Protocol):
    @property
    def lang(self) -> str:
        ...

    @property
    def tags(self) -> tuple[str, ...]:
        ...

    @property
    def policy(self) -> PublicationPolicy:
        ...


Record = TypeVar('Record', bound=TaggedRecord)


@dataclass(frozen=True)
class TagCount:
    slug: str
    count: int
    label: str


def normalized_tag_counts(articles: Iterable[TaggedRecord], language: str) -> tuple[TagCount, ...]:
    counts = Counter()
    labels = {}
    for article in articles:
        if article.lang != language or not article.policy.listing:
            continue
        membership = set()
        for tag in dict.fromkeys(article.tags):
            slug = normalize_slug(tag)
            if slug and slug not in membership:
                membership.add(slug)
                counts[slug] += 1
                labels.setdefault(slug, tag)
    return tuple(TagCount(slug, count, labels[slug]) for slug, count in sorted(counts.items()))


def _language_codes(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError('Catalogue languages must be a collection')
    languages = tuple(values)
    if not languages or any(not isinstance(value, str) or not value.strip() for value in languages):
        raise ValueError('Catalogue language codes must be nonempty strings')
    if len(languages) != len(set(languages)):
        raise ValueError('Catalogue language codes must be unique')
    return languages


def _counts_by_language(articles, languages):
    groups = {language: [] for language in languages}
    for article in articles:
        language = getattr(article, 'lang', None)
        if language not in groups:
            raise ValueError('Catalogue article language is disabled')
        groups[language].append(article)
    return MappingProxyType({language: normalized_tag_counts(group, language)
                             for language, group in groups.items()})


class PublicationCatalogue(Generic[Record]):
    def __init__(self, articles: Iterable[Record], languages: Iterable[str]):
        self._languages = _language_codes(languages)
        if isinstance(articles, (str, bytes, dict)):
            raise ValueError('Catalogue articles must be a collection of records')
        self._articles = tuple(articles)
        self._counts = _counts_by_language(self._articles, self._languages)

    @property
    def articles(self) -> tuple[Record, ...]:
        return self._articles

    def tag_counts(self, language: str) -> tuple[TagCount, ...]:
        if language not in self._counts:
            raise ValueError('Catalogue language is disabled')
        return self._counts[language]
