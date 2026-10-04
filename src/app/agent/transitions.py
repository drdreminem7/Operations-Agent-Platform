from .states import RunState

ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.NEW: frozenset({RunState.TRIAGE}),
    RunState.TRIAGE: frozenset({RunState.GATHER_CONTEXT}),
    RunState.GATHER_CONTEXT: frozenset({RunState.GATHER_CONTEXT, RunState.PLAN}),
    RunState.PLAN: frozenset(
        {RunState.ACTION_SELECTED, RunState.ESCALATED, RunState.FAILED}
    ),
    RunState.ACTION_SELECTED: frozenset(
        {RunState.AWAITING_APPROVAL, RunState.EXECUTING}
    ),
    RunState.AWAITING_APPROVAL: frozenset({RunState.EXECUTING, RunState.ESCALATED}),
    RunState.EXECUTING: frozenset({RunState.VERIFY, RunState.FAILED}),
    RunState.VERIFY: frozenset(
        {RunState.RESOLVED, RunState.GATHER_CONTEXT, RunState.FAILED}
    ),
}


def ensure_transition_allowed(current: RunState, next_state: RunState) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())

    if next_state not in allowed:
        raise ValueError(
            f"Transition from {current.value} to {next_state.value} is not allowed"
        )
