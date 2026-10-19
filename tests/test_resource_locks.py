"""BUILD-007: shared build orchestration and native lock adapters."""

import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import pytest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class BuildLockTests(unittest.TestCase):
    def test_build007_build_has_no_native_lock_dependencies(self):
        tree = ast.parse((ROOT / "articulous/resource_locks.py").read_text())
        imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        self.assertNotIn("fcntl", imports)
        self.assertFalse(
            any(
                isinstance(node, ast.Attribute) and node.attr == "flock"
                for node in ast.walk(tree)
            )
        )

    def test_build007_shared_interface_imports_without_native_modules(self):
        script = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'fcntl':
        raise AssertionError('Native module loaded by shared interface')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from articulous.resource_locks import resource_lock
"""
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_build007_native_contention_release_and_exception_release(self):
        from articulous.resource_locks import resource_lock

        script = """
from pathlib import Path
import sys
from articulous.resource_locks import resource_lock
try:
    with resource_lock(Path(sys.argv[1]) / 'resource.lock'):
        print('acquired')
except RuntimeError as error:
    print(error)
    sys.exit(3)
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def contender():
                return subprocess.run(
                    [sys.executable, "-c", script, str(root)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )

            for exceptional in (False, True):
                try:
                    with resource_lock(root / "resource.lock"):
                        with self.assertRaisesRegex(
                            RuntimeError, "Resource lock is held"
                        ):
                            with resource_lock(root / "resource.lock"):
                                self.fail("A second descriptor acquired the held lock")
                        blocked = contender()
                        self.assertEqual(3, blocked.returncode, blocked.stderr)
                        self.assertIn("Resource lock is held", blocked.stdout)
                        if exceptional:
                            raise LookupError("body failure")
                except LookupError:
                    pass
                acquired = contender()
                self.assertEqual(0, acquired.returncode, acquired.stderr)
                self.assertEqual("acquired", acquired.stdout.strip())

    def test_build007_capabilities_do_not_claim_foreign_native_validation(self):
        from articulous.backends import locking

        self.assertTrue(locking.capability().available)
        self.assertEqual(
            sys.platform.startswith("linux"), locking.capability().validated
        )
        with (
            patch.object(locking.os, "name", "nt"),
            patch.object(locking.sys, "platform", "win32"),
        ):
            status = locking.capability()
            self.assertFalse(status.available)
            self.assertFalse(status.validated)
            with self.assertRaisesRegex(RuntimeError, "Unix"):
                locking.native_backend()
        with patch.object(locking.sys, "platform", "darwin"):
            self.assertTrue(locking.capability().available)
            self.assertFalse(locking.capability().validated)
            self.assertIn("unvalidated", locking.capability().detail)

    def test_build007_invalid_native_paths_fail_without_fallback(self):
        from articulous.resource_locks import resource_lock

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            file = root / "file"
            file.touch()
            for invalid in (file,):
                with self.subTest(invalid=invalid), self.assertRaises(OSError):
                    with resource_lock(invalid / "resource.lock"):
                        self.fail("Invalid lock path accepted")


def test_arch009_injected_lock_closes_on_body_failure(tmp_path):
    from contextlib import contextmanager
    from articulous.resource_locks import resource_lock
    import pytest

    events = []

    @contextmanager
    def backend(path):
        events.append("acquired")
        try:
            yield
        finally:
            events.append("released")

    with pytest.raises(FileExistsError, match="body"):
        with resource_lock(tmp_path / "resource.lock", backend=backend):
            raise FileExistsError("body failure")
    assert events == ["acquired", "released"]


def test_arch009_site_snapshot_lock_covers_all_build_entrypoints(site_root, seo_config):
    from articulous.publication import lock_site, build_site
    from articulous.pipeline import run_build
    import pytest

    cli, config = seo_config
    with lock_site(cli, config, site_root):
        with pytest.raises(FileExistsError):
            build_site(cli, config, site_root)
        with pytest.raises(FileExistsError):
            run_build(cli, config, site_root)
    build_site(cli, config, site_root)


@pytest.mark.parametrize('invalid', [None, 0, 1.5, '', [], {}])
def test_build007_invalid_lock_path_types_fail_before_native_access(invalid):
    from articulous.resource_locks import resource_lock
    with pytest.raises(TypeError):
        with resource_lock(invalid):
            pytest.fail('invalid path accepted')
