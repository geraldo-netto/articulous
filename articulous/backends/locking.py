"""Lazy native selection for independent resource locks."""
import os
import sys

from ..lock_contracts import LockCapability


def capability() -> LockCapability:
    if os.name == 'posix':
        validated = sys.platform.startswith('linux')
        detail = ('Native locking validated on Linux.' if validated else
                  'Native locking unvalidated on this Unix platform; platform support is not established.')
        return LockCapability('posix-flock', True, validated, detail)
    return LockCapability(None, False, False,
                          'Resource locking requires Unix/fcntl; no native adapter is available. '
                          'Native support is unavailable.')


def native_backend():
    status = capability()
    if not status.available:
        raise RuntimeError(status.detail)
    from ..filesystem import lock_file
    return lock_file
