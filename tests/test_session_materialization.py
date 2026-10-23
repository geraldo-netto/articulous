"""PERF-004: explicit helper admission and linear checkpoint diagnostics."""
import os
import random
import sys
import time
from pathlib import Path
from typing import SupportsIndex, cast

import pytest

from articulous.backends import processes
from articulous.backends.imagemagick import ImageMagick
from articulous.browser_process import run_browser_suite
from articulous.process_contracts import SessionOptions


def test_perf004_converter_does_not_materialize_browser_helpers(tmp_path, monkeypatch):
    executable = tmp_path / 'identify'
    executable.write_text('#!' + sys.executable + '\nprint("123 45")\n')
    executable.chmod(0o700)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    sizes = []
    environment = processes.session_environment

    def measured_environment(*args, **kwargs):
        result = environment(*args, **kwargs)
        sizes.extend(path.stat().st_size for path in args[0].rglob('*.mjs'))
        return result

    monkeypatch.setattr(processes, 'session_environment', measured_environment)
    started = time.perf_counter()
    assert ImageMagick().dimensions(tmp_path / 'input.png') == (123, 45)
    print(f'PERF-004 converter files={len(sizes)} bytes={sum(sizes)} seconds={time.perf_counter() - started:.6f}')
    assert sizes == [], 'PERF-004: converters must not admit browser tooling resources'


@pytest.mark.parametrize('chunk_size', [262_144, 1_048_576])
def test_perf004_checkpoint_output_copy_scaling(monkeypatch, tmp_path, chunk_size):
    copied = []
    native_bytes = bytes

    def measured_bytes(source):
        copied.append(len(source))
        return native_bytes(source)

    monkeypatch.setattr(processes, 'bytes', measured_bytes, raising=False)
    code = ('import os,time\nfrom pathlib import Path\nfor index in range(4):\n'
            f' os.write(1,b"x"*{chunk_size})\n'
            ' os.write(2,f"[BUILD-013] settled {index}: case\\n".encode())\n'
            f' while not Path({str(tmp_path / "ack")!r}+str(index)).exists(): time.sleep(.001)\n')
    progress = []

    def report(message):
        progress.append(message)
        if message.startswith('[BUILD-013] settled '):
            (tmp_path / ('ack' + message.split()[2].removesuffix(':'))).touch()

    started = time.perf_counter()
    result = run_browser_suite([sys.executable, '-c', code], checkpoint=.005, report=report)
    total = len(result.stdout.encode()) + len(result.stderr.encode())
    assert result.stdout == 'x' * (4 * chunk_size)
    assert result.stderr.count('settled') == 4
    assert len(progress) >= 4
    print(f'PERF-004 output={total} copied={sum(copied)} checkpoints={len(progress)} seconds={time.perf_counter() - started:.6f}')
    assert sum(copied) <= 3 * total, 'PERF-004: checkpoints must not repeatedly copy accumulated output'


def test_perf004_incremental_lines_preserve_complete_output_and_borrows():
    options = SessionOptions(tooling=False, checkpoint_output=True)
    with processes.open_session([sys.executable, '-c', 'pass'], options=options) as session:
        assert isinstance(session, processes.LinuxSession)
        stderr = session._buffers['stderr']
        stderr.extend(b'[BUILD-013] settl')
        assert session._timeout(.01).stderr == b''
        stderr.extend('ed 1: caf'.encode())
        stderr.extend('é\npartial'.encode())
        first = session._timeout(.01)
        assert first.output is None
        assert first.stderr == '[BUILD-013] settled 1: café\n'.encode()
        assert session._timeout(.01).stderr == b''
        stderr.extend(b'x' * 100_000 + b'\n')
        assert session._timeout(.01).stderr == b'partial' + b'x' * 100_000 + b'\n'
        assert first.stderr == '[BUILD-013] settled 1: café\n'.encode()
        assert session.communicate()[1] == stderr.decode()
        session.stop()
        assert session.communicate()[1] == stderr.decode()


def test_perf004_unterminated_line_scanning_is_linear():
    scans = []

    class MeasuredBuffer(bytearray):
        def rfind(self, token, start: SupportsIndex | None = None, end: SupportsIndex | None = None):
            first, stop, _ = slice(start, end).indices(len(self))
            scans.append(max(0, stop - first))
            return super().rfind(token, start, end)

    with processes.open_session([sys.executable, '-c', 'pass']) as session:
        assert isinstance(session, processes.LinuxSession)
        session._buffers['stderr'] = MeasuredBuffer()
        for _ in range(16):
            session._buffers['stderr'].extend(b'x' * 1024)
            assert session._checkpoint_stderr() == b''
        assert sum(scans) == 16 * 1024
        assert len(session.communicate()[1]) == 16 * 1024
        buffer = session._buffers['stderr']
        for start, end in ((None, None), (0, 4), (-4, None), (4, 2), (0, -1)):
            assert buffer.rfind(b'x', start, end) == bytearray(buffer).rfind(b'x', start, end), 'QA-001: preserve bytearray bounds'


def test_perf004_failed_snapshot_keeps_cursor_and_releases_borrow(monkeypatch):
    def exhausted_copy(_):
        raise MemoryError('snapshot capacity unavailable')

    options = SessionOptions(tooling=False, checkpoint_output=True)
    with processes.open_session([sys.executable, '-c', 'pass'], options=options) as session:
        assert isinstance(session, processes.LinuxSession)
        session._buffers['stderr'].extend(b'first\n')
        with monkeypatch.context() as fault:
            fault.setattr(processes, 'bytes', exhausted_copy, raising=False)
            with pytest.raises(MemoryError) as failure:
                session._timeout(.01)
        assert isinstance(failure.value, MemoryError)
        session._buffers['stderr'].extend(b'next\n')
        assert session._timeout(.01).stderr == b'first\nnext\n'


def test_perf004_explicit_deadline_preserves_full_timeout_snapshots():
    with processes.open_session([sys.executable, '-c', 'pass']) as session:
        assert isinstance(session, processes.LinuxSession)
        session._buffers['stdout'].extend(b'output')
        session._buffers['stderr'].extend(b'diagnostics')
        assert session._timeout(.01).output == b'output'
        assert session._timeout(.01).stderr == b'diagnostics'
        assert session.communicate() == ('output', 'diagnostics')


@pytest.mark.parametrize('field', ['tooling', 'checkpoint_output'])
@pytest.mark.parametrize('value', [None, False, True, 0, 1, -1, 'false', [], {}])
def test_perf004_session_option_boundaries(field, value):
    if type(value) is bool:
        assert getattr(SessionOptions(**{field: value}), field) is value
    else:
        with pytest.raises(ValueError, match='boolean'):
            SessionOptions(**{field: value})


@pytest.mark.parametrize('seed', [2026, 0xC0FFEE])
def test_perf004_bounded_option_fuzz(seed):
    randomizer = random.Random(seed)
    for _ in range(32):
        number = randomizer.randrange(-2**64, 2**64)
        value = randomizer.choice([None, number, str(number), [number], {'flag': number}, float('nan')])
        field = randomizer.choice(['tooling', 'checkpoint_output'])
        with pytest.raises(ValueError, match='boolean'):
            SessionOptions(**{field: cast(bool, value)})


def test_perf004_invalid_options_rejected_before_resource_admission(monkeypatch):
    def forbidden_admission(**_):
        pytest.fail('resource admitted')

    monkeypatch.setattr(processes.tempfile, 'mkdtemp', forbidden_admission)
    with pytest.raises(ValueError, match='SessionOptions'):
        with processes.open_session(['unused'], options=cast(SessionOptions, None)):
            pytest.fail('invalid options accepted')


def test_perf004_disabled_tooling_clears_inherited_resource_urls(tmp_path, monkeypatch):
    monkeypatch.setenv('ARTICULOUS_BROWSER_SESSION', 'file:///stale-owner/browser.mjs')
    monkeypatch.setenv('ARTICULOUS_NATIVE_COVERAGE', 'file:///stale-owner/coverage.mjs')
    environment = processes.session_environment(tmp_path, SessionOptions(tooling=False))
    assert 'ARTICULOUS_BROWSER_SESSION' not in environment
    assert 'ARTICULOUS_NATIVE_COVERAGE' not in environment
    assert not (tmp_path / 'tools').exists()
    assert Path(environment['TMPDIR']) == tmp_path
