"""Measure the warm incremental build with the checkout on PYTHONPATH."""
import argparse
import gc
import json
import logging
import os
import shutil
import tempfile
import tracemalloc
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from articulous import pipeline
from articulous.configuration_contracts import BuildRequest


def create_corpus(root, count):
    fixture = Path(pipeline.__file__).resolve().parents[1] / "tests/fixtures/site"
    shutil.copytree(fixture, root, dirs_exist_ok=True)
    shutil.rmtree(root / "content")
    config = json.loads((root / "config.json").read_text())
    languages = ["en", "fr", "de"]
    config["site"]["languages"] = languages
    config["site"]["pagination"]["per_page"] = 20
    for lang in languages:
        (root / "content" / lang).mkdir(parents=True)
    for index in range(count):
        lang = languages[index % len(languages)]
        (root / "content" / lang / f"{index}.xml").write_text(
            f"<article><title>Article {index}</title><date>2025-01-01</date>"
            f"<description>Article {index}</description><lang>{lang}</lang>"
            f"<tag>Tag {index % 65}</tag><body><p>Body.</p></body></article>"
        )
    return config


def _state_file_kind(name):
    if name.startswith(".articulous-activity-retire-"):
        return "activity retirement"
    if name.startswith(".articulous-activity-"):
        return "activity"
    if name in {".build-cache.json", ".output.articulous-ownership.json"}:
        return name
    return None


def measured_build(root, config, *, trace):
    result = {}
    writes = defaultdict(list)
    run_plan = pipeline._run_plan
    replace = os.replace

    def at_render(plan, ctx):
        if trace:
            gc.collect()
            live, peak = tracemalloc.get_traced_memory()
            result.update(render_live=live, planning_peak=peak)
        return run_plan(plan, ctx)

    def count_replace(source, target, **kwargs):
        replace(source, target, **kwargs)
        kind = _state_file_kind(Path(target).name)
        if kind is not None:
            writes[kind].append(os.stat(target, dir_fd=kwargs.get("dst_dir_fd")).st_size)

    if trace:
        tracemalloc.start()
    try:
        with patch.object(pipeline, "_run_plan", at_render), patch.object(os, "replace", count_replace):
            pipeline.run_build(BuildRequest(), config, root)
        if trace:
            result["build_peak"] = tracemalloc.get_traced_memory()[1]
    finally:
        if trace:
            tracemalloc.stop()
    return {**result, "state_replacement_bytes": dict(writes)}


def measure(root, count, rename):
    config = create_corpus(root, count)
    runs = [("cold", False), ("warm", True), ("edited", False)]
    if rename:
        runs = [("cold", False), ("renamed", True)]
    changes = {
        "renamed": ("<title>Article 0</title>", "<title>Renamed article</title>"),
        "edited": ("Body.", "Changed."),
    }
    for label, trace in runs:
        if label in changes:
            path = root / "content/en/0.xml"
            path.write_text(path.read_text().replace(*changes[label]))
        result = measured_build(root, config, trace=trace)
        print(json.dumps({"articles": count, "build": label, **result}), flush=True)


if __name__ == "__main__":
    logging.disable(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("articles", type=int, choices=(4000, 12000))
    parser.add_argument("--rename", action="store_true", help="trace a route rename immediately after the cold build")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        measure(Path(temporary), args.articles, args.rename)
