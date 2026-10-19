"""TEST-002: finite independent ownership contract and native trace refinement."""
from dataclasses import dataclass, replace
import sys
from unittest.mock import patch
import pytest
from articulous.backends import processes


@dataclass(frozen=True)
class State:
    lease: bool = True
    quiet: bool = False
    pipes: bool = True
    workspace: bool = True


REQUIRES = {
    'signal': {'lease': True, 'workspace': True},
    'fence': {'lease': True, 'workspace': True},
    'reap': {'lease': True, 'quiet': True, 'pipes': False},
    'close': {'lease': True, 'quiet': True, 'pipes': True},
    'cleanup': {'lease': False, 'quiet': True, 'pipes': False, 'workspace': True},
    'retain': {'workspace': True},
}
EFFECTS = {'signal': {}, 'fence': {'quiet': True}, 'reap': {'lease': False},
           'close': {'pipes': False}, 'cleanup': {'workspace': False}, 'retain': {}}


def transition(state, event):
    required = REQUIRES[event]
    if any(getattr(state, key) != value for key, value in required.items()):
        raise ValueError('Forbidden native ownership transition: ' + event)
    return replace(state, **EFFECTS[event])


def test_test002_exhaustive_single_group_domain():
    pending = [State(), State(lease=False, quiet=True, pipes=False)]
    seen = set(pending)
    forbidden = set()
    while pending:
        state = pending.pop()
        for event in REQUIRES:
            try:
                successor = transition(state, event)
            except ValueError:
                forbidden.add(event)
                continue
            assert successor.lease or successor.quiet
            assert successor.workspace or not successor.pipes
            if successor not in seen:
                seen.add(successor)
                pending.append(successor)
    assert len(seen) == 5
    assert forbidden == set(REQUIRES)
    assert State(lease=False, quiet=True, pipes=False, workspace=False) in seen
    with pytest.raises(ValueError):
        transition(State(), 'cleanup')
    with pytest.raises(ValueError):
        transition(State(lease=False, quiet=True, pipes=False, workspace=False), 'signal')


def test_test002_native_trace_refines_contract():
    trace = []
    native_fence = processes.await_group_exit
    native_cleanup = processes.cleanup_workspace
    def fence(group):
        native_fence(group)
        trace.append('fence')
    def cleanup(path, identity):
        native_cleanup(path, identity)
        trace.append('cleanup')
    with patch.object(processes, 'await_group_exit', fence), patch.object(processes, 'cleanup_workspace', cleanup):
        with processes.open_session([sys.executable, '-c', 'print("done")']) as session:
            assert isinstance(session, processes.LinuxSession)
            session.communicate()
            native_wait = session._process.wait
            def wait():
                result = native_wait()
                trace.append('reap')
                return result
            class ObservedPipe:
                def __init__(self, stderr, stdout):
                    self.stderr, self.stdout = stderr, stdout

                def close(self):
                    self.stderr.close()
                    assert self.stdout.closed
                    trace.append('close')
            observed = ObservedPipe(session._process.stderr, session._process.stdout)
            with patch.object(session, '_stderr', observed), patch.object(session._process, 'wait', wait):
                session.stop()
            # Context exit repeats only the cached, already-settled stop.
    state = State()
    for event in trace:
        state = transition(state, event)
    assert not state.workspace and not state.pipes and not state.lease
