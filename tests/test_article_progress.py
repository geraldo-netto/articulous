"""Long scans report aggregate progress without logging every file."""
import logging

import pytest

from articulous.articles import ArticleStats, iter_articles


def _write_article(path, status="published"):
    path.write_text(
        f"<article><title>{path.stem}</title><date>2025-01-01</date>"
        f"<status>{status}</status></article>"
    )


def _progress_messages(caplog):
    return [record.message for record in caplog.records
            if record.levelno == logging.INFO and "Article scan progress:" in record.message]


@pytest.mark.parametrize("provided_stats", [False, True])
def test_scan_progress_is_rate_limited_and_counts_skipped_files(tmp_path, monkeypatch, caplog, provided_stats):
    _write_article(tmp_path / "a.xml")
    (tmp_path / "b.xml").write_text("invalid XML")
    _write_article(tmp_path / "c.xml", "private")
    (tmp_path / "d.xml").write_text("invalid XML")
    clock = iter([0.0, 1.0, 5.0, 5.1, 10.0])
    monkeypatch.setattr("articulous.articles.monotonic", lambda: next(clock))
    stats = ArticleStats() if provided_stats else None
    with caplog.at_level(logging.INFO):
        articles = list(iter_articles(tmp_path, stats=stats))
    assert len(articles) == 2
    assert not articles[1].policy.page
    assert _progress_messages(caplog) == [
        "Article scan progress: 2 scanned, 1 parsed, 1 skipped",
        "Article scan progress: 4 scanned, 2 parsed, 2 skipped",
    ]
    if stats is not None:
        assert stats == ArticleStats(scanned=4, parsed=2, skipped=2)


def test_short_scan_emits_no_progress_messages(tmp_path, monkeypatch, caplog):
    _write_article(tmp_path / "a.xml")
    _write_article(tmp_path / "b.xml")
    clock = iter([0.0, 0.1, 4.9])
    monkeypatch.setattr("articulous.articles.monotonic", lambda: next(clock))
    with caplog.at_level(logging.INFO):
        assert len(list(iter_articles(tmp_path))) == 2
    assert _progress_messages(caplog) == []
