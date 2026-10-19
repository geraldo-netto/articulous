"""Independent TAG-003 taxonomy contract; validation never rewrites tags."""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
from types import MappingProxyType


def policy_slug(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value):
        raise ValueError(f'TAG-003: invalid normalized tag slug: {value!r}')
    return value


def removed_tags(value: object) -> frozenset[str]:
    if not isinstance(value, list):
        raise ValueError('TAG-003: removed must be a list of unique normalized slugs')
    names = frozenset(policy_slug(name) for name in value)
    if len(names) != len(value):
        raise ValueError('TAG-003: duplicate removed tag')
    return names


def merged_tags(value: object, removed: frozenset[str]) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError('TAG-003: merged must map retired slugs to canonical slugs')
    names = {policy_slug(old):policy_slug(new) for old, new in value.items()}
    retired = set(names)
    if retired & removed:
        raise ValueError('TAG-003: a retired tag cannot be both removed and merged')
    if set(names.values()) & (retired | removed):
        raise ValueError('TAG-003: merge targets must be current tags; chains and cycles are forbidden')
    return MappingProxyType(names)


@dataclass(frozen=True)
class TagPolicy:
    removed: frozenset[str]
    merged: Mapping[str, str]

    @classmethod
    def from_mapping(cls, value: object) -> 'TagPolicy':
        if not isinstance(value, Mapping) or set(value) != {'schema', 'removed', 'merged'}:
            raise ValueError('TAG-003: invalid tag policy fields')
        if type(value['schema']) is not int or value['schema'] != 1:
            raise ValueError('TAG-003: unsupported tag policy schema')
        removed = removed_tags(value['removed'])
        return cls(removed, merged_tags(value['merged'], removed))

    def validate(self, slugs: object, source: str) -> None:
        if isinstance(slugs, (str, bytes)) or not isinstance(slugs, Iterable):
            raise ValueError('TAG-003: tags must be a collection of normalized slugs, not a scalar')
        for value in slugs:
            if value == '':
                continue  # Unroutable labels retain the existing article contract.
            name = policy_slug(value)
            if name in self.removed:
                raise ValueError(f'TAG-003: {source}: tag {name!r} was removed; edit the source XML')
            target = self.merged.get(name)
            if target is not None:
                raise ValueError(f'TAG-003: {source}: tag {name!r} was merged; use {target!r} in the source XML')
