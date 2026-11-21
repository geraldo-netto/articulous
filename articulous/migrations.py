"""Plan removal of owned files that obstruct replacement output routes."""
import stat
from pathlib import Path

from .filesystem import validate_output_path, validate_regular_file


class OutputMigrations:
    def __init__(self, root: Path, previous: dict, retained: dict):
        self.root = root.resolve()
        self.previous = previous
        self.selected = previous.keys() - retained.keys() if retained else previous.keys()
        self._parents = set()
        self._targets: set[Path] = set()

    def finish_planning(self):
        """Drop admission and obstruction state after the last preflight mutation."""
        self.previous = {}
        self.selected = self.previous.keys()
        self._parents.clear()
        self._targets.clear()

    def admit_path(self, path):
        if path.is_symlink():
            raise ValueError(f"Generated output path contains a symlink: {path}")
        newly_checked = []
        for parent in path.parents:
            if parent in self._parents:
                break
            if parent.is_symlink():
                raise ValueError(f"Generated output path contains a symlink: {parent}")
            newly_checked.append(parent)
        self._parents.update(newly_checked)

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
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            return set()
        except NotADirectoryError:
            return self._obstructing_parent(path)
        return self._directory_files(path) if stat.S_ISDIR(mode) else set()

    def _obstructing_parent(self, path):
        ancestors = path.relative_to(self.root).parents
        for relative in reversed(ancestors):
            parent = self.root / relative
            if parent.exists() and not parent.is_dir():
                return {self._owned_file(parent)}
        return set()

    def requires_rebuild(self, path: Path) -> bool:
        validate_output_path(path)
        return self.admitted_requires_rebuild(path)

    def admitted_requires_rebuild(self, path):
        if not self._obstructions(path):
            return False
        self._targets.add(path)
        return True

    def removals(self) -> list[Path]:
        paths = set()
        for target in self._targets:
            validate_output_path(target)
            paths.update(self._obstructions(target))
        return sorted(paths)
