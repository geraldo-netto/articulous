# tests/test_generator_basic.py
import os
import shutil


def test_full_build(run_sitegen):
    if os.path.isdir("output"):
        shutil.rmtree("output")
    run_sitegen(["--force", "--verbose"])


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
