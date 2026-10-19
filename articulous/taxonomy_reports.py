"""Optional vocabulary comparisons; no owner vocabulary or display policy."""
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
    stripped = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()
    return stripped.lower().replace('-', '').replace(' ', '')


def plural_pairs(names: set[str]) -> list[tuple[str, str]]:
    pairs = []
    for name in sorted(names):
        for plural in (name + 's', name + 'es', name[:-1] + 'ies' if name.endswith('y') else None):
            if plural and plural in names:
                pairs.append((name, plural))
    return pairs


def duplicate_candidates(names: list[str], threshold: float = 0.8):
    normalized = [fold(name) for name in names]
    for index, second in enumerate(names):
        matcher = difflib.SequenceMatcher(None, '', normalized[index])
        for position in range(index):
            first = names[position]
            if normalized[position] == normalized[index]:
                yield (1.0, first, second)
                continue
            matcher.set_seq1(normalized[position])
            if matcher.real_quick_ratio() < threshold:
                continue
            ratio = matcher.ratio()
            if ratio >= threshold:
                yield (round(ratio, 2), first, second)



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


