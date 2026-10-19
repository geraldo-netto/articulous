"""TEST-002: native PID generation handles and libc error/boundary contracts."""
import os
import signal
from unittest.mock import patch
import pytest
from articulous.backends import pidfds


def test_test002_real_pidfd_for_current_process():
    descriptor = pidfds.open_pidfd(os.getpid())
    try:
        pidfds.send_signal(descriptor, 0)
    finally:
        os.close(descriptor)
    with pytest.raises(OSError):
        pidfds.send_signal(descriptor, 0)
    with pytest.raises(ProcessLookupError):
        pidfds.open_pidfd(2**31 - 1)


@pytest.mark.parametrize('value', [None, False, -1, 0, 2**31, '1', 1.5])
def test_test002_invalid_pid_domain(value):
    with pytest.raises(ValueError, match='C int'):
        pidfds.open_pidfd(value)


@pytest.mark.parametrize('value', [None, True, -1, signal.NSIG, 2**100, '1'])
def test_test002_invalid_signal_domain(value):
    with pytest.raises(ValueError, match='signal'):
        pidfds.send_signal(0, value)


def test_test002_unavailable_native_pidfd_capabilities():
    pidfds.native_library.cache_clear()
    with patch.object(pidfds.sys, 'platform', 'darwin'), pytest.raises(NotImplementedError, match='Linux'):
        pidfds.native_library()
    with patch.object(pidfds.ctypes, 'CDLL', return_value=object()), pytest.raises(NotImplementedError, match='unavailable'):
        pidfds.native_library()
    pidfds.native_library.cache_clear()
