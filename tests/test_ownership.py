"""Ownership recovery must preserve provenance or stop the build."""
import json

import pytest

from articulous.ownership import load_ownership, ownership_path, save_ownership


@pytest.mark.parametrize("entries", [
    [], {1: "rss.xml"}, {"rss": None}, {"rss": ""}, {"rss": "."},
    {"rss": "../manual.txt"}, {"rss": "/manual.txt"}, {"rss": "assets/style.css"},
])
def test_invalid_legacy_ownership_is_rejected(tmp_path, entries):
    with pytest.raises(ValueError, match="Invalid output ownership entries"):
        load_ownership(tmp_path / "output", entries)


@pytest.mark.parametrize("content", [b"{", b"\xff", b"[]", b'{"version": 2}'])
def test_invalid_ownership_file_requires_recovery(tmp_path, content):
    output = tmp_path / "output"
    ownership_path(output).write_bytes(content)
    with pytest.raises(ValueError, match="Invalid output ownership"):
        load_ownership(output, {"rss": "rss.xml"})


@pytest.mark.parametrize("override", [
    {"output_dir": "/another-output"}, {"outputs": None},
])
def test_ownership_identity_and_entries_are_validated(tmp_path, override):
    output = tmp_path / "output"
    data = {"version": 1, "output_dir": str(output), "outputs": {}}
    data.update(override)
    ownership_path(output).write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Invalid output ownership"):
        load_ownership(output)


def test_empty_output_needs_no_legacy_ownership(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    assert load_ownership(output) == {}


def test_ownership_requires_recovery_for_unknown_existing_output(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    manual = output / "manual.txt"
    manual.write_text("keep")
    with pytest.raises(ValueError, match="Output ownership unavailable"):
        load_ownership(output)
    assert manual.read_text() == "keep"


def test_ownership_save_does_not_rewrite_unchanged_state(tmp_path):
    output = tmp_path / "output"
    entries = {"rss": "rss.xml"}
    save_ownership(output, entries)
    path = ownership_path(output)
    before = path.stat().st_mtime_ns
    save_ownership(output, entries)
    assert path.stat().st_mtime_ns == before
    assert load_ownership(output) == entries
