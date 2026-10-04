import asyncio
import logging
import os
import signal
import socket
from contextlib import suppress

from opentelemetry import propagate, trace

from ..agent.engine import AgentEngine
from ..agent.factory import create_agent_engine
from ..agent.providers.errors import ModelProviderError
from ..agent.repository import AgentRunRepository
from ..agent.states import RunState
from ..database import engine
from ..observability.logging import bind_context, log_event
from ..observability.metrics import configure_active_runs
from ..observability.tracing import configure_tracing
from .queue import TERMINAL_STATES, RunJobQueue

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class RunWorker:
    def __init__(
        self,
        queue: RunJobQueue,
        repository: AgentRunRepository,
        agent_engine: AgentEngine,
        worker_id: str,
    ) -> None:
        self._queue = queue
        self._repository = repository
        self._agent_engine = agent_engine
        self._worker_id = worker_id

    async def _heartbeat(self, job_id: int, lease_token: str) -> None:
        while True:
            await asyncio.sleep(10)
            self._queue.heartbeat(job_id, lease_token)

    async def run_once(self, *, run_id: int | None = None) -> bool:
        job = self._queue.claim(self._worker_id, run_id=run_id)
        if job is None:
            return False
        if job.lease_token is None:
            raise ValueError("Claimed job has no lease token")
        lease_token = job.lease_token
        heartbeat: asyncio.Task[None] | None = None
        parent = propagate.extract(
            {"traceparent": job.traceparent} if job.traceparent else {}
        )
        with (
            bind_context(run_id=job.run_id),
            tracer.start_as_current_span("worker.job", context=parent) as span,
        ):
            span.set_attribute("run.id", job.run_id)
            try:
                run = self._repository.load_run(job.run_id)
                if run is None:
                    raise ValueError("Run for job does not exist")
                with bind_context(incident_id=run.incident_id):
                    if run.current_state not in TERMINAL_STATES | {
                        RunState.AWAITING_APPROVAL
                    }:
                        heartbeat = asyncio.create_task(
                            self._heartbeat(job.id, lease_token)
                        )
                        await self._agent_engine.step(run)
            except ModelProviderError as error:
                self._queue.fail(job.id, lease_token, str(error), retry=True)
                log_event(
                    logger,
                    logging.WARNING,
                    "run_job_retry_scheduled",
                    job_id=job.id,
                    error_type=type(error).__name__,
                )
                return True
            except Exception as error:
                self._queue.fail(job.id, lease_token, str(error), retry=False)
                log_event(
                    logger,
                    logging.ERROR,
                    "run_job_failed",
                    job_id=job.id,
                    error_type=type(error).__name__,
                )
                return True
            finally:
                if heartbeat is not None:
                    heartbeat.cancel()
                    with suppress(asyncio.CancelledError):
                        await heartbeat
            self._queue.finish(job.id, lease_token)
            log_event(logger, logging.INFO, "run_job_finished", job_id=job.id)
        return True

    async def run_forever(
        self,
        stop: asyncio.Event,
        *,
        poll_seconds: float = 1.0,
        run_id: int | None = None,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("Poll interval must be positive")
        while not stop.is_set():
            try:
                worked = await self.run_once(run_id=run_id)
            except Exception as error:
                log_event(
                    logger,
                    logging.ERROR,
                    "worker_iteration_failed",
                    error_type=type(error).__name__,
                )
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
                except TimeoutError:
                    pass


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(message)s"
    )
    configure_tracing("operations-agent-worker")
    configure_active_runs(engine)
    metrics_port = os.getenv("WORKER_METRICS_PORT")
    if metrics_port:
        from prometheus_client import start_http_server

        start_http_server(int(metrics_port), addr="127.0.0.1")
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, stop.set)
    repository = AgentRunRepository(engine)
    worker = RunWorker(
        RunJobQueue(engine),
        repository,
        create_agent_engine(repository),
        f"{socket.gethostname()}:{os.getpid()}"[:100],
    )
    await worker.run_forever(stop)


if __name__ == "__main__":
    asyncio.run(main())
