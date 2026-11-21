"""Enumerate a finite directory tree completely or propagate the filesystem error."""
import os
from pathlib import Path


def tree_entries(root: Path, *, skip_directory_prefix: str | None = None, include=None):
    directories = [root]
    while directories:
        with os.scandir(directories.pop()) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    if skip_directory_prefix and entry.name.startswith(skip_directory_prefix):
                        continue
                    directories.append(path)
                if include is None or include(entry):
                    yield path
