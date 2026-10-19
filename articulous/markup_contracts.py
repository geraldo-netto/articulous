"""Provider-independent markup policy and a scoped, single-use tree borrow."""
from dataclasses import dataclass, field
from typing import Generic, TypeVar

OPAQUE_TAGS = frozenset({'pre', 'code', 'svg', 'path', 'g', 'defs', 'clippath', 'circle', 'iframe', 'script', 'style'})
INLINE_TAGS = frozenset({'a', 'abbr', 'b', 'bdi', 'bdo', 'br', 'cite', 'code', 'data', 'del', 'dfn', 'em', 'i', 'img', 'input', 'ins', 'kbd', 'mark', 'q', 'ruby', 'rp', 'rt', 's', 'samp', 'small', 'span', 'strong', 'sub', 'sup', 'time', 'u', 'var', 'wbr'})
BLOCK_TAGS = frozenset({'p', 'li', 'td', 'th', 'caption', 'blockquote', 'dt', 'dd', 'figcaption', 'summary', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'})


@dataclass(frozen=True)
class MarkupPolicy:
    opaque_tags: frozenset[str] = OPAQUE_TAGS
    inline_tags: frozenset[str] = INLINE_TAGS
    block_tags: frozenset[str] = BLOCK_TAGS
    void_tags: frozenset[str] = frozenset({'br', 'img', 'hr', 'input'})
    translatable_attributes: tuple[str, ...] = ('alt', 'title', 'aria-label', 'placeholder')


Node = TypeVar('Node')


@dataclass
class Encoded(Generic[Node]):
    text: str
    root: Node | None
    snapshot: bytes
    slots: dict[int, Node] = field(default_factory=dict)

    def close(self):
        self.root = None
        self.slots.clear()
        self.snapshot = b''
