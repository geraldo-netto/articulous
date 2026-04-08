# tests/test_fuzzing.py
import os
import glob
import random
import subprocess
import pytest

SECTIONS = ["articles", "index", "tags", "rss", "sitemap", "search"]

def run(cmd):
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, f"Command failed: {' '.join(cmd)}\n{result.stderr.decode()}"

def test_partial_build_fuzz():
    for _ in range(5):
        section = random.choice(SECTIONS)
        run(["./sitegen.py", "--verbose", "--only", section])

def test_random_order_fuzz():
    for _ in range(3):
        order = SECTIONS[:]
        random.shuffle(order)
        for section in order:
            run(["./sitegen.py", "--verbose", "--only", section])

def test_file_touch_fuzz():
    xml_files = glob.glob("content/**/*.xml", recursive=True)
    for _ in range(5):
        f = random.choice(xml_files)
        os.utime(f, None)
        run(["./sitegen.py", "--verbose"])

