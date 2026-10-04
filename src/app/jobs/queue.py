from datetime import UTC, datetime, timedelta
from uuid import uuid4

from opentelemetry import propagate
from sqlalchemy import or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..agent.states import RunState
from ..models import AgentRunRecord, RunJobRecord

TERMINAL_STATES = {RunState.RESOLVED, RunState.ESCALATED, RunState.FAILED}


class RunJobQueue:
    def __init__(self, db_engine: Engine) -> None:
        self._engine = db_engine

    def get_for_run(self, run_id: int) -> RunJobRecord | None:
        with Session(self._engine) as session:
            return session.scalar(
                select(RunJobRecord).where(RunJobRecord.run_id == run_id)
            )

    def enqueue(self, run_id: int) -> RunJobRecord:
        carrier: dict[str, str] = {}
        propagate.inject(carrier)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                run = session.get(AgentRunRecord, run_id, with_for_update=True)
                if run is None:
                    raise LookupError("Run not found")
                state = RunState(run.current_state)
                if state in TERMINAL_STATES:
                    raise ValueError("Terminal run cannot be queued")
                if state == RunState.AWAITING_APPROVAL:
                    raise ValueError("Run is awaiting approval")
                job = session.scalar(
                    select(RunJobRecord)
                    .where(RunJobRecord.run_id == run_id)
                    .with_for_update()
                )
                if job is None:
                    job = RunJobRecord(
                        run_id=run_id,
                        status="queued",
                        available_at=datetime.now(UTC),
                        traceparent=carrier.get("traceparent"),
                    )
                    session.add(job)
                elif job.status in {"paused", "failed"}:
                    if job.status == "failed":
                        job.failure_count = 0
                    job.status = "queued"
                    job.available_at = datetime.now(UTC)
                    job.last_error = None
                session.flush()
            return job

    def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 60,
        run_id: int | None = None,
    ) -> RunJobRecord | None:
        if not worker_id or len(worker_id) > 100:
            raise ValueError("Worker ID must be 1 to 100 characters")
        if lease_seconds <= 0:
            raise ValueError("Lease duration must be positive")
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                statement = (
                    select(RunJobRecord)
                    .where(
                        or_(
                            (RunJobRecord.status == "queued")
                            & (RunJobRecord.available_at <= now),
                            (RunJobRecord.status == "running")
                            & (RunJobRecord.lease_until <= now),
                        )
                    )
                    .order_by(RunJobRecord.available_at, RunJobRecord.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if run_id is not None:
                    statement = statement.where(RunJobRecord.run_id == run_id)
                job = session.scalar(statement)
                if job is None:
                    return None
                if job.status == "running":
                    job.failure_count += 1
                    job.last_error = "Worker lease expired"
                    if job.failure_count >= 3:
                        job.status = "failed"
                        job.lease_owner = None
                        job.lease_token = None
                        job.lease_until = None
                        return None
                job.status = "running"
                job.attempts += 1
                job.lease_owner = worker_id
                job.lease_token = str(uuid4())
                job.lease_until = now + timedelta(seconds=lease_seconds)
                job.heartbeat_at = now
            return job

    def heartbeat(
        self, job_id: int, lease_token: str, *, lease_seconds: int = 60
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("Lease duration must be positive")
        with Session(self._engine) as session:
            with session.begin():
                job = session.get(RunJobRecord, job_id, with_for_update=True)
                if (
                    job is None
                    or job.status != "running"
                    or job.lease_token != lease_token
                ):
                    raise ValueError("Job lease is no longer owned by this worker")
                now = datetime.now(UTC)
                if job.lease_until is None or job.lease_until <= now:
                    raise ValueError("Job lease has expired")
                job.heartbeat_at = now
                job.lease_until = now + timedelta(seconds=lease_seconds)

    def finish(self, job_id: int, lease_token: str) -> None:
        with Session(self._engine) as session:
            with session.begin():
                existing = session.get(RunJobRecord, job_id)
                if existing is None:
                    raise ValueError("Job not found")
                run = session.get(AgentRunRecord, existing.run_id, with_for_update=True)
                if run is None:
                    raise ValueError("Run not found")
                job = session.get(RunJobRecord, job_id, with_for_update=True)
                if (
                    job is None
                    or job.status != "running"
                    or job.lease_token != lease_token
                ):
                    raise ValueError("Job lease is no longer owned by this worker")
                state = RunState(run.current_state)
                if state == RunState.AWAITING_APPROVAL:
                    job.status = "paused"
                elif state == RunState.FAILED:
                    job.status = "failed"
                elif state in TERMINAL_STATES:
                    job.status = "completed"
                else:
                    job.status = "queued"
                    job.available_at = datetime.now(UTC)
                job.lease_owner = None
                job.lease_token = None
                job.lease_until = None
                job.failure_count = 0

    def fail(self, job_id: int, lease_token: str, error: str, *, retry: bool) -> None:
        with Session(self._engine) as session:
            with session.begin():
                job = session.get(RunJobRecord, job_id, with_for_update=True)
                if (
                    job is None
                    or job.status != "running"
                    or job.lease_token != lease_token
                ):
                    raise ValueError("Job lease is no longer owned by this worker")
                job.last_error = error
                job.failure_count += 1
                job.status = "queued" if retry and job.failure_count < 3 else "failed"
                if job.status == "queued":
                    job.available_at = datetime.now(UTC) + timedelta(
                        seconds=min(30, 2**job.failure_count)
                    )
                job.lease_owner = None
                job.lease_token = None
                job.lease_until = None
