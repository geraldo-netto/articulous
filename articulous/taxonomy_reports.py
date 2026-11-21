"""Optional vocabulary comparisons; no owner vocabulary or display policy."""
from bisect import bisect_left
from collections import Counter, defaultdict
from functools import lru_cache, partial
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
    width: int
    overlap: int


def _ratio(matches, length):
    return 2.0 * matches / length if length else 1.0


def _window(length, lengths, threshold):
    def shorter_bound(overlap):
        return _ratio(overlap, length + overlap)

    least = bisect_left(range(length + 1), threshold, key=shorter_bound)
    shortest = lengths[bisect_left(lengths, least)]
    shared_bigrams = _minimum_bigrams(length, shortest, threshold)
    if shared_bigrams > 0:
        return _Window(2, shared_bigrams)
    return _Window(1, _minimum_matches(length, shortest, threshold))


def _minimum_matches(first, second, threshold):
    def score(matches):
        return _ratio(matches, first + second)
    return bisect_left(range(min(first, second) + 1), threshold, key=score)


def _minimum_bigrams(length, shortest, threshold):
    combined = length + shortest
    # M ordered matches in combined length N form at most N - 2*M + 1 runs.
    # With fewer than b shared bigrams, 3*M <= N + b. The resulting ratio
    # bound 2*(N + b)/(3*N) is weakest at the shortest eligible N.
    def upper_bound(bigrams):
        return _ratio(combined + bigrams, 3 * combined)

    return bisect_left(range(length), threshold, key=upper_bound) - 1


def _occurrences(value, width):
    grams = (value[offset:offset + width] for offset in range(len(value) - width + 1))
    for gram, count in Counter(grams).items():
        for occurrence in range(count):
            yield gram, occurrence


_BLOCK_SIZE = 256


def _add_occurrences(planes, mask):
    """Add one to each selected counter, with one bit per tag in each binary digit."""
    for place, plane in enumerate(planes):
        planes[place] = plane ^ mask
        mask &= plane
        if not mask:
            return
    planes.append(mask)


def _at_least(planes, minimum):
    """Compare each counter to minimum - 1, from least to most significant bit."""
    if minimum.bit_length() > len(planes):
        return 0
    threshold = minimum - 1
    greater = 0
    for place, plane in enumerate(planes):
        if threshold & (1 << place):
            greater &= plane
        else:
            greater |= plane
    return greater


class _OverlapIndex:
    """Bound sparse token postings to fixed-size blocks of distinct folded names."""
    def __init__(self, windows, threshold):
        self.minimum_matches = lru_cache(maxsize=256)(partial(_minimum_matches, threshold=threshold))
        self.widths = {1, *(window.width for window in windows.values())}
        self.lengths = defaultdict(dict)
        self.values = []
        self.postings = {}

    def add(self, value):
        block, offset = divmod(len(self.values), _BLOCK_SIZE)
        self.values.append(value)
        bit = 1 << offset
        lengths = self.lengths[block]
        lengths[len(value)] = lengths.get(len(value), 0) | bit
        for width in self.widths:
            for token in _occurrences(value, width):
                blocks = self.postings.setdefault(token, {})
                blocks[block] = blocks.get(block, 0) | bit

    def _counts(self, tokens):
        counts = {}
        for token in tokens:
            for block, mask in self.postings.get(token, {}).items():
                _add_occurrences(counts.setdefault(block, []), mask)
        return counts

    def _character_counts(self, tokens, block, selected):
        planes = []
        for token in tokens:
            shared = selected & self.postings.get(token, {}).get(block, 0)
            if shared:
                _add_occurrences(planes, shared)
        return planes

    def _qualified(self, block, selected, planes, length):
        mask = 0
        for size, members in self.lengths[block].items():
            subset = selected & members
            if subset:
                mask |= subset & _at_least(planes, self.minimum_matches(length, size))
        return mask

    def matches(self, value, window):
        chars = tuple(_occurrences(value, 1))
        tokens = chars if window.width == 1 else _occurrences(value, window.width)
        result = set()
        for block, planes in self._counts(tokens).items():
            selected = _at_least(planes, window.overlap)
            if selected:
                if window.width > 1:
                    planes = self._character_counts(chars, block, selected)
                mask = self._qualified(block, selected, planes, len(value))
                result.update(self._values_at(block, mask))
        return result

    def _values_at(self, block, mask):
        while mask:
            bit = mask & -mask
            yield self.values[block * _BLOCK_SIZE + bit.bit_length() - 1]
            mask ^= bit


def _matching_positions(matches, prior, equal):
    if not matches:
        return equal
    if len(matches) == 1:
        return prior[next(iter(matches))]
    return sorted(position for value in matches for position in prior[value])


def _indexed_positions(normalized, threshold):
    lengths = sorted({len(value) for value in normalized})
    windows = {length: _window(length, lengths, threshold) for length in lengths}
    prior = defaultdict(list)
    index = _OverlapIndex(windows, threshold)
    for position, value in enumerate(normalized):
        equal = prior[value]
        yield _matching_positions(index.matches(value, windows[len(value)]), prior, equal)
        if not equal:
            index.add(value)
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
        ratio = matcher.ratio()
        if ratio >= threshold:
            yield round(ratio, 2), names[position], names[index]


def duplicate_candidates(names: list[str], threshold: float = 0.8):
    """Score pairs in ascending original-name order, independent of the input order."""
    names = sorted(names)
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


