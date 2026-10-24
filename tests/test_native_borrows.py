"""REVIEW-020: inherited descriptor admission and retained private input copies."""
from pathlib import Path
import os
import sys
from unittest.mock import Mock

import lxml.etree as etree
import pytest
import subprocess

from articulous.backends import processes
from articulous.backends.saxon import run_transform_command
from articulous.engines import SaxonCEngine
from articulous import engines, native_workspace
from articulous.process_contracts import NativeCleanupError, RecoveryToken
from articulous.process_contracts import SessionOptions
from articulous.transform_contracts import TransformFailure
from articulous.source_files import cleanup_workspace, workspace_identity
from test_engines import MINIMAL_XSLT


@pytest.mark.parametrize('value', [None, [], [1], (True,), (-1,), (2**31,), (None,), ('1',), ([],)])
def test_review020_invalid_descriptor_admission(value):
    with pytest.raises(ValueError):
        with processes.open_session(['unused'], pass_fds=value):
            pytest.fail('invalid descriptor admitted')


def test_review020_descriptor_handoff_and_rejection(tmp_path):
    path = tmp_path / 'data'
    with path.open('w+b') as stream:
        descriptor = stream.fileno()
        result = run_transform_command([sys.executable, '-c', 'import os,sys;os.write(int(sys.argv[1]),b"owned")', str(descriptor)],
                           pass_fds=(descriptor,))
        assert result.returncode == 0
        stream.seek(0)
        assert stream.read() == b'owned'
        with pytest.raises(ValueError, match='unique tuple'):
            with processes.open_session(['unused'], pass_fds=(descriptor, descriptor)):
                pytest.fail('duplicate descriptor admitted')
    with pytest.raises(OSError):
        with processes.open_session(['unused'], pass_fds=(descriptor,)):
            pytest.fail('closed descriptor admitted')


def command_inputs(command):
    return {prefix: Path(next(value[len(prefix):] for value in command if value.startswith(prefix)))
            for prefix in ('-s:', '-xsl:', '-config:')}


@pytest.mark.parametrize('source_kind', ['bytes', 'path'])
@pytest.mark.parametrize('storage_fault', [False, True])
def test_review020_failed_fence_retains_copies_until_recovery(tmp_path, monkeypatch, source_kind, storage_fault):
    binary = tmp_path / 'Transform'
    binary.write_text('#!' + sys.executable + '\nimport os,sys\nfd=int(next(a[11:] for a in sys.argv if a.startswith("-o:/dev/fd/")))\nos.write(fd,b"new")\n')
    binary.chmod(0o700)
    stylesheet = tmp_path / 'style.xsl'
    stylesheet.write_text(MINIMAL_XSLT)
    original = tmp_path / 'original.xml'
    original.write_bytes(b'<x/>')
    source = original if source_kind == 'path' else b'<x/>'
    output = tmp_path / 'out.xml'
    output.write_bytes(b'previous')
    observed = []
    native = engines.run_transform_command

    def record(command, **options):
        observed.append(command_inputs(command))
        return native(command, **options)

    monkeypatch.setattr(engines, 'run_transform_command', record)
    with monkeypatch.context() as fault:
        fault.setattr(processes, 'await_group_exit', Mock(side_effect=TimeoutError('missing fence')))
        if storage_fault:
            from articulous.backends import recovery
            persist = recovery.persist_reservation

            def fail_borrowed_storage(reservation):
                if reservation.borrowed:
                    raise OSError('journal storage unavailable')
                return persist(reservation)

            fault.setattr(recovery, 'persist_reservation', fail_borrowed_storage)
        with pytest.raises(NativeCleanupError) as failure:
            SaxonCEngine(binary).run(source, stylesheet, output)
    reservation = processes._RETAINED[failure.value.token]
    try:
        assert len(reservation.borrowed) == 2
        assert all(path.is_file() for path in observed[0].values())
        original.write_bytes(b'changed caller input')
        assert etree.parse(str(observed[0]['-s:'])).getroot().tag == 'x'
        assert output.read_bytes() == b'previous'
    finally:
        processes.recover_session(failure.value.token)
    assert all(not path.exists() for path in observed[0].values())


def test_review020_workspace_admission_failure_preserves_unknown_identity(tmp_path, monkeypatch):
    directory = tmp_path / 'inputs'
    directory.mkdir()
    monkeypatch.setattr(native_workspace.tempfile, 'mkdtemp', Mock(return_value=str(directory)))
    monkeypatch.setattr(native_workspace, 'workspace_identity', Mock(side_effect=OSError('identity unavailable')))
    with pytest.raises(RuntimeError, match='needs inspection'):
        with native_workspace.native_workspace():
            pytest.fail('unidentified workspace admitted')
    assert directory.is_dir()


def test_review020_failed_recovery_transfer_preserves_inputs(monkeypatch):
    retained = None
    monkeypatch.setattr(native_workspace, 'defer_workspace_cleanup', Mock(side_effect=RuntimeError('storage failure')))
    try:
        with pytest.raises(NativeCleanupError) as failure:
            with native_workspace.native_workspace() as workspace:
                retained = workspace._directory
                assert retained is not None
                with workspace.named_file('wb') as stream:
                    stream.write(b'borrowed')
                raise NativeCleanupError(RecoveryToken(1, 'controlled'))
        assert retained is not None and retained.is_dir()
        assert any('manual recovery' in note for note in failure.value.__notes__)
    finally:
        if retained is not None:
            cleanup_workspace(retained, workspace_identity(retained))


@pytest.mark.parametrize('base', [None, 'https://example.test/input.xml'])
def test_review020_path_copy_preserves_effective_base(tmp_path, monkeypatch, base):
    source = tmp_path / 'source.xml'
    source.write_bytes(b'<x/>')
    stylesheet = tmp_path / 'style.xsl'
    stylesheet.write_text(MINIMAL_XSLT)
    observed = []

    def inspect(command, **options):
        copied = command_inputs(command)['-s:']
        assert copied != source
        observed.append(etree.parse(str(copied)).getroot().base)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(engines, 'run_transform_command', inspect)
    SaxonCEngine(tmp_path / 'Transform').run(source, stylesheet, tmp_path / 'out.xml', xml_base_uri=base)
    assert observed == [base or source.as_uri()]


@pytest.mark.parametrize('value', [None, 0, 1, 'true', [], {}])
def test_review020_exit_sealing_requires_boolean(value):
    with pytest.raises(ValueError, match='boolean'):
        SessionOptions(seal_on_exit=value)


@pytest.mark.parametrize('status', [0, 7])
def test_review020_native_diagnostics_survive_supervision(tmp_path, capsys, status):
    binary = tmp_path / 'Transform'
    binary.write_text('#!' + sys.executable + '\nimport sys\nprint("native output")\nprint("native error",file=sys.stderr)\nraise SystemExit(' + str(status) + ')\n')
    binary.chmod(0o700)
    stylesheet = tmp_path / 'style.xsl'
    stylesheet.write_text(MINIMAL_XSLT)
    output = tmp_path / 'out.xml'
    engine = SaxonCEngine(binary)
    if status:
        with pytest.raises(TransformFailure):
            engine.run(b'<x/>', stylesheet, output)
    else:
        engine.run(b'<x/>', stylesheet, output)
    captured = capsys.readouterr()
    assert 'native output' in captured.out
    assert 'native error' in captured.err


def test_review020_exited_leader_drains_buffer_before_releasing_lease():
    options = SessionOptions(tooling=False, seal_on_exit=True)
    with processes.open_session([sys.executable, '-c', 'print("buffered before exit")'], options=options) as session:
        assert isinstance(session, processes.LinuxSession)
        evidence = os.waitid(os.P_PID, session._process.pid, os.WEXITED | os.WNOWAIT)
        assert evidence is not None
        assert session.communicate() == ('buffered before exit\n', '')
        assert session._quiet
        assert os.waitid(os.P_PID, session._process.pid, os.WEXITED | os.WNOWAIT) is not None
    assert session.settled
