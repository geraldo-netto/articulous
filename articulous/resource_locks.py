"""Platform-independent resource exclusion using one native lock primitive."""
from contextlib import ExitStack, contextmanager
from pathlib import Path

from .lock_contracts import LockBackend


@contextmanager
def resource_lock(path: Path, backend: LockBackend | None = None):
    if not isinstance(path, Path):
        raise TypeError('Resource lock requires a Path')
    if backend is None:
        from .backends.locking import native_backend
        backend = native_backend()
    with ExitStack() as cleanup:
        try:
            cleanup.enter_context(backend(path))
        except FileExistsError as error:
            raise RuntimeError(f'Resource lock is held: {path}') from error
        yield
