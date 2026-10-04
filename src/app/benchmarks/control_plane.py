import argparse
import asyncio
import json
import os
import platform
import resource
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from math import ceil
from time import perf_counter, process_time

from fastapi.testclient import TestClient
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from ..agent.decision_provider import DeterministicDecisionProvider
from ..agent.engine import AgentEngine
from ..agent.run import AgentRun
from ..agent.states import RunState
from ..database import engine
from ..main import app
from ..tools.defaults import create_default_registry
from ..tools.executor import ToolExecutor


@dataclass
class Measurement:
    samples: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    throughput_per_second: float


def nearest_rank(samples: list[float], percentile: float) -> float:
    if not samples:
        raise ValueError("At least one sample is required")
    if not 0 < percentile <= 1:
        raise ValueError("Percentile must be between zero and one")
    ordered = sorted(samples)
    return ordered[ceil(len(ordered) * percentile) - 1]


def measure(operation: Callable[[], None], iterations: int) -> Measurement:
    if iterations < 1:
        raise ValueError("Iterations must be positive")
    for _ in range(min(10, iterations)):
        operation()
    samples = []
    started = perf_counter()
    for _ in range(iterations):
        sample_started = perf_counter()
        operation()
        samples.append(perf_counter() - sample_started)
    elapsed = perf_counter() - started
    return Measurement(
        samples=iterations,
        p50_ms=nearest_rank(samples, 0.50) * 1000,
        p95_ms=nearest_rank(samples, 0.95) * 1000,
        p99_ms=nearest_rank(samples, 0.99) * 1000,
        throughput_per_second=iterations / elapsed,
    )


async def run_in_memory_agent() -> None:
    agent = AgentEngine(
        DeterministicDecisionProvider(),
        ToolExecutor(create_default_registry()),
    )
    run = AgentRun(incident_id=1, title="Checkout errors", service="checkout")
    while run.current_state != RunState.ESCALATED:
        await agent.step(run)


def database_probe() -> None:
    with Session(engine) as session:
        session.execute(sql_text("SELECT 1"))


def report(iterations: int, *, with_database: bool) -> dict[str, object]:
    client = TestClient(app)

    def health_request() -> None:
        response = client.get("/health")
        if response.status_code != 200:
            raise RuntimeError("Health request failed")

    def ready_request() -> None:
        response = client.get("/ready")
        if response.status_code != 200:
            raise RuntimeError("Readiness request failed")

    cpu_started = process_time()
    wall_started = perf_counter()
    measurements = {
        "health_http": asdict(measure(health_request, iterations)),
        "in_memory_agent": asdict(
            measure(lambda: asyncio.run(run_in_memory_agent()), iterations)
        ),
    }
    if with_database:
        measurements["database_select_1"] = asdict(
            measure(database_probe, iterations)
        )
        measurements["ready_http"] = asdict(measure(ready_request, iterations))
    wall_seconds = perf_counter() - wall_started
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_bytes = peak_rss if sys.platform == "darwin" else peak_rss * 1024
    return {
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "concurrency": 1,
            "dataset": "synthetic local checkout escalation",
            "iterations_per_operation": iterations,
            "database_included": with_database,
        },
        "measurements": measurements,
        "process_cpu_seconds": process_time() - cpu_started,
        "wall_seconds": wall_seconds,
        "peak_process_rss_bytes": rss_bytes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure local control-plane paths")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--with-database", action="store_true")
    args = parser.parse_args()
    result = report(args.iterations, with_database=args.with_database)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
