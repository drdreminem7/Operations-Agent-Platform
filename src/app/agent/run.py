from dataclasses import dataclass, field

from ..tools.result import ToolResult
from .decision_provider import ActionProposal
from .states import RunState
from .transitions import ensure_transition_allowed


@dataclass(frozen=True)
class RunTransition:
    sequence_number: int
    state_before: RunState
    state_after: RunState


@dataclass
class AgentRun:
    incident_id: int
    title: str
    service: str
    description: str | None = None
    run_id: int | None = None
    current_state: RunState = RunState.NEW
    history: list[RunTransition] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    action_proposal: ActionProposal | None = None

    def prepare_transition(self, next_state: RunState) -> RunTransition:
        ensure_transition_allowed(self.current_state, next_state)

        return RunTransition(
            sequence_number=len(self.history) + 1,
            state_before=self.current_state,
            state_after=next_state,
        )

    def apply_transition(self, transition: RunTransition) -> None:
        if transition.state_before != self.current_state:
            raise ValueError("Transition does not start from the current run state")

        if transition.sequence_number != len(self.history) + 1:
            raise ValueError("Transition sequence number is incorrect")

        ensure_transition_allowed(self.current_state, transition.state_after)
        self.history.append(transition)
        self.current_state = transition.state_after

    def transition_to(self, next_state: RunState) -> RunTransition:
        transition = self.prepare_transition(next_state)
        self.apply_transition(transition)
        return transition
