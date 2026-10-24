"""Explicit source-image optimization; the build asset mirror never calls it."""
from pathlib import Path
import shutil
import stat

from .image_contracts import ImageBackend, ImageResult, KINDS, validate_options
from .source_files import replace_file
from .source_transactions import fingerprint
from .resource_locks import resource_lock


def candidates(root: Path, threshold: int, kinds: set[str]):
    for path in sorted(root.rglob('*')):
        if path.is_file() and KINDS.get(path.suffix.lower()) in kinds and path.stat().st_size >= threshold:
            yield path


def image_generation(path):
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f'Image source must be a regular file: {path}')
    return metadata, metadata.st_mtime_ns, metadata.st_ctime_ns


def require_image(path, generation, digest):
    try:
        unchanged = (image_generation(path) == generation and fingerprint(path) == digest
                     and image_generation(path) == generation)
    except FileNotFoundError:
        unchanged = False
    if not unchanged:
        raise ValueError(f'Image source changed during optimization: {path}')


def apply_image(path, target, generation, digest):
    with resource_lock(path.with_name('.' + path.name + '.articulous.lock')):
        def write_optimized(staged):
            shutil.copyfile(target, staged)
            require_image(path, generation, digest)
        replace_file(path, write_optimized)


def optimize(root: Path, backend: ImageBackend, *, largest: int, quality: int,
             threshold: int, kinds: set[str], apply: bool = False):
    validate_options(largest, quality, threshold)
    with backend.workspace() as temporary:
        for path in candidates(root, threshold, kinds):
            generation = image_generation(path)
            digest = fingerprint(path)
            require_image(path, generation, digest)
            width, height = backend.dimensions(path)
            target = temporary / path.name
            backend.shrink(path, target, largest, quality)
            require_image(path, generation, digest)
            old, new = generation[0].st_size, target.stat().st_size
            if new < old and apply:
                apply_image(path, target, generation, digest)
            yield ImageResult(path, width, height, old, min(old, new))
