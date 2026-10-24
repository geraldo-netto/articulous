"""CC-005: native compiler boundaries, admission and exact cleanup controls."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import resource
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from articulous.backends import xpath as worker
from articulous import complexity_xpath as adapter
from articulous.complexity_xslt_contracts import XPathDecisions


@pytest.mark.parametrize('value', [None, 1, '', ' \t', 'a\0b', 'x' * (worker.MAX_EXPRESSION_BYTES + 1)])
def test_cc005_invalid_expression_admission(value):
    with pytest.raises(ValueError):
        worker.require_expression(value)


def test_cc005_expression_capacity_boundary():
    worker.require_expression('x' * worker.MAX_EXPRESSION_BYTES)
    worker.require_expression('é' * (worker.MAX_EXPRESSION_BYTES // 2))


def test_cc005_compiled_pointer_identity_and_failure():
    xml = SimpleNamespace(xmlXPathCompile=Mock(return_value=123), xmlXPathFreeCompExpr=Mock())
    with worker.compiled(xml, 'a') as pointer:
        assert pointer == 123
    xml.xmlXPathFreeCompExpr.assert_called_once_with(123)
    xml.xmlXPathFreeCompExpr.reset_mock()
    with pytest.raises(RuntimeError):
        with worker.compiled(xml, 'a'):
            raise RuntimeError('fault')
    xml.xmlXPathFreeCompExpr.assert_called_once_with(123)
    xml.xmlXPathCompile.return_value = None
    xml.xmlXPathFreeCompExpr.reset_mock()
    with pytest.raises(ValueError, match='Invalid XPath'):
        with worker.compiled(xml, 'bad'):
            pytest.fail('unadmitted pointer')
    xml.xmlXPathFreeCompExpr.assert_not_called()


@pytest.mark.parametrize('fault', ['none', 'admission', 'body', 'close'])
def test_cc005_stream_ownership(fault, monkeypatch):
    closed = []
    monkeypatch.setattr(worker.os, 'dup', lambda _: 77)
    monkeypatch.setattr(worker.os, 'close', closed.append)
    libc = SimpleNamespace(fdopen=Mock(return_value=None if fault == 'admission' else 123),
                           fclose=Mock(return_value=-1 if fault == 'close' else 0))
    if fault == 'none':
        with worker.stream(libc, 1) as handle:
            assert handle == 123
        libc.fclose.assert_called_once_with(123)
    else:
        with pytest.raises((OSError, RuntimeError)):
            with worker.stream(libc, 1):
                if fault == 'body':
                    raise RuntimeError('fault')
        assert libc.fclose.call_count == (0 if fault == 'admission' else 1)
    assert closed == ([77] if fault == 'admission' else [])


@pytest.mark.parametrize('fault', ['flush', 'capacity'])
def test_cc005_trace_failure_closes_native_borrow(fault, monkeypatch):
    xml = SimpleNamespace(xmlXPathDebugDumpCompExpr=lambda handle, *_: os.write(handle, b'x'))
    libc = SimpleNamespace(fflush=Mock(return_value=-1 if fault == 'flush' else 0))
    released = []

    @contextmanager
    def stream(_, descriptor):
        try:
            yield descriptor
        finally:
            released.append(descriptor)

    monkeypatch.setattr(worker, 'stream', stream)
    monkeypatch.setattr(worker, 'MAX_TRACE_BYTES', 0)
    with pytest.raises((OSError, ValueError)):
        worker.trace(xml, libc, 123)
    assert len(released) == 1


@pytest.mark.parametrize('expression', ['(', "'unterminated", 'a[', 'a and', '1 +'])
def test_cc005_native_parser_rejects_invalid_syntax(expression):
    with pytest.raises(ValueError, match='Invalid XPath'):
        worker.compile_trace(expression)


def test_cc005_native_trace_escapes_literal_injection():
    result = worker.compile_trace('contains("line\n  AND\n  PREDICATE", "and or")')
    measured = adapter.decisions(result)
    assert (measured.booleans, measured.predicates) == (0, 0)
    assert 'line' not in result['trace']
    assert adapter.decisions(worker.compile_trace('a[b and c]')).booleans == 1


def test_cc005_missing_native_version(monkeypatch):
    @contextmanager
    def compiled(*_):
        yield 123

    monkeypatch.setattr(worker, 'compiled', compiled)
    monkeypatch.setattr(worker, 'libraries', lambda: ('xml', 'libc'))
    monkeypatch.setattr(worker, 'trace', lambda *_: 'trace')
    monkeypatch.setattr(worker, 'ctypes', SimpleNamespace(c_char_p=SimpleNamespace(
        in_dll=lambda *_: SimpleNamespace(value=None))))
    with pytest.raises(ValueError, match='version'):
        worker.compile_trace('a')


def test_cc005_worker_main_and_native_capability(monkeypatch, capsys):
    limits = []
    monkeypatch.setattr(resource, 'setrlimit', lambda *args: limits.append(args))
    monkeypatch.setattr(worker, 'compile_trace', lambda _: {'version': '20914', 'trace': 'Streaming Expression\n'})
    assert worker.main(['a']) == 0
    assert json.loads(capsys.readouterr().out)['version'] == '20914'
    assert limits == [(resource.RLIMIT_FSIZE, (worker.MAX_TRACE_BYTES, worker.MAX_TRACE_BYTES))]
    monkeypatch.setattr(worker.sys, 'platform', 'win32')
    with pytest.raises(NotImplementedError, match='Linux'):
        worker.main(['a'])


@pytest.mark.parametrize('payload', [None, '', 'other', 'Compiled Expression : 1 elements\n',
    'Compiled Expression : 1 elements\n  UNKNOWN\n', 'Compiled Expression : 1 elements\nno indent\n'])
def test_cc005_unknown_trace_formats(payload):
    with pytest.raises(ValueError):
        adapter.operations(payload)


def test_cc005_trace_capacity_and_header_boundary(monkeypatch):
    monkeypatch.setattr(worker, 'MAX_TRACE_BYTES', len('Streaming Expression\n'))
    assert adapter.operations('Streaming Expression\n') == []
    with pytest.raises(ValueError, match='capacity'):
        adapter.operations('Streaming Expression\n ')


@pytest.mark.parametrize('value', ['', None, 12, 'v2.9'])
def test_cc005_invalid_compiler_provenance(value):
    with pytest.raises(ValueError, match='provenance'):
        adapter.decisions({'version': value, 'trace': 'Streaming Expression\n'})


@pytest.mark.parametrize('value', [-1, True, 65537, '1'])
def test_cc005_invalid_native_counts(value):
    with pytest.raises(ValueError, match='count'):
        XPathDecisions(value, 0, '20914', 'a' * 64)


def test_cc005_immutable_result_contract():
    assert XPathDecisions(65536, 0, '20914', 'a' * 64).booleans == 65536
    with pytest.raises(ValueError, match='provenance'):
        XPathDecisions(0, 0, '', 'a' * 64)


def test_cc005_owned_native_adapter():
    result = adapter.compile_xpath('a[b] or c')
    assert (result.booleans, result.predicates) == (1, 1)


@pytest.mark.parametrize('expression', ['-a', '--a', '-1', '--1'])
def test_cc005_native_unary_expressions_are_not_cli_options(expression):
    result = adapter.compile_xpath(expression)
    assert (result.booleans, result.predicates) == (0, 0)


def test_cc005_adapter_command_boundary(monkeypatch):
    commands = []

    def command(arguments):
        commands.append(arguments)
        return json.dumps({'version': '20914', 'trace': 'Streaming Expression\n'})

    monkeypatch.setattr(adapter, 'command', command)
    assert adapter.compile_xpath('a').booleans == 0
    assert Path(commands[0][1]) == Path(worker.__file__)


def test_cc005_native_descriptor_churn_settles():
    before = set(Path('/proc/self/fd').iterdir())
    for _ in range(32):
        assert adapter.decisions(worker.compile_trace('a[b] and c')).predicates == 1
    assert set(Path('/proc/self/fd').iterdir()) == before


def test_cc005_native_trace_exhaustion_fails_owned_command():
    import subprocess
    expression = ' and '.join(['a'] * 2000)
    with pytest.raises(subprocess.CalledProcessError):
        adapter.compile_xpath(expression)


@pytest.mark.parametrize('fault', ['none', 'original', 'projection', 'trace'])
def test_cc005_bounded_pointer_lifecycle_model(monkeypatch, fault):
    active, events = set(), []
    admissions = iter((1, 2))

    def allocate(_):
        pointer = next(admissions)
        if (fault, pointer) in (('original', 1), ('projection', 2)):
            return None
        active.add(pointer)
        events.append(('allocate', pointer))
        return pointer

    def release(pointer):
        assert pointer in active
        active.remove(pointer)
        events.append(('release', pointer))

    def trace(*args):
        assert active == {2} and args[-1] == 2
        if fault == 'trace':
            raise MemoryError('funding')
        return 'Streaming Expression\n'

    xml = SimpleNamespace(xmlXPathCompile=allocate, xmlXPathFreeCompExpr=release)
    monkeypatch.setattr(worker, 'libraries', lambda: (xml, None))
    monkeypatch.setattr(worker, 'trace', trace)
    monkeypatch.setattr(worker, 'ctypes', SimpleNamespace(c_char_p=SimpleNamespace(
        in_dll=lambda *_: SimpleNamespace(value=b'20914'))))
    if fault == 'none':
        assert worker.compile_trace('a')['version'] == '20914'
    else:
        with pytest.raises((ValueError, MemoryError)):
            worker.compile_trace('a')
    assert not active
    assert events[::2] == [('allocate', pointer) for _, pointer in events[1::2]]
