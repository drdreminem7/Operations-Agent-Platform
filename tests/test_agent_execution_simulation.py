import asyncio

import pytest

from app.agent.decision_provider import DeterministicDecisionProvider
from app.agent.engine import AgentEngine
from app.agent.run import AgentRun
from app.agent.states import RunState
from app.tools.defaults import create_default_registry
from app.tools.executor import ToolExecutor
from app.tools.simulator import Simulator


def test_approved_proposal_executes_simulated_rollback_and_verifies() -> None:
    engine = AgentEngine(
        DeterministicDecisionProvider(),
        ToolExecutor(create_default_registry()),
    )
    run = AgentRun(
        incident_id=42,
        title="Errors started after deployment",
        service="checkout",
    )

    for _ in range(5):
        asyncio.run(engine.step(run))

    assert run.current_state == RunState.AWAITING_APPROVAL
    assert run.action_proposal is not None
    assert run.action_proposal.action == "rollback_deployment"

    assert engine.decide_approval(run, approved=True) == RunState.EXECUTING
    assert asyncio.run(engine.step(run)) == RunState.VERIFY
    assert run.tool_results[-1].tool_name == "rollback_deployment"
    assert run.tool_results[-1].output["status"] == "rolled_back"
    assert asyncio.run(engine.step(run)) == RunState.RESOLVED

    history_length = len(run.history)
    with pytest.raises(ValueError, match="No automatic step"):
        asyncio.run(engine.step(run))

    assert run.current_state == RunState.RESOLVED
    assert len(run.history) == history_length


def test_verification_does_not_resolve_when_health_remains_degraded() -> None:
    simulator = Simulator()
    engine = AgentEngine(
        DeterministicDecisionProvider(),
        ToolExecutor(create_default_registry(simulator)),
    )
    run = AgentRun(
        incident_id=43,
        title="Errors started after deployment",
        service="checkout",
    )
    for _ in range(5):
        asyncio.run(engine.step(run))
    engine.decide_approval(run, approved=True)
    assert asyncio.run(engine.step(run)) == RunState.VERIFY

    simulator.health["checkout"] = {"status": "degraded", "latency_ms": 900}

    assert asyncio.run(engine.step(run)) == RunState.FAILED
    assert run.current_state != RunState.RESOLVED


def test_stale_deployment_fails_without_retrying_automatically() -> None:
    simulator = Simulator()
    engine = AgentEngine(
        DeterministicDecisionProvider(),
        ToolExecutor(create_default_registry(simulator)),
    )
    run = AgentRun(
        incident_id=44,
        title="Errors started after deployment",
        service="checkout",
    )
    for _ in range(5):
        asyncio.run(engine.step(run))
    engine.decide_approval(run, approved=True)
    simulator.deployments[0]["status"] = "rolled_back"

    assert asyncio.run(engine.step(run)) == RunState.FAILED
    assert simulator.service_health("checkout")["status"] == "degraded"
    with pytest.raises(ValueError, match="No automatic step"):
        asyncio.run(engine.step(run))
