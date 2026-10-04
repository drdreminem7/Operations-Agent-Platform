import pytest
from fastapi.testclient import TestClient

from app.agent.providers.errors import ModelProviderError, ModelProviderTimeoutError
from app.agent.run import AgentRun
from app.agent.states import RunState
from app.main import app
from app.routes import runs as run_routes

client = TestClient(app)


def create_test_incident(title: str) -> int:
    response = client.post(
        "/incidents",
        json={
            "title": title,
            "service": "checkout",
            "severity": "high",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_create_step_and_read_run_history() -> None:
    incident_id = create_test_incident("Checkout latency is high")

    create_response = client.post(f"/incidents/{incident_id}/runs")

    assert create_response.status_code == 201
    run_id = create_response.json()["id"]
    assert create_response.json()["incident_id"] == incident_id
    assert create_response.json()["status"] == "running"
    assert create_response.json()["current_state"] == "new"

    expected_states = ["triage", "gather_context", "plan"]
    for expected_state in expected_states:
        step_response = client.post(f"/runs/{run_id}/step")
        assert step_response.status_code == 200
        assert step_response.json()["current_state"] == expected_state

    run_response = client.get(f"/runs/{run_id}")
    assert run_response.status_code == 200
    assert run_response.json()["current_state"] == "plan"

    steps_response = client.get(f"/runs/{run_id}/steps")
    assert steps_response.status_code == 200
    steps = steps_response.json()
    assert [step["sequence_number"] for step in steps] == [1, 2, 3]
    assert steps[2]["step_type"] == "tool_execution"
    assert steps[2]["payload_json"]["tool_name"] == "get_service_health"


def test_start_run_for_missing_incident_returns_404() -> None:
    response = client.post("/incidents/999999/runs")

    assert response.status_code == 404
    assert response.json() == {"detail": "Incident not found"}


def test_get_and_step_missing_run_return_404() -> None:
    assert client.get("/runs/999999").status_code == 404
    assert client.get("/runs/999999/steps").status_code == 404
    assert client.post("/runs/999999/step").status_code == 404


class TimeoutEngine:
    async def step(self, run: AgentRun) -> RunState:
        raise ModelProviderTimeoutError("Gemini request exceeded its timeout")


class FailedEngine:
    async def step(self, run: AgentRun) -> RunState:
        raise ModelProviderError("Gemini request failed")


def test_model_timeout_returns_504(monkeypatch: pytest.MonkeyPatch) -> None:
    incident_id = create_test_incident("Checkout errors increased")
    create_response = client.post(f"/incidents/{incident_id}/runs")
    run_id = create_response.json()["id"]
    monkeypatch.setattr(run_routes, "agent_engine", TimeoutEngine())

    response = client.post(f"/runs/{run_id}/step")

    assert response.status_code == 504
    assert response.json() == {
        "detail": "Gemini request exceeded its timeout"
    }


def test_model_failure_returns_502(monkeypatch: pytest.MonkeyPatch) -> None:
    incident_id = create_test_incident("Checkout errors increased")
    create_response = client.post(f"/incidents/{incident_id}/runs")
    run_id = create_response.json()["id"]
    monkeypatch.setattr(run_routes, "agent_engine", FailedEngine())

    response = client.post(f"/runs/{run_id}/step")

    assert response.status_code == 502
    assert response.json() == {"detail": "Gemini request failed"}
