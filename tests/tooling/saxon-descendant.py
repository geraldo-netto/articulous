"""REVIEW-020: deliberately faulty tool, never article/post code."""
import json
import os
from pathlib import Path
import signal
import sys
import time

marker = Path(os.environ['ARTICULOUS_SAXON_MARKER'])
descriptor = int(next(value[11:] for value in sys.argv if value.startswith('-o:/dev/fd/')))
os.write(descriptor, b'initial')
child = os.fork()
if child == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if os.environ['ARTICULOUS_SAXON_STDIO'] == 'close':
        for descriptor_number in (0, 1, 2):
            os.close(descriptor_number)
    fields = Path('/proc/self/stat').read_text().rpartition(') ')[2].split()
    ready = marker.with_suffix('.ready')
    ready.write_text(json.dumps({'pid': os.getpid(), 'start': int(fields[19])}))
    ready.replace(marker)
    while not marker.with_suffix('.release').exists():
        time.sleep(.005)
    source = Path(next(value[3:] for value in sys.argv if value.startswith('-s:')))
    try:
        content = source.read_bytes()
    except FileNotFoundError:
        content = b'missing borrowed input'
    marker.with_suffix('.read').write_bytes(content)
    os.write(descriptor, b'-late')
    marker.with_suffix('.done').touch()
    os._exit(0)
while not marker.exists():
    time.sleep(.005)
if os.environ['ARTICULOUS_SAXON_MODE'] == 'cancel':
    while True:
        time.sleep(1)
if os.environ['ARTICULOUS_SAXON_MODE'] == 'failure':
    raise SystemExit(7)
