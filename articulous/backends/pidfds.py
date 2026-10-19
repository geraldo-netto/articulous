"""Linux libc pidfd calls; descriptors bind signals to one process generation."""
import ctypes
from functools import lru_cache
import signal
import sys


@lru_cache(maxsize=1)
def native_library():
    if sys.platform != 'linux':
        raise NotImplementedError('Native pidfds are validated only on Linux/libc')
    library = ctypes.CDLL(None, use_errno=True)
    try:
        library.pidfd_open.argtypes = (ctypes.c_int, ctypes.c_uint)
        library.pidfd_open.restype = ctypes.c_int
        library.pidfd_send_signal.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint)
        library.pidfd_send_signal.restype = ctypes.c_int
    except AttributeError as error:
        raise NotImplementedError('Native pidfd libc entry points are unavailable') from error
    return library


def native_integer(value, minimum):
    if type(value) is not int or not minimum <= value <= 2**31 - 1:
        raise ValueError('Native process identifier/descriptor is outside the C int domain')
    return value


def checked_result(result):
    if result == -1:
        error = ctypes.get_errno()
        raise OSError(error, 'Native pidfd operation failed')
    return result


def open_pidfd(pid):
    return checked_result(native_library().pidfd_open(native_integer(pid, 1), 0))


def send_signal(descriptor, number):
    native_integer(descriptor, 0)
    if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number < signal.NSIG:
        raise ValueError('Invalid native signal number')
    checked_result(native_library().pidfd_send_signal(descriptor, number, None, 0))
