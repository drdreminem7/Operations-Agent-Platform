import asyncio

import pytest
from fastapi.testclient import TestClient

from app.agent.decision_provider import DeterministicDecisionProvider
from app.agent.engine import AgentEngine
from app.agent.run import AgentRun
from app.main import app
from app.routes import runs as run_routes
from app.tools.defaults import create_default_registry
from app.tools.executor import ToolExecutor
from app.tools.simulator import Simulator

client = TestClient(app)


def test_bad_deployment_incident_is_approved_executed_and_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APPROVAL_API_KEY", "test-approval-key")
    headers = {
        "X-Approval-Key": "test-approval-key",
        "X-Operator-ID": "incident_commander",
    }

    created = client.post(
        "/incidents",
        json={
            "title": "Checkout latency increased after deployment",
            "service": "checkout",
            "severity": "high",
        },
    )
    assert created.status_code == 201
    incident_id = created.json()["id"]

    started = client.post(f"/incidents/{incident_id}/runs")
    assert started.status_code == 201
    run_id = started.json()["id"]

    states = [
        client.post(f"/runs/{run_id}/step").json()["current_state"]
        for _ in range(7)
    ]
    assert states == [
        "triage",
        "gather_context",
        "gather_context",
        "gather_context",
        "plan",
        "action_selected",
        "awaiting_approval",
    ]

    before_approval = client.get(f"/runs/{run_id}/steps").json()
    assert client.get(f"/runs/{run_id}/execution").status_code == 404
    read_tools = [
        step["payload_json"]["tool_name"]
        for step in before_approval
        if step["step_type"] == "tool_execution"
    ]
    assert read_tools == [
        "get_service_health",
        "get_recent_deployments",
        "search_logs",
    ]
    assert all(
        step["payload_json"]["decision_trace"]["provider"]
        == "DeterministicDecisionProvider"
        for step in before_approval
        if step["step_type"] == "tool_execution"
    )
    assert all(step["step_type"] != "tool_execution_failed" for step in before_approval)

    pending = client.get("/approvals/pending", headers=headers)
    assert pending.status_code == 200
    approval = next(item for item in pending.json() if item["run_id"] == run_id)
    assert approval["tool_name"] == "rollback_deployment"
    assert approval["arguments_json"] == {"service": "checkout", "version": "2.4.1"}

    approved = client.post(f"/approvals/{approval['id']}/approve", headers=headers)
    assert approved.status_code == 200
    assert approved.json()["decided_by"] == "incident_commander"

    execution = client.post(f"/runs/{run_id}/step")
    assert execution.status_code == 200
    assert execution.json()["current_state"] == "verify"
    saved_execution = client.get(f"/runs/{run_id}/execution")
    assert saved_execution.status_code == 200
    assert saved_execution.json()["status"] == "succeeded"
    assert len(saved_execution.json()["idempotency_key"]) == 64
    assert saved_execution.json()["finished_at"] is not None

    restarted_engine = AgentEngine(
        DeterministicDecisionProvider(),
        repository=run_routes.repository,
        tool_executor_factory=lambda run: ToolExecutor(
            create_default_registry(Simulator.from_results(run.tool_results))
        ),
    )
    monkeypatch.setattr(run_routes, "agent_engine", restarted_engine)

    verified = client.post(f"/runs/{run_id}/step")
    assert verified.status_code == 200
    assert verified.json()["current_state"] == "resolved"
    assert verified.json()["status"] == "completed"
    assert verified.json()["finished_at"] is not None

    steps = client.get(f"/runs/{run_id}/steps").json()
    assert [step["sequence_number"] for step in steps] == list(range(1, 11))
    assert [step["step_type"] for step in steps].count("tool_execution") == 4
    action = next(
        step
        for step in steps
        if step["step_type"] == "tool_execution"
        and step["payload_json"]["tool_name"] == "rollback_deployment"
    )
    assert action["payload_json"]["output"]["status"] == "rolled_back"
    proposal = next(step for step in steps if step["step_type"] == "action_proposal")
    assert (
        proposal["payload_json"]["decision_trace"]["provider"]
        == "DeterministicDecisionProvider"
    )
    verification = steps[-1]
    assert verification["step_type"] == "verification"
    assert verification["payload_json"]["result"] == "verified"
    assert verification["payload_json"]["evidence"]["health"]["status"] == "healthy"
    incident = client.get(f"/incidents/{incident_id}")
    assert incident.status_code == 200
    assert incident.json()["status"] == "resolved"
    assert client.get(f"/runs/{run_id}").json()["current_state"] == "resolved"


def test_simulator_state_is_isolated_between_runs() -> None:
    engine = AgentEngine(
        DeterministicDecisionProvider(),
        tool_executor_factory=lambda run: ToolExecutor(create_default_registry()),
    )
    first = AgentRun(
        incident_id=1,
        title="Checkout latency increased after deployment",
        service="checkout",
    )
    for _ in range(7):
        asyncio.run(engine.step(first))
    engine.decide_approval(first, approved=True)
    assert asyncio.run(engine.step(first)).value == "verify"

    second = AgentRun(
        incident_id=2,
        title="Checkout latency is high",
        service="checkout",
    )
    for _ in range(3):
        asyncio.run(engine.step(second))
    assert second.tool_results[0].output["status"] == "degraded"
