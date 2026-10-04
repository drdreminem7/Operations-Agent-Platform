from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import engine
from app.jobs.queue import RunJobQueue
from app.main import app
from app.models import AgentRunRecord, RunJobRecord

client = TestClient(app)


def create_background_run() -> int:
    incident = client.post(
        "/incidents",
        json={
            "title": "Checkout latency increased after deployment",
            "service": "checkout",
            "severity": "high",
        },
    )
    assert incident.status_code == 201
    response = client.post(f"/incidents/{incident.json()['id']}/runs/background")
    assert response.status_code == 201
    return response.json()["id"]


def test_background_run_enqueues_once_and_exposes_job() -> None:
    run_id = create_background_run()

    response = client.get(f"/runs/{run_id}/job")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["attempts"] == 0
    assert client.post(f"/runs/{run_id}/job").status_code == 202
    assert client.get(f"/runs/{run_id}/job").json()["id"] == response.json()["id"]


def test_concurrent_workers_cannot_claim_same_job() -> None:
    run_id = create_background_run()
    queue = RunJobQueue(engine)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(
            pool.map(
                lambda worker: queue.claim(worker, run_id=run_id),
                ("worker-a", "worker-b"),
            )
        )

    assert sum(job is not None for job in claims) == 1


def test_claim_is_exclusive_and_expired_lease_can_be_reclaimed() -> None:
    run_id = create_background_run()
    queue = RunJobQueue(engine)
    first = queue.claim("worker-a", run_id=run_id)
    assert first is not None
    assert first.lease_token is not None
    assert queue.claim("worker-b", run_id=run_id) is None

    with Session(engine) as session:
        record = session.get(RunJobRecord, first.id)
        assert record is not None
        record.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    second = queue.claim("worker-b", run_id=run_id)
    assert second is not None
    assert second.id == first.id
    assert second.lease_token != first.lease_token
    assert second.attempts == 2
    with pytest.raises(ValueError, match="no longer owned"):
        queue.heartbeat(first.id, first.lease_token)
    with pytest.raises(ValueError, match="no longer owned"):
        queue.finish(first.id, first.lease_token)
    assert second.lease_token is not None
    queue.finish(second.id, second.lease_token)
    saved = queue.get_for_run(run_id)
    assert saved is not None
    assert saved.status == "queued"


def test_heartbeat_extends_owned_lease() -> None:
    run_id = create_background_run()
    queue = RunJobQueue(engine)
    job = queue.claim("worker-a", run_id=run_id)
    assert job is not None
    assert job.lease_token is not None
    assert job.lease_until is not None

    queue.heartbeat(job.id, job.lease_token, lease_seconds=120)

    saved = queue.get_for_run(run_id)
    assert saved is not None
    assert saved.lease_until is not None
    assert saved.lease_until > job.lease_until
    assert saved.heartbeat_at is not None


def test_transient_failure_has_bounded_backoff() -> None:
    run_id = create_background_run()
    queue = RunJobQueue(engine)
    for failure_count in (1, 2, 3):
        with Session(engine) as session:
            record = session.query(RunJobRecord).filter_by(run_id=run_id).one()
            record.available_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        job = queue.claim("worker-a", run_id=run_id)
        assert job is not None
        assert job.lease_token is not None
        queue.fail(job.id, job.lease_token, "provider timeout", retry=True)
        saved = queue.get_for_run(run_id)
        assert saved is not None
        assert saved.failure_count == failure_count
        assert saved.status == ("failed" if failure_count == 3 else "queued")
    assert queue.claim("worker-b", run_id=run_id) is None


def test_repeated_worker_deaths_stop_reclaiming() -> None:
    run_id = create_background_run()
    queue = RunJobQueue(engine)
    job = queue.claim("worker-a", run_id=run_id)
    assert job is not None

    for failure_count in (1, 2, 3):
        with Session(engine) as session:
            record = session.get(RunJobRecord, job.id)
            assert record is not None
            record.lease_until = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        reclaimed = queue.claim("worker-b", run_id=run_id)
        saved = queue.get_for_run(run_id)
        assert saved is not None
        assert saved.failure_count == failure_count
        if failure_count < 3:
            assert reclaimed is not None
            assert reclaimed.lease_owner == "worker-b"
            job = reclaimed
        else:
            assert reclaimed is None
            assert saved.status == "failed"


def test_awaiting_approval_cannot_be_queued() -> None:
    run_id = create_background_run()
    with Session(engine) as session:
        run = session.get(AgentRunRecord, run_id)
        assert run is not None
        run.current_state = "awaiting_approval"
        session.commit()

    response = client.post(f"/runs/{run_id}/job")
    assert response.status_code == 409
