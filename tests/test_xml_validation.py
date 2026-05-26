"""Fixture XML files are well-formed and carry the required fields."""
import subprocess
from pathlib import Path

FIXTURE_CONTENT = Path(__file__).parent / "fixtures" / "site" / "content"


def _xml_files():
    return list(FIXTURE_CONTENT.rglob("*.xml"))


def test_no_empty_xml_files():
    empty = [f for f in _xml_files() if f.stat().st_size == 0]
    assert not empty, f"Empty XML files: {empty}"


def test_xml_is_well_formed():
    for f in _xml_files():
        r = subprocess.run(
            ["xmllint", "--noout", str(f)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert r.returncode == 0, (
            f"Malformed XML: {f}\n{r.stderr.decode()}"
        )


def test_required_fields_exist():
    required = ["<title>", "<date>", "<description>"]
    for f in _xml_files():
        text = f.read_text(encoding="utf-8")
        for tag in required:
            assert tag in text, f"Missing {tag} in {f}"
