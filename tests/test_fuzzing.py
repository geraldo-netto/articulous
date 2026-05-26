# tests/test_fuzzing.py
import os
import random

from conftest import xml_files

SECTIONS = ["articles", "index", "tags", "rss", "sitemap", "search"]


def test_partial_build_fuzz(run_sitegen):
    for _ in range(5):
        section = random.choice(SECTIONS)
        run_sitegen(["--verbose", "--only", section])


def test_random_order_fuzz(run_sitegen):
    for _ in range(3):
        order = SECTIONS[:]
        random.shuffle(order)
        for section in order:
            run_sitegen(["--verbose", "--only", section])


def test_file_touch_fuzz(run_sitegen):
    files = xml_files()
    for _ in range(5):
        f = random.choice(files)
        os.utime(f, None)
        run_sitegen(["--verbose"])
