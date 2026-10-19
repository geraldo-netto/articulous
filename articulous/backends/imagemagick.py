"""Explicit ImageMagick/optipng process adapter; never installs tools."""
from pathlib import Path
import tempfile

from contextlib import contextmanager
from ..source_files import cleanup_workspace, workspace_identity
from ..process_contracts import NativeCleanupError
from .processes import defer_workspace_cleanup
from ..browser_process import run_owned
from ..image_contracts import KINDS, validate_options


class ImageMagick:
    def dimensions(self, path: Path) -> tuple[int, int]:
        out = run_owned(['identify', '-format', '%w %h', str(path) + '[0]']).stdout.split()
        return int(out[0]), int(out[1])

    def shrink(self, path: Path, target: Path, largest: int, quality: int) -> None:
        validate_options(largest, quality)
        kind = KINDS[path.suffix.lower()]
        resize = f'{largest}x{largest}>'
        if kind == 'jpeg':
            run_owned(['convert', str(path), '-auto-orient', '-resize', resize, '-strip',
                            '-interlace', 'Plane', '-quality', str(quality), str(target)])
        else:
            run_owned(['convert', str(path), '-resize', resize, '-strip', str(target)])
            run_owned(['optipng', '-quiet', '-o2', str(target)])

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
                raise RuntimeError(f'Image workspace requires manual recovery: {workspace}') from transfer_error
            raise
        finally:
            if not deferred:
                cleanup_workspace(workspace, identity)
