"""Optional vocabulary comparisons; no owner vocabulary or display policy."""
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from itertools import islice
from typing import NamedTuple
import difflib
import heapq
import unicodedata


def interchangeable(carriers: dict[str, set[str]]) -> list[list[str]]:
    """Tags carried by exactly the same articles.

    Three names for one list is three routes, three sidebar chips and three
    cloud entries that all land in the same place. Worth merging, unless they
    are meant to separate as the archive grows.

    Tags on a single article are left alone: every article's own vocabulary
    trivially matches itself, and saying so buries the real finding.
    """
    groups: dict[frozenset, list[str]] = {}
    for tag, where in carriers.items():
        if len(where) > 1:
            groups.setdefault(frozenset(where), []).append(tag)
    def group_order(group):
        return -len(group), group
    return sorted((sorted(g) for g in groups.values() if len(g) > 1), key=group_order)


def fold(value: str) -> str:
    folded = unicodedata.normalize('NFKD', value).casefold().replace('-', '').replace(' ', '')
    if folded.isascii():
        return folded
    return ''.join(char for char in folded if not unicodedata.combining(char))


def plural_pairs(names: set[str]) -> list[tuple[str, str]]:
    pairs = []
    for name in sorted(names):
        for plural in (name + 's', name + 'es', name[:-1] + 'ies' if name.endswith('y') else None):
            if plural and plural in names:
                pairs.append((name, plural))
    return pairs


class _Window(NamedTuple):
    min_length: int
    max_length: int
    prefix_length: int


def _ratio(matches, length):
    return 2.0 * matches / length if length else 1.0


def _window(length, lengths, threshold):
    def shorter_bound(overlap):
        return _ratio(overlap, length + overlap)

    least = bisect_left(range(length + 1), threshold, key=shorter_bound)
    shortest = lengths[bisect_left(lengths, least)]
    # The shortest eligible length gives the weakest overlap bound for this bucket.
    def overlap_bound(overlap):
        return _ratio(overlap, length + shortest)

    def longer_bound(other):
        return -_ratio(length, length + other)

    needed = bisect_left(range(shortest + 1), threshold, key=overlap_bound)
    right = bisect_right(lengths, -threshold, lo=bisect_left(lengths, length), key=longer_bound)
    return _Window(shortest, lengths[right - 1], length - needed + 1)


def _ordered_tokens(value, frequencies):
    counts = Counter(value)
    def frequency_order(char):
        return frequencies[char], char

    for char in sorted(counts, key=frequency_order):
        for occurrence in range(counts[char]):
            yield char, occurrence


def _prefix_matches(prefix, window, index):
    matches = set()
    for token in prefix:
        for length, values in index.get(token, {}).items():
            if window.min_length <= length <= window.max_length:
                matches.update(values)
    return matches


def _matching_positions(matches, prior, equal):
    if not matches:
        return equal
    if len(matches) == 1:
        return prior[next(iter(matches))]
    return sorted(position for value in matches for position in prior[value])


def _indexed_positions(normalized, threshold):
    lengths = sorted({len(value) for value in normalized})
    windows = {length: _window(length, lengths, threshold) for length in lengths}
    frequencies = Counter(char for value in set(normalized) for char in set(value))
    prior = defaultdict(list)
    index = {}
    for position, value in enumerate(normalized):
        window = windows[len(value)]
        # A pair reaching the overlap bound shares a token in these prefixes.
        prefix = tuple(islice(_ordered_tokens(value, frequencies), window.prefix_length))
        equal = prior[value]
        yield _matching_positions(_prefix_matches(prefix, window, index), prior, equal)
        if not equal:
            for token in prefix:
                index.setdefault(token, {}).setdefault(len(value), []).append(value)
        equal.append(position)


def _exact_positions(normalized):
    prior = defaultdict(list)
    for position, value in enumerate(normalized):
        equal = prior[value]
        yield equal
        equal.append(position)


def _candidate_positions(normalized, threshold):
    if threshold <= 0:
        return (range(index) for index in range(len(normalized)))
    if threshold <= 1:
        return _indexed_positions(normalized, threshold)
    return _exact_positions(normalized)


def _score_candidates(names, normalized, index, positions, threshold):
    matcher = None
    for position in positions:
        if normalized[position] == normalized[index]:
            yield 1.0, names[position], names[index]
            continue
        if matcher is None:
            matcher = difflib.SequenceMatcher(None, '', normalized[index])
        matcher.set_seq1(normalized[position])
        if matcher.quick_ratio() >= threshold:
            ratio = matcher.ratio()
            if ratio >= threshold:
                yield round(ratio, 2), names[position], names[index]


def duplicate_candidates(names: list[str], threshold: float = 0.8):
    normalized = [fold(name) for name in names]
    if len(normalized) < 2:
        return
    positions = _candidate_positions(normalized, threshold)
    for index, matches in enumerate(positions):
        yield from _score_candidates(names, normalized, index, matches, threshold)



def near_duplicates(names: list[str], threshold: float = 0.8) -> list[tuple[float, str, str]]:
    return sorted(duplicate_candidates(names, threshold), reverse=True)


def duplicate_summary(names, limit=20):
    if type(limit) is not int or limit < 1:
        raise ValueError('Duplicate sample size must be a positive integer')
    best = []
    total = 0
    for candidate in duplicate_candidates(names):
        total += 1
        if len(best) < limit:
            heapq.heappush(best, candidate)
        elif candidate > best[0]:
            heapq.heapreplace(best, candidate)
    return total, sorted(best, reverse=True)


