import asyncio

from sqlalchemy.orm import Session

from app.agent.decision_provider import DeterministicDecisionProvider
from app.agent.engine import AgentEngine
from app.agent.repository import AgentRunRepository
from app.agent.run import AgentRun
from app.agent.states import RunState
from app.database import engine
from app.models import Incident
from app.tools.defaults import create_default_registry
from app.tools.executor import ToolExecutor


def test_run_can_be_reloaded_and_continue_after_restart() -> None:
    with Session(engine) as session:
        incident = Incident(
            title="Errors started after deployment",
            service="checkout",
            severity="high",
            status="open",
        )
        session.add(incident)
        session.commit()
        session.refresh(incident)
        incident_id = incident.id

    repository = AgentRunRepository(engine)
    run_id = repository.create_run(incident_id)

    run = AgentRun(
        run_id=run_id,
        incident_id=incident_id,
        title="Errors started after deployment",
        service="checkout",
    )
    agent_engine = AgentEngine(
        DeterministicDecisionProvider(),
        ToolExecutor(create_default_registry()),
        repository,
    )

    for _ in range(5):
        asyncio.run(agent_engine.step(run))

    reloaded_run = repository.load_run(run_id)

    assert reloaded_run is not None
    assert reloaded_run.current_state == RunState.AWAITING_APPROVAL
    assert len(reloaded_run.history) == 5
    assert len(reloaded_run.tool_results) == 1
    assert reloaded_run.tool_results[0].tool_name == "get_recent_deployments"
    assert reloaded_run.action_proposal is not None
    assert reloaded_run.action_proposal.action == "rollback_deployment"
    assert reloaded_run.action_proposal.arguments == {
        "service": "checkout",
        "version": "2.4.1",
    }

    state = agent_engine.decide_approval(reloaded_run, approved=False)

    assert state == RunState.ESCALATED

    saved_run = repository.get_run(run_id)
    saved_steps = repository.list_steps(run_id)

    assert saved_run is not None
    assert saved_run.current_state == "escalated"
    assert saved_run.status == "escalated"
    assert len(saved_steps) == 6
    assert saved_steps[3].step_type == "action_proposal"
    assert saved_steps[3].payload_json == {
        "action": "rollback_deployment",
        "arguments": {"service": "checkout", "version": "2.4.1"},
        "requires_approval": True,
        "policy_outcome": "require_approval",
        "policy_reason": "Human approval required for simulated write",
        "decision_trace": {"provider": "DeterministicDecisionProvider"},
    }
