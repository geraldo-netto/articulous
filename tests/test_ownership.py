"""Ownership recovery must preserve provenance or stop the build."""
import json

import pytest

from articulous.composition_contracts import Route
from articulous.ownership import load_ownership, ownership_path, save_ownership


def current_manifest(output):
    return {"version": 2, "output_dir": str(output), "generation": "a" * 32,
            "existing": {}, "paths": {}, "pending": False, "routes": {}, "translations": {}}


@pytest.mark.parametrize("entries", [
    [], {"rss.xml": None}, {"": "rss"}, {".": "rss"}, {"../manual.txt": "rss"},
    {"/manual.txt": "rss"}, {"assets/style.css": "rss"},
])
def test_invalid_current_ownership_is_rejected(tmp_path, entries):
    output = tmp_path / "output"
    ownership_path(output).write_text(json.dumps({**current_manifest(output), "paths": entries}))
    with pytest.raises(ValueError, match="Invalid output ownership entries"):
        load_ownership(output)


@pytest.mark.parametrize("content", [b"{", b"\xff", b"[]", b'{"version": 2}'])
def test_invalid_ownership_file_requires_recovery(tmp_path, content):
    output = tmp_path / "output"
    ownership_path(output).write_bytes(content)
    with pytest.raises(ValueError, match="Invalid output ownership"):
        load_ownership(output)


@pytest.mark.parametrize("override", [
    {"output_dir": "/another-output"}, {"paths": None},
])
def test_ownership_identity_and_entries_are_validated(tmp_path, override):
    output = tmp_path / "output"
    data = current_manifest(output)
    data.update(override)
    ownership_path(output).write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Invalid output ownership"):
        load_ownership(output)


def test_empty_output_needs_no_ownership(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    assert load_ownership(output).paths == {}


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
    entries = {"rss.xml": "rss"}
    routes = {"rss": Route("rss", "rss", "https://example.org/rss.xml", "rss.xml")}
    save_ownership(output, entries, routes=routes, generation="a" * 32, translations={})
    path = ownership_path(output)
    before = path.stat().st_mtime_ns
    save_ownership(output, entries, routes=routes, generation="a" * 32, translations={})
    assert path.stat().st_mtime_ns == before
    assert load_ownership(output).paths == entries


def test_version_one_ownership_requires_recovery(tmp_path):
    output = tmp_path / "output"
    ownership_path(output).write_text(json.dumps({
        "version": 1, "output_dir": str(output), "outputs": {"rss": "rss.xml"},
    }))
    with pytest.raises(ValueError, match="version.*restore"):
        load_ownership(output)


@pytest.mark.parametrize("override", [
    {"version": 3}, {"pending": "false"}, {"paths": {"rss.xml": None}},
    {"paths": {"../rss.xml": "rss"}},
])
def test_invalid_recovery_metadata_is_rejected(tmp_path, override):
    output = tmp_path / "output"
    data = {"version": 2, "output_dir": str(output), "paths": {}, "pending": False}
    data.update(override)
    ownership_path(output).write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Invalid output ownership"):
        load_ownership(output)


@pytest.mark.parametrize("existing", [
    [], {"unknown.xml": None}, {"rss.xml": "invalid"}, {"rss.xml": []}, {"rss.xml": [1, "2"]},
])
def test_invalid_publication_identities_are_rejected(tmp_path, existing):
    output = tmp_path / "output"
    data = {"version": 2, "output_dir": str(output), "paths": {"rss.xml": "rss"},
            "pending": True, "existing": existing}
    ownership_path(output).write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Invalid output ownership publication identities"):
        load_ownership(output)


@pytest.mark.parametrize('value', [None, False, 0, '', [], [[]], [{}]])
def test_matrix02_invalid_root_shape_names_recovery_action(tmp_path, value):
    output = tmp_path / 'output'
    sidecar = ownership_path(output)
    payload = json.dumps(value).encode()
    sidecar.write_bytes(payload)
    with pytest.raises(ValueError, match='Invalid output ownership.*restore') as failure:
        load_ownership(output)
    assert str(sidecar) in str(failure.value)
    assert sidecar.read_bytes() == payload


def test_matrix02_valid_current_object_preserves_ownership(tmp_path):
    output = tmp_path / 'output'
    state = current_manifest(output)
    state.update(paths={'rss.xml': 'rss'}, routes={'rss': {
        'key': 'rss', 'output_path': 'rss.xml', 'url': '/rss.xml', 'section': 'rss'}})
    ownership_path(output).write_text(json.dumps(state))
    assert load_ownership(output).paths == {'rss.xml': 'rss'}
