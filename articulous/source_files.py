"""Replace one source file atomically after a writer has completed successfully."""
from pathlib import Path
import shutil
import tempfile
import sys


def workspace_identity(path):
    metadata = path.lstat()
    return metadata.st_dev, metadata.st_ino, metadata.st_mode


def require_workspace(path, identity):
    if workspace_identity(path) != identity:
        raise ValueError(f'Source workspace identity changed; retained for inspection: {path}')


def cleanup_workspace(path, identity):
    try:
        require_workspace(path, identity)
        shutil.rmtree(path)
    except (OSError, ValueError) as error:
        print(f'File workspace cleanup failed; remove manually: {path}: {error}', file=sys.stderr)


def replace_file(path, writer):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.' + path.name + '-', dir=path.parent))
    identity = workspace_identity(temporary)
    try:
        staged = temporary / path.name
        writer(staged)
        require_workspace(temporary, identity)
        if path.exists():
            staged.chmod(path.stat().st_mode)
        staged.replace(path)
    finally:
        cleanup_workspace(temporary, identity)
