# tests/test_xml_validation.py
import os
import glob
import subprocess
import pytest

CONTENT_DIR = "content"

def test_no_empty_xml_files():
    xml_files = glob.glob(f"{CONTENT_DIR}/**/*.xml", recursive=True)
    empty = [f for f in xml_files if os.path.getsize(f) == 0]
    assert not empty, f"Empty XML files found: {empty}"

def test_xml_is_well_formed():
    xml_files = glob.glob(f"{CONTENT_DIR}/**/*.xml", recursive=True)
    for f in xml_files:
        result = subprocess.run(
            ["xmllint", "--noout", f],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert result.returncode == 0, f"Malformed XML: {f}\n{result.stderr.decode()}"

def test_required_fields_exist():
    required = ["<title>", "<date>", "<description>"]
    xml_files = glob.glob(f"{CONTENT_DIR}/**/*.xml", recursive=True)

    for f in xml_files:
        text = open(f, "r", encoding="utf-8").read()
        for tag in required:
            assert tag in text, f"Missing {tag} in {f}"

