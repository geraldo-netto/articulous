# tests/test_generator_basic.py
import os
import shutil
from pathlib import Path


def _safe_clean(path: Path) -> None:
    """
    Remove ``path`` only if it is a regular directory under the test's
    working directory. Refuses to follow symlinks: a hostile symlink
    inside the repo could otherwise redirect rmtree to delete an
    arbitrary tree.
    """
    if not path.exists():
        return
    if path.is_symlink():
        raise RuntimeError(f"refusing to clean symlinked path: {path}")
    if not path.is_dir():
        raise RuntimeError(f"refusing to clean non-directory: {path}")
    resolved = path.resolve()
    cwd = Path.cwd().resolve()
    if not resolved.is_relative_to(cwd):
        raise RuntimeError(
            f"refusing to clean path outside cwd: {resolved} (cwd={cwd})"
        )
    shutil.rmtree(resolved)


def test_full_build(run_sitegen):
    _safe_clean(Path("output"))
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
