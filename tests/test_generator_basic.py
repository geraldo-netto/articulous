# tests/test_generator_basic.py
import os
import subprocess
import pytest

def test_full_build():
    # Clean output
    if os.path.isdir("output"):
        subprocess.run(["rm", "-rf", "output"])

    result = subprocess.run(
        ["./sitegen.py", "--force", "--verbose"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, f"Build failed:\n{result.stderr.decode()}"

def test_output_directory_exists():
    assert os.path.isdir("output"), "Output directory missing after build"

def test_required_output_files():
    required = [
        "output/rss.xml",
        "output/sitemap.xml",
        "output/search.json",
    ]
    missing = [f for f in required if not os.path.isfile(f)]
    assert not missing, f"Missing required output files: {missing}"

