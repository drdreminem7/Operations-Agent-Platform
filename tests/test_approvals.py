from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from app.models import AgentRunRecord, ApprovalRecord, RunStepRecord
from app.routes.approvals import repository

client = TestClient(app)
HEADERS = {"X-Approval-Key": "test-approval-key", "X-Operator-ID": "harry"}


def create_waiting_run() -> tuple[int, int]:
    incident = client.post(
        "/incidents",
        json={
            "title": "Checkout latency after deployment",
            "service": "checkout",
            "severity": "high",
        },
    )
    assert incident.status_code == 201
    started = client.post(f"/incidents/{incident.json()['id']}/runs")
    assert started.status_code == 201
    run_id = started.json()["id"]

    for _ in range(7):
        response = client.post(f"/runs/{run_id}/step")
        assert response.status_code == 200

    assert response.json()["current_state"] == "awaiting_approval"
    approval = repository.get_approval_for_run(run_id)
    assert approval is not None
    return run_id, approval.id


def test_approval_requires_configured_operator_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APPROVAL_API_KEY", raising=False)
    assert client.get("/approvals/pending", headers=HEADERS).status_code == 503
    monkeypatch.setenv("APPROVAL_API_KEY", "test-approval-key")
    assert client.get("/approvals/pending").status_code == 403
    assert (
        client.get(
            "/approvals/pending", headers={"X-Approval-Key": "wrong"}
        ).status_code
        == 403
    )


def test_pending_approve_and_replay_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APPROVAL_API_KEY", "test-approval-key")
    run_id, approval_id = create_waiting_run()

    pending = client.get("/approvals/pending", headers=HEADERS)
    assert pending.status_code == 200
    item = next(row for row in pending.json() if row["id"] == approval_id)
    assert item["run_id"] == run_id
    assert item["tool_name"] == "rollback_deployment"
    assert item["arguments_json"] == {"service": "checkout", "version": "2.4.1"}
    assert len(item["action_hash"]) == 64

    approved = client.post(f"/approvals/{approval_id}/approve", headers=HEADERS)
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_by"] == "harry"
    assert client.get(f"/runs/{run_id}").json()["current_state"] == "executing"

    replay = client.post(f"/approvals/{approval_id}/approve", headers=HEADERS)
    assert replay.status_code == 409
    steps = client.get(f"/runs/{run_id}/steps").json()
    assert [step["step_type"] for step in steps].count("approval_decision") == 1


def test_denial_escalates_and_cannot_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APPROVAL_API_KEY", "test-approval-key")
    run_id, approval_id = create_waiting_run()

    denied = client.post(f"/approvals/{approval_id}/deny", headers=HEADERS)
    assert denied.status_code == 200
    assert denied.json()["status"] == "denied"
    assert client.get(f"/runs/{run_id}").json()["current_state"] == "escalated"
    assert client.post(f"/runs/{run_id}/step").status_code == 409


def test_expired_approval_cannot_be_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APPROVAL_API_KEY", "test-approval-key")
    run_id, approval_id = create_waiting_run()
    with Session(engine) as session:
        approval = session.get(ApprovalRecord, approval_id)
        assert approval is not None
        approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    response = client.post(f"/approvals/{approval_id}/approve", headers=HEADERS)
    assert response.status_code == 409
    approval = repository.get_approval(approval_id)
    assert approval is not None
    assert approval.status == "expired"
    assert client.get(f"/runs/{run_id}").json()["current_state"] == "awaiting_approval"


def test_changed_saved_action_invalidates_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APPROVAL_API_KEY", "test-approval-key")
    run_id, approval_id = create_waiting_run()
    with Session(engine) as session:
        proposal = (
            session.query(RunStepRecord)
            .filter_by(run_id=run_id, step_type="action_proposal")
            .one()
        )
        payload = dict(proposal.payload_json or {})
        payload["arguments"] = {"service": "checkout", "version": "2.3.0"}
        proposal.payload_json = payload
        session.commit()

    response = client.post(f"/approvals/{approval_id}/approve", headers=HEADERS)
    assert response.status_code == 409
    assert client.get(f"/runs/{run_id}").json()["current_state"] == "awaiting_approval"


def test_changed_review_record_invalidates_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APPROVAL_API_KEY", "test-approval-key")
    run_id, approval_id = create_waiting_run()
    with Session(engine) as session:
        approval = session.get(ApprovalRecord, approval_id)
        assert approval is not None
        approval.arguments_json = {"service": "checkout", "version": "2.3.0"}
        session.commit()

    response = client.post(f"/approvals/{approval_id}/approve", headers=HEADERS)
    assert response.status_code == 409
    assert "record differs" in response.json()["detail"]
    assert client.get(f"/runs/{run_id}").json()["current_state"] == "awaiting_approval"


def test_execution_rechecks_approved_action_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APPROVAL_API_KEY", "test-approval-key")
    run_id, approval_id = create_waiting_run()
    assert (
        client.post(f"/approvals/{approval_id}/approve", headers=HEADERS).status_code
        == 200
    )
    with Session(engine) as session:
        proposal = (
            session.query(RunStepRecord)
            .filter_by(run_id=run_id, step_type="action_proposal")
            .one()
        )
        payload = dict(proposal.payload_json or {})
        payload["arguments"] = {"service": "checkout", "version": "2.3.0"}
        proposal.payload_json = payload
        session.commit()

    step = client.post(f"/runs/{run_id}/step")
    assert step.status_code == 409
    assert "differs" in step.json()["detail"]
    assert client.get(f"/runs/{run_id}").json()["current_state"] == "executing"


def test_two_deciders_cannot_both_use_one_approval() -> None:
    run_id, approval_id = create_waiting_run()

    def decide(operator: str) -> str:
        try:
            repository.decide_approval(
                approval_id, approved=True, decided_by=operator
            )
        except ValueError:
            return "conflict"
        return "approved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, ["operator_a", "operator_b"]))

    assert sorted(results) == ["approved", "conflict"]
    steps = repository.list_steps(run_id)
    assert [step.step_type for step in steps].count("approval_decision") == 1


def test_ended_run_cannot_be_approved() -> None:
    run_id, approval_id = create_waiting_run()
    with Session(engine) as session:
        run = session.get(AgentRunRecord, run_id)
        assert run is not None
        run.current_state = "escalated"
        run.status = "escalated"
        session.commit()

    with pytest.raises(ValueError, match="not awaiting approval"):
        repository.decide_approval(
            approval_id, approved=True, decided_by="operator"
        )
