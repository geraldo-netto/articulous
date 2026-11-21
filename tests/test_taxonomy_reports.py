"""EDIT-002/REV-102/136: complete duplicate totals, bounded display sample."""

import unittest
import difflib
import math
import random

import pytest
from articulous import taxonomy_reports as reports


class DuplicateReportCost(unittest.TestCase):
    def test_rev102_reuses_normalized_names_without_losing_pairs(self):
        from unittest.mock import patch
        import difflib
        import random
        from articulous import taxonomy_reports as report

        names = ["café", "cafe", "foo-bar", "foo bar", "日本語", "", "tag", "tags"]
        randomizer = random.Random(102)
        names += [
            "".join(randomizer.choices("abc-é ", k=size)) for size in range(1, 25)
        ]
        ordered = sorted(names)
        for threshold in (0, 0.5, 0.8, 1, 1.1, -1, float("nan")):
            expected = []
            for index, first in enumerate(ordered):
                for second in ordered[index + 1 :]:
                    left, right = report.fold(first), report.fold(second)
                    if left == right:
                        expected.append((1.0, first, second))
                        continue
                    ratio = difflib.SequenceMatcher(None, left, right).ratio()
                    if ratio >= threshold:
                        expected.append((round(ratio, 2), first, second))
            with patch.object(report, "fold", wraps=report.fold) as fold:
                self.assertEqual(
                    sorted(expected, reverse=True),
                    report.near_duplicates(names, threshold),
                )
                self.assertLessEqual(
                    fold.call_count,
                    len(names),
                    "each tag normalization must be reusable",
                )
        self.assertEqual([], report.near_duplicates([]))


def test_edit002_groups_plurals_and_normalization():
    assert reports.interchangeable(
        {"a": {"x", "y"}, "b": {"x", "y"}, "c": {"z"}, "d": {"one", "two"}}
    ) == [["a", "b"]]
    assert reports.plural_pairs(
        {"city", "cities", "class", "classes", "toy", "toys"}
    ) == [("city", "cities"), ("class", "classes"), ("toy", "toys")]
    assert reports.fold("Café - Name") == "cafename"


@pytest.mark.parametrize(("name", "expected"), [
    ("Москва", "москва"), ("Київ", "киів"), ("Python入門", "python入門"),
    ("Python基礎", "python基礎"), ("Straße", "strasse"), ("कला", "कला"),
])
def test_review28_49_preserves_unicode_letters_and_spacing_marks(name, expected):
    assert reports.fold(name) == expected


def test_review28_49_distinct_scripts_do_not_fill_the_exact_duplicate_sample():
    names = ["Москва", "Київ", "Python入門", "Python基礎", "python", "Straße", "STRASSE", "strae"]
    assert reports.near_duplicates(names, 1.0) == [(1.0, "STRASSE", "Straße")]


def test_review28_53_equal_length_tags_skip_unrelated_pairs(monkeypatch):
    names = [f"tag-{chr(0x4E00 + index) * 12}" for index in range(512)]
    quick_ratio = difflib.SequenceMatcher.quick_ratio
    checks = []

    def count(matcher):
        checks.append(1)
        return quick_ratio(matcher)

    monkeypatch.setattr(difflib.SequenceMatcher, "quick_ratio", count)
    assert reports.duplicate_summary(names) == (0, [])
    assert len(checks) <= len(names)


def _direct_candidates(names, threshold):
    names = sorted(names)
    values = [reports.fold(name) for name in names]
    for right, second in enumerate(names):
        for left in range(right):
            if values[left] == values[right]:
                yield 1.0, names[left], second
            else:
                ratio = difflib.SequenceMatcher(None, values[left], values[right]).ratio()
                if ratio >= threshold:
                    yield round(ratio, 2), names[left], second


@pytest.mark.parametrize("seed", range(8))
def test_review28_53_order_bounds_and_sample_match_all_pairs(seed):
    rng = random.Random(seed)
    names = ["", "-", "a", "aa", "aab", "aba", "aabb", "AABB", "aBb", "abBb", "東京"]
    names.extend("".join(rng.choices("aaabbccéßΩЖ日🗺 ", k=rng.randrange(30))) for _ in range(24))
    names.extend(("ß" * 99 + "xyz", "SS" * 100 + "x", "ss" * 100 + "zyx"))
    boundary = 2 / 3
    for threshold in (-math.inf, 0, math.nextafter(boundary, 0), boundary,
                      math.nextafter(boundary, 1), 0.8, 1, 1.1, math.inf, math.nan):
        expected = list(_direct_candidates(names, threshold))
        assert list(reports.duplicate_candidates(names, threshold)) == expected
    expected = sorted(_direct_candidates(names, 0.8), reverse=True)
    assert reports.duplicate_summary(names, 7) == (len(expected), expected[:7])


@pytest.mark.parametrize("limit", [None, False, 0, -1, 1.5, "1"])
def test_edit002_invalid_sample_capacity(limit):
    with pytest.raises(ValueError, match="positive integer"):
        reports.duplicate_summary(["x"], limit)


def test_rev136_complete_dense_totals_with_bounded_storage(monkeypatch):
    import tracemalloc

    names = [f"tag-{index:04}" for index in range(500)]
    monkeypatch.setattr(reports, "fold", same_name)
    tracemalloc.start()
    try:
        total, best = reports.duplicate_summary(names)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert total == 500 * 499 // 2
    assert len(best) == 20
    assert peak < 2_000_000
    assert reports.duplicate_summary([]) == (0, [])
    assert reports.duplicate_summary(["same"], 1) == (0, [])


def same_name(value):
    return "same"


def test_review28_51_permuting_tags_preserves_scores_pairs_and_top_k():
    from itertools import permutations

    names = ['amaterasu', 'amateurs', 'A', 'a']
    pairs = [(1.0, 'A', 'a'), (0.82, 'amaterasu', 'amateurs')]
    assert reports.near_duplicates(['amateurs', 'amaterasu']) == pairs[1:]
    for order in permutations(names):
        assert reports.near_duplicates(list(order)) == pairs
        assert list(reports.duplicate_candidates(list(order))) == pairs
        assert reports.duplicate_summary(list(order), 1) == (2, pairs[:1])
