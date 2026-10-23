"""LIFE-002: finite post-handoff ownership model with fair operator recovery."""
from dataclasses import dataclass, replace

import pytest


@dataclass(frozen=True)
class State:
    owner: bool = True
    native: bool = True
    primary: bool = True
    borrowed: bool = True
    journal: bool = True


EVENTS = {
    'owner_loss': ({'owner': True}, {'owner': False}),
    'native_fence': ({'native': True}, {'native': False}),
    'release_primary': ({'owner': False, 'native': False, 'primary': True, 'journal': True}, {'primary': False}),
    'release_borrowed': ({'owner': False, 'native': False, 'borrowed': True, 'journal': True}, {'borrowed': False}),
    'settle': ({'owner': False, 'native': False, 'primary': False, 'borrowed': False, 'journal': True}, {'journal': False}),
}


def transition(state, event):
    required, effect = EVENTS[event]
    if any(getattr(state, key) != value for key, value in required.items()):
        raise ValueError('Forbidden durable-recovery transition')
    return replace(state, **effect)


def successors(state):
    result = set()
    for event in EVENTS:
        try:
            result.add(transition(state, event))
        except ValueError:
            pass
    return result


def reachable():
    pending = [State()]
    seen = set(pending)
    while pending:
        for successor in successors(pending.pop()) - seen:
            seen.add(successor)
            pending.append(successor)
    return seen


def assert_safe(state):
    if state.owner or state.native:
        assert state.primary and state.borrowed and state.journal
    if state.primary or state.borrowed:
        assert state.journal


def can_settle(states, terminal):
    settled = {terminal}
    while True:
        previous = len(settled)
        settled.update(state for state in states if successors(state) & settled)
        if len(settled) == previous:
            break
    return settled


def test_life002_exhaustive_durable_handoff_domain():
    states = reachable()
    terminal = State(False, False, False, False, False)
    assert len(states) == 8
    assert terminal in states
    for state in states:
        assert_safe(state)
    assert can_settle(states, terminal) == states


@pytest.mark.parametrize('event', ['release_primary', 'release_borrowed', 'settle'])
def test_life002_faulty_cleanup_controls(event):
    with pytest.raises(ValueError):
        transition(State(), event)
    with pytest.raises(ValueError):
        transition(State(owner=False), event)
