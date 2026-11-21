"""Explicit ImageMagick/optipng process adapter; never installs tools."""
from pathlib import Path
import os
import re
import tempfile

from contextlib import contextmanager
from ..source_files import cleanup_workspace, workspace_identity
from ..process_contracts import NativeCleanupError
from .processes import defer_workspace_cleanup
from ..browser_process import run_owned
from ..image_contracts import KINDS, validate_options


class ImageMagick:
    @contextmanager
    def _literal_paths(self, *paths):
        with self.workspace() as directory:
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                names = []
                for index, path in enumerate(paths):
                    suffix = path.suffix if re.fullmatch(r'\.[A-Za-z0-9]+', path.suffix) else ''
                    name = f'image-{index}{suffix}'
                    os.symlink(path.absolute(), name, dir_fd=descriptor)
                    names.append(f'/proc/self/fd/{descriptor}/{name}')
                yield (descriptor,), names
            finally:
                os.close(descriptor)

    def dimensions(self, path: Path) -> tuple[int, int]:
        with self._literal_paths(path) as (descriptors, names):
            out = run_owned(['identify', '-format', '%w %h', names[0] + '[0]'],
                            pass_fds=descriptors, tooling=False).stdout.split()
        return int(out[0]), int(out[1])

    def shrink(self, path: Path, target: Path, largest: int, quality: int) -> None:
        validate_options(largest, quality)
        kind = KINDS[path.suffix.lower()]
        resize = f'{largest}x{largest}>'
        with self._literal_paths(path, target) as (descriptors, names):
            source, output = names
            if kind == 'jpeg':
                run_owned(['convert', source, '-auto-orient', '-resize', resize, '-strip',
                           '-interlace', 'Plane', '-quality', str(quality), output], pass_fds=descriptors, tooling=False)
            else:
                run_owned(['convert', source, '-resize', resize, '-strip', output], pass_fds=descriptors, tooling=False)
                run_owned(['optipng', '-quiet', '-o2', str(target.absolute())], tooling=False)

    @contextmanager
    def workspace(self):
        workspace = Path(tempfile.mkdtemp(prefix='articulous-image-'))
        identity = workspace_identity(workspace)
        deferred = False
        try:
            yield workspace
        except NativeCleanupError as error:
            deferred = True
            try:
                defer_workspace_cleanup(error.token, workspace, identity)
            except BaseException as transfer_error:
                error.add_note(f'Image workspace requires manual recovery: {workspace}')
                raise error from transfer_error
            raise
        finally:
            if not deferred:
                cleanup_workspace(workspace, identity)
