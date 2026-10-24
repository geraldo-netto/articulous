"""REVIEW-020: contained native trace; outer session owns every faulty descendant."""
import json
import ctypes
import os
from pathlib import Path
import signal
import sys
import threading
import time

from articulous.backends.recovery import process_state
from articulous.engines import SaxonCEngine
from articulous.transform_contracts import TransformFailure


def interrupt_when_ready(marker, stop):
    while not marker.exists() and not stop.is_set():
        stop.wait(.005)
    if not stop.is_set():
        os.kill(os.getpid(), signal.SIGINT)


def transform(engine, stylesheet, output, mode, marker):
    stop = threading.Event()
    thread = threading.Thread(target=interrupt_when_ready, args=(marker, stop))
    if mode == 'cancel':
        thread.start()
    try:
        engine.run(b'<x/>', stylesheet, output)
    except (TransformFailure, KeyboardInterrupt):
        pass
    finally:
        stop.set()
        if mode == 'cancel':
            thread.join()


def descendant_alive(marker):
    identity = json.loads(marker.read_text())
    state = process_state(identity['pid'])
    if state is None:
        return False
    return state[0].started == identity['start'] and state[1] != 'Z'


def observe(root, mode, source, stdio):
    marker = root / 'child.json'
    os.environ.update(ARTICULOUS_SAXON_MARKER=str(marker), ARTICULOUS_SAXON_MODE=mode,
                      ARTICULOUS_SAXON_STDIO=stdio)
    binary = root / 'Transform'
    binary.write_text('#!' + sys.executable + '\n' + source)
    binary.chmod(0o700)
    stylesheet = root / 'style.xsl'
    stylesheet.write_text('<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0"><xsl:template match="/"><out/></xsl:template></xsl:stylesheet>')
    output = root / 'out.xml'
    output.write_bytes(b'previous')
    transform(SaxonCEngine(binary), stylesheet, output, mode, marker)
    alive = descendant_alive(marker)
    before = output.read_bytes()
    if alive:
        marker.with_suffix('.release').touch()
        while not marker.with_suffix('.done').exists():
            time.sleep(.005)
    return {'alive': alive, 'before': before.decode(), 'after': output.read_text(),
            'late_read': marker.with_suffix('.read').exists()}


def reap_descendants():
    while True:
        try:
            os.waitpid(-1, 0)
        except ChildProcessError:
            return


if __name__ == '__main__':
    assert ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0
    signal.signal(signal.SIGINT, signal.default_int_handler)
    result = observe(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]).read_text(), sys.argv[4])
    reap_descendants()
    print(json.dumps(result))
