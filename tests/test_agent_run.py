import pytest

from app.agent.run import AgentRun, RunTransition
from app.agent.states import RunState


def test_run_starts_new_with_empty_history() -> None:
    run = AgentRun(
        incident_id=42,
        title="Checkout latency",
        service="checkout",
    )

    assert run.current_state == RunState.NEW
    assert run.history == []


def test_transition_updates_state_and_records_history() -> None:
    run = AgentRun(
        incident_id=42,
        title="Checkout latency",
        service="checkout",
    )

    transition = run.transition_to(RunState.TRIAGE)

    assert run.current_state == RunState.TRIAGE
    assert transition == RunTransition(
        sequence_number=1,
        state_before=RunState.NEW,
        state_after=RunState.TRIAGE,
    )
    assert run.history == [transition]


def test_illegal_transition_leaves_run_unchanged() -> None:
    run = AgentRun(
        incident_id=42,
        title="Checkout latency",
        service="checkout",
    )

    with pytest.raises(ValueError, match="is not allowed"):
        run.transition_to(RunState.EXECUTING)

    assert run.current_state == RunState.NEW
    assert run.history == []
