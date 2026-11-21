"""Enumerate a finite directory tree completely or propagate the filesystem error."""
import os
from pathlib import Path


def tree_entries(root: Path):
    directories = [root]
    while directories:
        with os.scandir(directories.pop()) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    directories.append(path)
                yield path
