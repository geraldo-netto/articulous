"""Isolated Linux XPath compiler worker; native pointers never cross its boundary."""
import argparse
from contextlib import contextmanager
import ctypes
import json
import os
import re
import sys
import tempfile

MAX_EXPRESSION_BYTES = 16 * 1024
MAX_TRACE_BYTES = 128 * 1024
LITERALS = re.compile(r"'[^']*'|\"[^\"]*\"", re.DOTALL)


def require_expression(expression):
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError('XPath must be a nonempty string')
    if '\0' in expression or len(expression.encode()) > MAX_EXPRESSION_BYTES:
        raise ValueError('XPath input capacity or NUL boundary exceeded')


def bind(library, name, arguments, result):
    function = getattr(library, name)
    function.argtypes, function.restype = arguments, result


def libraries():
    xml, libc = ctypes.CDLL('libxml2.so.2'), ctypes.CDLL(None, use_errno=True)
    pointer = ctypes.c_void_p
    bind(xml, 'xmlXPathCompile', [ctypes.c_char_p], pointer)
    bind(xml, 'xmlXPathFreeCompExpr', [pointer], None)
    bind(xml, 'xmlXPathDebugDumpCompExpr', [pointer, pointer, ctypes.c_int], None)
    bind(libc, 'fdopen', [ctypes.c_int, ctypes.c_char_p], pointer)
    bind(libc, 'fflush', [pointer], ctypes.c_int)
    bind(libc, 'fclose', [pointer], ctypes.c_int)
    return xml, libc


@contextmanager
def compiled(xml, expression):
    pointer = xml.xmlXPathCompile(expression.encode())
    if not pointer:
        raise ValueError('Invalid XPath 1.0 expression')
    try:
        yield pointer
    finally:
        xml.xmlXPathFreeCompExpr(pointer)


@contextmanager
def stream(libc, descriptor):
    duplicate = os.dup(descriptor)
    handle = libc.fdopen(duplicate, b'w')
    if not handle:
        os.close(duplicate)
        raise OSError(ctypes.get_errno(), 'Cannot admit native XPath trace stream')
    try:
        yield handle
    finally:
        if libc.fclose(handle) != 0:
            raise OSError(ctypes.get_errno(), 'Cannot settle native XPath trace stream')


def trace(xml, libc, pointer):
    with tempfile.TemporaryFile() as output:
        with stream(libc, output.fileno()) as handle:
            xml.xmlXPathDebugDumpCompExpr(handle, pointer, 0)
            if libc.fflush(handle) != 0:
                raise OSError(ctypes.get_errno(), 'Cannot flush native XPath trace')
        output.seek(0)
        payload = output.read(MAX_TRACE_BYTES + 1)
        if len(payload) > MAX_TRACE_BYTES:
            raise ValueError('Native XPath trace capacity exceeded')
        return payload.decode()


def compile_trace(expression):
    require_expression(expression)
    xml, libc = libraries()
    with compiled(xml, expression):
        pass
    projected = LITERALS.sub("'literal'", expression)
    with compiled(xml, projected) as pointer:
        result = trace(xml, libc, pointer)
    version = ctypes.c_char_p.in_dll(xml, 'xmlParserVersion').value
    if version is None:
        raise ValueError('Missing native XPath compiler version')
    return {'version': version.decode(), 'trace': result}


def main(argv=None):
    if sys.platform != 'linux':
        raise NotImplementedError('Native XPath measurement currently requires Linux')
    import resource
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('expression')
    args = parser.parse_args(argv)
    require_expression(args.expression)
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_TRACE_BYTES, MAX_TRACE_BYTES))
    print(json.dumps(compile_trace(args.expression)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
