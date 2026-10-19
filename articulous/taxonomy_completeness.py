"""TAG-007: literal taxonomy requirements, independent of XML and Articulous."""
from dataclasses import dataclass
import re
from collections.abc import Iterable, Mapping, Sequence


def text_field(value: object, allow_blank: bool = False) -> None:
    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        raise ValueError('TAG-007: expected a string tag/identity or textual summary field')


@dataclass(frozen=True)
class TagSummary:
    key: str
    source: str
    title: str
    description: str
    tags: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in (self.key, self.source):
            text_field(value)
        for value in (self.title, self.description):
            text_field(value, allow_blank=True)
        if not isinstance(self.tags, tuple):
            raise ValueError('TAG-007: tags must be an immutable tuple of names')
        for value in self.tags:
            text_field(value)


def tag_pattern(name: str) -> re.Pattern:
    text_field(name)
    phrase = r'[\s-]+'.join(re.escape(part) for part in re.split(r'[\s-]+', name.strip()))
    return re.compile(r'(?<!\w)' + phrase + r'(?!\w)', re.IGNORECASE)


def required_tags(group: Sequence[TagSummary], patterns: Mapping[str, re.Pattern]) -> set[str]:
    required = set()
    for summary in group:
        required.update(summary.tags)
    for name, pattern in patterns.items():
        if any(pattern.search(row.title) or pattern.search(row.description) for row in group):
            required.add(name)
    return required


def summary_groups(summaries: object) -> dict[str, list[TagSummary]]:
    if isinstance(summaries, (str, bytes, Mapping)) or not isinstance(summaries, Iterable):
        raise ValueError('TAG-007: expected a collection of TagSummary records')
    groups: dict[str, list[TagSummary]] = {}
    sources = set()
    for summary in summaries:
        if not isinstance(summary, TagSummary):
            raise ValueError('TAG-007: expected TagSummary records')
        if summary.source in sources:
            raise ValueError('TAG-007: duplicate summary source')
        sources.add(summary.source)
        groups.setdefault(summary.key, []).append(summary)
    return groups


def missing_tags(summaries: object) -> dict[str, tuple[str, ...]]:
    groups = summary_groups(summaries)
    vocabulary = {name for group in groups.values() for row in group for name in row.tags}
    patterns = {name: tag_pattern(name) for name in sorted(vocabulary)}
    missing = {}
    for group in groups.values():
        required = required_tags(group, patterns)
        for summary in group:
            names = tuple(sorted(required - set(summary.tags)))
            if names:
                missing[summary.source] = names
    return missing
