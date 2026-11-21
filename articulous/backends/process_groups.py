"""Linux process-group filter. Denied probes require the full identity check."""
import os


def possible_group_member(pid, group):
    try:
        return os.getpgid(pid) == group
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
