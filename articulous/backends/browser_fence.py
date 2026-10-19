"""Linux pidfd fence for a caller's isolated, admission-closed browser process group."""
import os
from pathlib import Path
import select
import signal
import sys
import time
from .pidfds import open_pidfd, send_signal


def process_identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rpartition(') ')[2].split()
    except FileNotFoundError:
        return None
    return int(fields[2]), int(fields[19]), fields[0]


def owned_members(owner):
    for entry in Path('/proc').glob('[0-9]*'):
        pid = int(entry.name)
        if pid in (owner, os.getpid()):
            continue
        identity = process_identity(pid)
        if identity is not None and identity[0] == owner and identity[2] != 'Z':
            yield pid, identity


def admit_member(pid, expected):
    try:
        descriptor = open_pidfd(pid)
    except ProcessLookupError:
        return None
    actual = process_identity(pid)
    if actual is None or actual[:2] != expected[:2]:
        os.close(descriptor)
        return None
    return descriptor


def signal_member(descriptor, number):
    try:
        send_signal(descriptor, number)
    except ProcessLookupError:
        pass


def collect_members(owner, handles, number):
    observed = False
    for pid, identity in owned_members(owner):
        key = pid, identity[1]
        if key in handles:
            ready, _, _ = select.select([handles[key]], [], [], 0)
            if not ready:
                continue
            os.close(handles.pop(key))
        observed = True
        descriptor = admit_member(pid, identity)
        if descriptor is not None:
            handles[key] = descriptor
            signal_member(descriptor, number)
    return observed


def stopped_members(handles):
    for pid, generation in handles:
        identity = process_identity(pid)
        if identity is not None and identity[1] == generation and identity[2] not in ('T', 't', 'Z', 'X'):
            return False
    return True


def freeze_members(owner, handles, deadline):
    while True:
        admitted = collect_members(owner, handles, signal.SIGSTOP)
        if not admitted and stopped_members(handles):
            return
        if time.monotonic() >= deadline:
            raise TimeoutError('Browser process group did not stop admission')
        time.sleep(.001)


def await_members(handles, deadline):
    pending = set(handles.values())
    while pending:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Browser pidfds did not report native exit')
        ready, _, _ = select.select(list(pending), [], [], remaining)
        pending.difference_update(ready)


def fence_group(owner, phase, timeout):
    if phase not in ('terminate', 'fence'):
        raise ValueError('Invalid browser fence phase')
    if sys.platform != 'linux' or os.getppid() != owner or os.getpgrp() != owner or os.getsid(0) != owner:
        raise RuntimeError('Browser fence requires an Articulous-owned isolated Linux session')
    handles = {}
    try:
        if phase == 'terminate':
            collect_members(owner, handles, signal.SIGTERM)
        else:
            deadline = time.monotonic() + timeout
            freeze_members(owner, handles, deadline)
            for descriptor in handles.values():
                signal_member(descriptor, signal.SIGKILL)
            await_members(handles, deadline)
    finally:
        for descriptor in handles.values():
            os.close(descriptor)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('owner', type=int)
    parser.add_argument('phase', choices=('terminate', 'fence'))
    parser.add_argument('timeout', type=float)
    args = parser.parse_args(argv)
    if not 0 < args.timeout < float('inf'):
        parser.error('Fence timeout must be positive and finite')
    fence_group(args.owner, args.phase, args.timeout)


if __name__ == '__main__':
    main()
