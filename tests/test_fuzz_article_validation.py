"""Seeded invalid article metadata and calendar-boundary mutations."""
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
