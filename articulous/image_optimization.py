"""Explicit source-image optimization; the build asset mirror never calls it."""
from pathlib import Path
import shutil

from .image_contracts import ImageBackend, ImageResult, KINDS, validate_options
from .source_files import replace_file


def candidates(root: Path, threshold: int, kinds: set[str]):
    for path in sorted(root.rglob('*')):
        if path.is_file() and KINDS.get(path.suffix.lower()) in kinds and path.stat().st_size >= threshold:
            yield path


def optimize(root: Path, backend: ImageBackend, *, largest: int, quality: int,
             threshold: int, kinds: set[str], apply: bool = False):
    validate_options(largest, quality, threshold)
    with backend.workspace() as temporary:
        for path in candidates(root, threshold, kinds):
            width, height = backend.dimensions(path)
            target = temporary / path.name
            backend.shrink(path, target, largest, quality)
            old, new = path.stat().st_size, target.stat().st_size
            if new < old and apply:
                def write_optimized(staged):
                    shutil.copyfile(target, staged)
                replace_file(path, write_optimized)
            yield ImageResult(path, width, height, old, min(old, new))
