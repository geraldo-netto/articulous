"""Independent XML taxonomy edit layout and provenance projection contracts."""
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProvenanceLayout:
    source_element: str
    hash_element: str
    source_reference: Callable[[Path, str], Path]
    hash_fingerprint: Callable[[bytes], str]


@dataclass(frozen=True)
class TaxonomyLayout:
    tag_element: str
    pattern: str
    provenance: ProvenanceLayout | None = None


@dataclass(frozen=True)
class TaxonomyEdits:
    rewritten: int
    refreshed: int
