"""Seeded invalid article metadata and calendar-boundary mutations."""
from datetime import datetime, timezone
import random

import lxml.etree as etree
import pytest

from articulous.articles import parse_article_xml


SEEDS = (0xBAD, 2026, 0xC0FFEE)
FIELDS = {
    "title": "Title", "date": "2025-01-01", "description": "Description",
    "lang": "en", "status": "published", "publish-at": "2025-01-01T00:00:00Z",
}


def _article_root():
    root = etree.Element("article")
    for field, value in FIELDS.items():
        etree.SubElement(root, field).text = value
    return root


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_repeated_singletons_never_select_a_winning_value(tmp_path, caplog, seed):
    rng = random.Random(seed)
    path = tmp_path / "article.xml"
    for _ in range(40):
        root = _article_root()
        field = rng.choice(tuple(FIELDS))
        for _ in range(rng.randint(1, 6)):
            etree.SubElement(root, field).text = rng.choice(["", FIELDS[field], "private", "conflict"])
        children = list(root)
        rng.shuffle(children)
        root[:] = children
        path.write_bytes(etree.tostring(root))
        caplog.clear()
        assert parse_article_xml(path) is None, (seed, field, etree.tostring(root))
        assert f"duplicate singleton field <{field}>" in caplog.text
        assert str(path) in caplog.text


def _invalid_dates(seed):
    rng = random.Random(seed)
    for _ in range(20):
        yield f"{rng.choice([0, rng.randint(10000, 999999)]):04}-01-01"
        yield f"2025-{rng.choice([0, rng.randint(13, 99)]):02}-01"
        yield f"2025-01-{rng.choice([0, rng.randint(32, 99)]):02}"
        yield f"2025-01-01T{rng.randint(24, 99):02}:00:00"


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_out_of_range_article_dates_are_skipped(tmp_path, caplog, seed):
    path = tmp_path / "article.xml"
    for date in _invalid_dates(seed):
        root = _article_root()
        root.find("date").text = date
        path.write_bytes(etree.tostring(root))
        caplog.clear()
        assert parse_article_xml(path) is None, (seed, date)
        assert "missing/invalid date" in caplog.text


@pytest.mark.parametrize("raw", [
    "2025-01-01T24:00:00Z", "20250101T240000.000+01:00",
    "2025-W01-1T24", "2025W01T24", "2025-W01-2400", "2025010112400",
])
@pytest.mark.parametrize("field", ["date", "publish-at"])
def test_end_of_day_hour_rejected_for_article_dates(tmp_path, caplog, raw, field):
    """MATRIX-03: hour 24 cannot roll a date or a scheduled release forward."""
    path = tmp_path / "article.xml"
    root = _article_root()
    root.find("status").text = "scheduled"
    root.find(field).text = raw
    path.write_bytes(etree.tostring(root))
    article = parse_article_xml(path)
    if field == "publish-at":
        assert article is not None
        assert article.publication_state.publish_at == datetime.max.replace(tzinfo=timezone.utc)
        assert "invalid publish-at" in caplog.text
    else:
        assert article is None
        assert "missing/invalid date" in caplog.text


def test_end_of_day_hour_rejected_for_modification_date(tmp_path):
    """MATRIX-03: sitemap dates follow the same clock-hour limits."""
    path = tmp_path / "article.xml"
    root = _article_root()
    etree.SubElement(root, "modified").text = "2025-12-31T24:00:00Z"
    path.write_bytes(etree.tostring(root))
    assert parse_article_xml(path) is None


@pytest.mark.parametrize(("raw", "expected"), [
    ("2025-01-24", "2025-01-24T00:00:00+00:00"),
    ("2025-01-24T00:00:00+00:24", "2025-01-23T23:36:00+00:00"),
    ("20250124T235959.999999Z", "2025-01-24T23:59:59.999999+00:00"),
    ("2025-W24-2T00:00:00", "2025-06-10T00:00:00+00:00"),
    ("2025W012400", "2024-12-31T00:00:00+00:00"),
    ("2025-W24-232400", "2025-06-09T23:24:00+00:00"),
    ("2025W242T00", "2025-06-10T00:00:00+00:00"),
])
def test_article_clock_boundaries(tmp_path, raw, expected):
    """MATRIX-03: day, week and offset components may contain 24."""
    path = tmp_path / "article.xml"
    root = _article_root()
    root.find("date").text = raw
    path.write_bytes(etree.tostring(root))
    article = parse_article_xml(path)
    assert article is not None
    assert article.datetime.isoformat() == expected
