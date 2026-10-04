import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agent.factory import create_agent_engine
from app.agent.providers.errors import ModelProviderTimeoutError
from app.agent.repository import AgentRunRepository
from app.agent.run import AgentRun
from app.agent.states import RunState
from app.database import engine
from app.jobs.queue import RunJobQueue
from app.jobs.worker import RunWorker
from app.main import app
from app.models import RunJobRecord

client = TestClient(app)


def make_worker_run() -> tuple[int, RunWorker, AgentRunRepository, RunJobQueue]:
    incident = client.post(
        "/incidents",
        json={
            "title": "Checkout latency increased after deployment",
            "service": "checkout",
            "severity": "high",
        },
    )
    assert incident.status_code == 201
    started = client.post(f"/incidents/{incident.json()['id']}/runs/background")
    assert started.status_code == 201
    run_id = started.json()["id"]
    repository = AgentRunRepository(engine)
    queue = RunJobQueue(engine)
    worker = RunWorker(
        queue, repository, create_agent_engine(repository), "test-worker"
    )
    return run_id, worker, repository, queue


def test_worker_pauses_for_approval_then_resumes_without_duplicate_write() -> None:
    run_id, worker, repository, queue = make_worker_run()

    for _ in range(7):
        assert asyncio.run(worker.run_once(run_id=run_id))
    paused = queue.get_for_run(run_id)
    assert paused is not None
    assert paused.status == "paused"
    assert paused.attempts == 7
    assert repository.get_execution(run_id) is None
    assert not asyncio.run(worker.run_once(run_id=run_id))

    approval = repository.get_approval_for_run(run_id)
    assert approval is not None
    repository.decide_approval(approval.id, approved=True, decided_by="test-operator")
    queued = queue.get_for_run(run_id)
    assert queued is not None
    assert queued.status == "queued"

    assert asyncio.run(worker.run_once(run_id=run_id))
    execution = repository.get_execution(run_id)
    assert execution is not None
    assert execution.status == "succeeded"
    assert asyncio.run(worker.run_once(run_id=run_id))
    finished = queue.get_for_run(run_id)
    assert finished is not None
    assert finished.status == "completed"
    assert not asyncio.run(worker.run_once(run_id=run_id))
    run = repository.get_run(run_id)
    assert run is not None
    assert run.current_state == "resolved"
    assert [step.step_type for step in repository.list_steps(run_id)].count(
        "tool_execution"
    ) == 4


def test_worker_retries_provider_timeout_before_any_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, worker, repository, queue = make_worker_run()

    async def timeout(*args: object) -> None:
        raise ModelProviderTimeoutError("provider timeout")

    with monkeypatch.context() as patcher:
        patcher.setattr(worker._agent_engine, "step", timeout)
        assert asyncio.run(worker.run_once(run_id=run_id))

    job = queue.get_for_run(run_id)
    assert job is not None
    assert job.status == "queued"
    assert job.failure_count == 1
    assert job.last_error == "provider timeout"
    assert repository.list_steps(run_id) == []

    with Session(engine) as session:
        saved = session.get(RunJobRecord, job.id)
        assert saved is not None
        saved.available_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    assert asyncio.run(worker.run_once(run_id=run_id))
    saved = queue.get_for_run(run_id)
    assert saved is not None
    assert saved.status == "queued"
    assert saved.failure_count == 0
    run = repository.get_run(run_id)
    assert run is not None
    assert run.current_state == "triage"


def test_graceful_stop_finishes_current_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, worker, repository, queue = make_worker_run()
    step = worker._agent_engine.step

    async def run_until_stopped() -> None:
        stop = asyncio.Event()

        async def one_step(run: AgentRun) -> RunState:
            result = await step(run)
            stop.set()
            return result

        monkeypatch.setattr(worker._agent_engine, "step", one_step)
        await worker.run_forever(stop, poll_seconds=0.01, run_id=run_id)

    asyncio.run(run_until_stopped())

    run = repository.get_run(run_id)
    job = queue.get_for_run(run_id)
    assert run is not None
    assert job is not None
    assert run.current_state == "triage"
    assert job.status == "queued"
    assert job.attempts == 1
