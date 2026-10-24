"""Private native input copies stay owned until process-tree settlement."""
from contextlib import contextmanager
from pathlib import Path
import tempfile

from .backends.processes import defer_workspace_cleanup
from .filesystem import TempWorkspace
from .process_contracts import NativeCleanupError
from .source_files import cleanup_workspace, workspace_identity


def _allocate_inputs():
    directory = Path(tempfile.mkdtemp(prefix='articulous-native-input-'))
    try:
        return directory, workspace_identity(directory)
    except BaseException as error:
        raise RuntimeError(f'Native input workspace needs inspection: {directory}') from error


@contextmanager
def native_workspace():
    directory, identity = _allocate_inputs()
    deferred = False
    try:
        yield TempWorkspace(directory)
    except NativeCleanupError as error:
        deferred = True
        try:
            defer_workspace_cleanup(error.token, directory, identity)
        except BaseException as transfer_error:
            error.add_note(f'Native input workspace requires manual recovery: {directory}')
            raise error from transfer_error
        raise
    finally:
        if not deferred:
            cleanup_workspace(directory, identity)
