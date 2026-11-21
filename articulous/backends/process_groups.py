"""Linux process-group filter. Denied probes require the full identity check."""
import os
from pathlib import Path


def possible_group_member(pid, group):
    try:
        return os.getpgid(pid) == group
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def process_identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_bytes().rpartition(b') ')[2].split()
    except (FileNotFoundError, ProcessLookupError):
        return None
    return int(fields[2]), int(fields[19]), fields[0].decode('ascii')
