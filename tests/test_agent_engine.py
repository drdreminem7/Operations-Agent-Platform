import asyncio

import pytest

from app.agent.decision_provider import (
    ActionProposal,
    DeterministicDecisionProvider,
)
from app.agent.engine import AgentEngine
from app.agent.run import AgentRun
from app.agent.states import RunState
from app.tools.defaults import create_default_registry
from app.tools.errors import ToolExecutionError
from app.tools.executor import ToolExecutor
from app.tools.result import ToolResult


def make_engine() -> AgentEngine:
    executor = ToolExecutor(create_default_registry())
    return AgentEngine(DeterministicDecisionProvider(), executor)


def make_context_run(title: str) -> AgentRun:
    run = AgentRun(
        incident_id=42,
        title=title,
        service="checkout",
    )
    run.transition_to(RunState.TRIAGE)
    run.transition_to(RunState.GATHER_CONTEXT)
    return run


def test_gather_context_executes_selected_tool_and_advances_run() -> None:
    engine = make_engine()
    run = make_context_run("Checkout latency is high")

    result = asyncio.run(engine.gather_context(run))

    assert result.tool_name == "get_service_health"
    assert run.current_state == RunState.PLAN
    assert run.tool_results == [result]


def test_gather_context_rejects_run_in_wrong_state() -> None:
    engine = make_engine()
    run = AgentRun(
        incident_id=42,
        title="Checkout latency is high",
        service="checkout",
    )

    with pytest.raises(ValueError, match="gather_context"):
        asyncio.run(engine.gather_context(run))

    assert run.current_state == RunState.NEW
    assert run.tool_results == []


def test_gather_context_searches_logs_for_other_incidents() -> None:
    engine = make_engine()
    run = make_context_run("Checkout errors increased")

    result = asyncio.run(engine.gather_context(run))

    assert result.tool_name == "search_logs"
    assert result.output["query"] == "error"
    assert run.current_state == RunState.PLAN
    assert run.tool_results == [result]


def test_tool_failure_does_not_advance_run() -> None:
    engine = make_engine()
    run = make_context_run("Checkout latency is high")
    run.service = "unknown-service"

    with pytest.raises(ToolExecutionError, match="Unknown simulated service"):
        asyncio.run(engine.gather_context(run))

    assert run.current_state == RunState.GATHER_CONTEXT
    assert run.tool_results == []


def test_gather_context_checks_recent_deployments() -> None:
    engine = make_engine()
    run = make_context_run("Errors started after deployment")

    result = asyncio.run(engine.gather_context(run))

    assert result.tool_name == "get_recent_deployments"
    assert result.output["service"] == "checkout"
    assert run.current_state == RunState.PLAN
    assert run.tool_results == [result]


def test_step_escalates_deployment_clue_without_corroborating_evidence() -> None:
    engine = make_engine()
    run = AgentRun(
        incident_id=42,
        title="Errors started after deployment",
        service="checkout",
    )

    states = [asyncio.run(engine.step(run)) for _ in range(4)]

    assert states == [
        RunState.TRIAGE,
        RunState.GATHER_CONTEXT,
        RunState.PLAN,
        RunState.ESCALATED,
    ]
    assert len(run.history) == 4
    assert len(run.tool_results) == 1
    assert run.action_proposal is not None
    assert run.action_proposal.action == "escalate"


def test_engine_rejects_unsupported_provider_rollback() -> None:
    class UnsupportedRollbackProvider(DeterministicDecisionProvider):
        async def propose_action(
            self, *, title: str, service: str, evidence: list[ToolResult]
        ) -> ActionProposal:
            return ActionProposal(
                action="rollback_deployment",
                arguments={"service": service, "version": "2.4.1"},
                reason="A deployment exists",
            )

    engine = AgentEngine(
        UnsupportedRollbackProvider(), ToolExecutor(create_default_registry())
    )
    run = AgentRun(
        incident_id=42,
        title="Errors started after deployment",
        service="checkout",
    )

    states = [asyncio.run(engine.step(run)) for _ in range(4)]

    assert states[-1] == RunState.ESCALATED
    assert run.action_proposal is not None
    assert run.action_proposal.action == "escalate"


def test_step_escalates_when_proposal_does_not_require_approval() -> None:
    engine = make_engine()
    run = AgentRun(
        incident_id=42,
        title="Checkout errors increased",
        service="checkout",
    )

    states = [asyncio.run(engine.step(run)) for _ in range(4)]

    assert states[-1] == RunState.ESCALATED
    assert run.action_proposal is not None
    assert run.action_proposal.action == "escalate"


def test_decision_to_approve_or_deny_requires_waiting_state() -> None:
    engine = make_engine()
    run = AgentRun(
        incident_id=42,
        title="Checkout latency is high",
        service="checkout",
    )

    with pytest.raises(ValueError, match="not awaiting approval"):
        engine.decide_approval(run, approved=True)

    assert run.current_state == RunState.NEW
    assert run.history == []


def make_approval_run() -> AgentRun:
    run = AgentRun(
        incident_id=42,
        title="Errors started after deployment",
        service="checkout",
    )
    run.transition_to(RunState.TRIAGE)
    run.transition_to(RunState.GATHER_CONTEXT)
    run.transition_to(RunState.PLAN)
    run.action_proposal = ActionProposal(
        action="rollback_deployment",
        arguments={"service": "checkout", "version": "2.4.1"},
        reason="Test rollback proposal",
    )
    run.transition_to(RunState.ACTION_SELECTED)
    run.transition_to(RunState.AWAITING_APPROVAL)
    return run


def test_approval_moves_run_to_executing() -> None:
    engine = make_engine()
    run = make_approval_run()

    state = engine.decide_approval(run, approved=True)

    assert state == RunState.EXECUTING
    assert run.history[-1].state_after == RunState.EXECUTING


def test_denial_escalates_run() -> None:
    engine = make_engine()
    run = make_approval_run()

    state = engine.decide_approval(run, approved=False)

    assert state == RunState.ESCALATED
    assert run.history[-1].state_after == RunState.ESCALATED
