"""EDIT-002/REV-102/136: complete duplicate totals, bounded display sample."""

import unittest
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
        for threshold in (0, 0.5, 0.8, 1, 1.1, -1, float("nan")):
            expected = []
            for index, first in enumerate(names):
                for second in names[index + 1 :]:
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
