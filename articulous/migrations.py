"""Plan removal of owned files that obstruct replacement output routes."""
from pathlib import Path

from .filesystem import validate_output_path, validate_regular_file


class OutputMigrations:
    def __init__(self, root: Path, previous: dict, retained: dict):
        self.root = root.resolve()
        self.previous = previous
        self.selected = previous.keys() - retained.keys()
        self._targets: set[Path] = set()

    def _owned_file(self, path: Path) -> Path:
        validate_output_path(path)
        if path.relative_to(self.root).as_posix() not in self.selected:
            raise ValueError(f"Output migration would remove an unowned or retained path: {path}")
        validate_regular_file(path)
        return path

    def _directory_files(self, path: Path) -> set[Path]:
        relative = path.relative_to(self.root).as_posix()
        if relative in self.previous and not any(entry.startswith(relative + "/") for entry in self.previous):
            raise ValueError(f"Path must be a regular file: {path}")
        files = set()
        directories = {path}
        for entry in path.rglob("*"):
            validate_output_path(entry)
            if entry.is_dir():
                directories.add(entry)
            else:
                files.add(self._owned_file(entry))
        parents = {parent for entry in files for parent in entry.parents}
        if not directories <= parents:
            raise ValueError(f"Output migration would remove an unowned directory: {path}")
        return files

    def _obstructions(self, path: Path) -> set[Path]:
        validate_output_path(path)
        ancestors = path.relative_to(self.root).parents
        for relative in reversed(ancestors):
            parent = self.root / relative
            if parent.exists() and not parent.is_dir():
                return {self._owned_file(parent)}
        return self._directory_files(path) if path.is_dir() else set()

    def requires_rebuild(self, path: Path) -> bool:
        if not self._obstructions(path):
            return False
        self._targets.add(path)
        return True

    def removals(self) -> list[Path]:
        paths = {entry for target in self._targets for entry in self._obstructions(target)}
        return sorted(paths)
