import pytest

from app.agent.states import RunState
from app.agent.transitions import ALLOWED_TRANSITIONS, ensure_transition_allowed


def test_allows_legal_transition() -> None:
    ensure_transition_allowed(RunState.NEW, RunState.TRIAGE)


def test_rejects_illegal_transition() -> None:
    with pytest.raises(ValueError, match="is not allowed"):
        ensure_transition_allowed(RunState.NEW, RunState.EXECUTING)


def test_terminal_state_cannot_continue() -> None:
    with pytest.raises(ValueError, match="is not allowed"):
        ensure_transition_allowed(RunState.RESOLVED, RunState.GATHER_CONTEXT)


@pytest.mark.parametrize(
    ("current", "next_state"),
    [
        (current, next_state)
        for current, allowed in ALLOWED_TRANSITIONS.items()
        for next_state in allowed
    ],
)
def test_all_declared_transitions_are_allowed(
    current: RunState,
    next_state: RunState,
) -> None:
    ensure_transition_allowed(current, next_state)


@pytest.mark.parametrize(
    "terminal_state",
    [RunState.RESOLVED, RunState.ESCALATED, RunState.FAILED],
)
def test_terminal_states_cannot_continue(terminal_state: RunState) -> None:
    with pytest.raises(ValueError, match="is not allowed"):
        ensure_transition_allowed(terminal_state, RunState.GATHER_CONTEXT)
