"""Section-order fuzz tests driving the full pipeline via the CLI."""
import os
import random

from conftest import xml_files

SECTIONS = ["articles", "index", "tags", "rss", "sitemap", "search"]


def test_partial_build_fuzz(site_root, run_sitegen):
    rnd = random.Random(0xC0FFEE)
    for _ in range(5):
        section = rnd.choice(SECTIONS)  # NOSONAR - deterministic test data, not security-sensitive
        run_sitegen(["--verbose", "--only", section])


def test_random_order_fuzz(site_root, run_sitegen):
    rnd = random.Random(42)
    for _ in range(3):
        order = SECTIONS[:]
        rnd.shuffle(order)  # NOSONAR - deterministic test data, not security-sensitive
        for section in order:
            run_sitegen(["--verbose", "--only", section])


def test_file_touch_fuzz(site_root, run_sitegen):
    files = xml_files(site_root / "content")
    rnd = random.Random(7)
    for _ in range(5):
        f = rnd.choice(files)  # NOSONAR - deterministic test data, not security-sensitive
        os.utime(f, None)
        run_sitegen(["--verbose"])
