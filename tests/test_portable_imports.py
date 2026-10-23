"""ARCH-009/BUILD-007/LIFE-002: shared boundaries avoid eager native lock imports."""
import subprocess
import sys


def test_arch009_package_and_publication_capabilities_import_without_native_modules():
    script = '''
import builtins, subprocess
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'fcntl':
        raise AssertionError('Native module loaded by shared interface')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from articulous.resource_locks import resource_lock
from articulous.extensions import BuildComposition
from articulous.catalogue import PublicationCatalogue
from articulous.backends import publication_capabilities
from articulous.browser_process import run_browser
assert publication_capabilities().platform
assert callable(run_browser)
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
