"""Fixture XML files are well-formed and carry the required fields."""
from pathlib import Path

import lxml.etree as etree

from articulous.engines import safe_xml_parser

FIXTURE_CONTENT = Path(__file__).parent / "fixtures" / "site" / "content"


def _xml_files():
    return list(FIXTURE_CONTENT.rglob("*.xml"))


def test_no_empty_xml_files():
    empty = [f for f in _xml_files() if f.stat().st_size == 0]
    assert not empty, f"Empty XML files: {empty}"


def test_xml_is_well_formed():
    for f in _xml_files():
        etree.parse(str(f), parser=safe_xml_parser())


def test_required_fields_exist():
    required = ["<title>", "<date>", "<description>"]
    for f in _xml_files():
        text = f.read_text(encoding="utf-8")
        for tag in required:
            assert tag in text, f"Missing {tag} in {f}"
