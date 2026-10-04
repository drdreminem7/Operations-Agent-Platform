import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.agent.approval import action_hash
from app.agent.decision_provider import DeterministicDecisionProvider
from app.agent.engine import AgentEngine
from app.agent.repository import AgentRunRepository
from app.agent.run import AgentRun
from app.agent.states import RunState
from app.database import engine
from app.models import ActionExecutionRecord, ApprovalRecord, Incident, RunStepRecord
from app.tools.defaults import create_default_registry
from app.tools.executor import ToolExecutor
from app.tools.result import ToolResult
from app.tools.simulator import Simulator


def make_executing_run() -> tuple[AgentRunRepository, AgentEngine, AgentRun, Simulator]:
    with Session(engine) as session:
        incident = Incident(
            title="Checkout latency after deployment",
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
        title="Checkout latency after deployment",
        service="checkout",
    )
    simulator = Simulator()
    agent_engine = AgentEngine(
        DeterministicDecisionProvider(),
        ToolExecutor(create_default_registry(simulator)),
        repository,
    )
    for _ in range(7):
        asyncio.run(agent_engine.step(run))
    assert agent_engine.decide_approval(run, approved=True) == RunState.EXECUTING
    return repository, agent_engine, run, simulator


def make_claim_stale(run_id: int) -> None:
    with Session(engine) as session:
        record = (
            session.query(ActionExecutionRecord).filter_by(run_id=run_id).one()
        )
        record.started_at = datetime.now(UTC) - timedelta(seconds=11)
        session.commit()


@pytest.mark.parametrize("effect_happened", [False, True])
def test_stale_execution_becomes_uncertain_without_automatic_retry(
    effect_happened: bool,
) -> None:
    repository, agent_engine, run, simulator = make_executing_run()
    assert run.run_id is not None
    assert run.action_proposal is not None
    assert repository.claim_execution(run.run_id, run.action_proposal)

    if effect_happened:
        simulator.rollback_deployment("checkout", "2.4.1")

    with pytest.raises(ValueError, match="already in progress"):
        asyncio.run(agent_engine.step(run))
    assert run.current_state == RunState.EXECUTING

    make_claim_stale(run.run_id)
    assert asyncio.run(agent_engine.step(run)) == RunState.FAILED
    record = repository.get_execution(run.run_id)
    assert record is not None
    assert record.status == "uncertain"
    assert record.idempotency_key == action_hash(
        run.run_id,
        run.action_proposal.action,
        run.action_proposal.arguments,
    )
    assert repository.list_steps(run.run_id)[-1].step_type == "execution_uncertain"
    assert simulator.service_health("checkout")["status"] == (
        "healthy" if effect_happened else "degraded"
    )


def test_crash_after_tool_effect_before_result_persistence_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, agent_engine, run, simulator = make_executing_run()
    assert run.run_id is not None

    def fail_persistence(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected persistence failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(repository, "record_execution_result", fail_persistence)
        with pytest.raises(RuntimeError, match="injected persistence failure"):
            asyncio.run(agent_engine.step(run))

    assert simulator.service_health("checkout")["status"] == "healthy"
    record = repository.get_execution(run.run_id)
    assert record is not None
    assert record.status == "started"

    make_claim_stale(run.run_id)
    assert asyncio.run(agent_engine.step(run)) == RunState.FAILED
    recovered = repository.get_execution(run.run_id)
    assert recovered is not None
    assert recovered.status == "uncertain"


def test_result_state_and_step_roll_back_together_on_write_failure() -> None:
    repository, agent_engine, run, simulator = make_executing_run()
    assert run.run_id is not None
    assert run.action_proposal is not None
    proposal = run.action_proposal
    assert repository.claim_execution(run.run_id, proposal)
    original_step_count = len(repository.list_steps(run.run_id))
    output = simulator.rollback_deployment("checkout", "2.4.1")
    result = ToolResult(tool_name=proposal.action, output=output)

    def fail_step_write(session: Session, *args: object) -> None:
        if any(
            isinstance(record, RunStepRecord)
            and record.step_type == "tool_execution"
            for record in session.new
        ):
            raise RuntimeError("injected step write failure")

    event.listen(Session, "before_flush", fail_step_write)
    try:
        with pytest.raises(RuntimeError, match="injected step write failure"):
            repository.record_execution_result(
                run.run_id,
                run.prepare_transition(RunState.VERIFY),
                proposal,
                result=result,
            )
    finally:
        event.remove(Session, "before_flush", fail_step_write)

    execution = repository.get_execution(run.run_id)
    persisted_run = repository.get_run(run.run_id)
    assert execution is not None
    assert persisted_run is not None
    assert execution.status == "started"
    assert execution.result_json is None
    assert persisted_run.current_state == RunState.EXECUTING.value
    assert len(repository.list_steps(run.run_id)) == original_step_count
    assert simulator.service_health("checkout")["status"] == "healthy"

    make_claim_stale(run.run_id)
    assert asyncio.run(agent_engine.step(run)) == RunState.FAILED
    recovered = repository.get_execution(run.run_id)
    assert recovered is not None
    assert recovered.status == "uncertain"
    assert len(repository.list_steps(run.run_id)) == original_step_count + 1


def test_tool_error_after_claim_is_recorded_as_uncertain() -> None:
    repository, agent_engine, run, simulator = make_executing_run()
    assert run.run_id is not None
    simulator.deployments[0]["status"] = "rolled_back"

    assert asyncio.run(agent_engine.step(run)) == RunState.FAILED
    record = repository.get_execution(run.run_id)
    assert record is not None
    assert record.status == "uncertain"
    assert record.error is not None
    assert repository.list_steps(run.run_id)[-1].step_type == "execution_uncertain"


def test_expired_approval_does_not_prevent_stale_intent_recovery() -> None:
    repository, agent_engine, run, simulator = make_executing_run()
    assert run.run_id is not None
    assert run.action_proposal is not None
    assert repository.claim_execution(run.run_id, run.action_proposal)
    make_claim_stale(run.run_id)
    with Session(engine) as session:
        approval = (
            session.query(ApprovalRecord).filter_by(run_id=run.run_id).one()
        )
        approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    assert asyncio.run(agent_engine.step(run)) == RunState.FAILED
    record = repository.get_execution(run.run_id)
    assert record is not None
    assert record.status == "uncertain"
    assert simulator.service_health("checkout")["status"] == "degraded"
