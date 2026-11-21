"""Language identifiers shared by site configuration and translation directories."""
from collections.abc import Sequence
import re


def validate_languages(languages, *, label='Languages'):
    if not isinstance(languages, Sequence) or isinstance(languages, (str, bytes)):
        raise ValueError(f'{label} must be a sequence of language identifiers')
    seen = set()
    for code in languages:
        if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', code):
            raise ValueError(f'{label} must contain non-empty identifiers using only '
                             'ASCII letters, digits, hyphens, and underscores')
        folded = code.casefold()
        if folded in seen:
            raise ValueError(f'{label} must not contain case-insensitive duplicates')
        seen.add(folded)
