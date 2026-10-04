# Operations Agent Platform

A stateful incident-response system for a simulated software environment.
Operators create incidents, start agent runs, review evidence and proposed
actions, approve or deny simulated changes, and inspect the audit history.
The application owns transitions, authorization, execution, and persistence;
the decision provider cannot perform arbitrary actions.

The platform runs with a deterministic decision provider by default. A Gemini
provider is available when configured with an API key. Neither provider has
access to real production infrastructure: health, deployments, logs, restart,
and rollback tools operate on a local simulator.

## What works

- Incident creation, listing, retrieval, and partial update in PostgreSQL.
- Manual or database-backed background agent runs with durable steps and jobs.
- Read tools for simulated health, deployments, and logs; simulated restart
  and rollback tools with server-owned permission checks.
- Human approval records bound to a specific run, tool, and argument set.
  Denial escalates the run; successful execution is independently verified.
- Fail-closed recovery around write intents and worker leases. Uncertain
  effects are not automatically retried.
- Structured application logs, Prometheus metrics, and OpenTelemetry traces.
- A 20-scenario, simulator-only evaluation suite and CI regression gate.

The incident path is: create incident → start run → gather evidence → propose
action or escalate → request approval if required → execute a simulated action
→ verify the result → record the final state. For deployment rollback, the
application requires degraded health, a matching error log, and an active
production deployment; a deployment mention alone is insufficient.

## Architecture and scope

`src/app/routes/` handles HTTP requests; `schemas.py` defines API contracts;
`models.py` and Alembic migrations define persistent records. `agent/` owns
state transitions, decisions, policy integration, and the repository.
`tools/` contains the registry, executor, simulator, and bounded capabilities.
`jobs/` runs background work; `observability/` records operational signals;
`evaluation/` runs isolated scenarios. The
[architecture guide](docs/architecture.md), [engineering journal](docs/engineering-journal.md),
and [learning guide](docs/milestone-learning-guide.md) explain the file-level
flow and trade-offs.

This is a runnable local research prototype, not a production operations
controller. The approval API uses a shared key rather than individual identity;
the simulator is not real infrastructure; and the evaluation dataset covers
only 20 synthetic cases. See [evaluation](docs/evaluation.md) and the
[failure model](docs/failure-model.md) for exact limits; see the
[security model](docs/security.md) before exposing the API.
The [performance baseline](docs/performance.md) records reproducible local
control-plane measurements and their limits.
An [isolated LangGraph comparison](docs/runtime-comparison.md) exercises the
same simulated approval path without replacing the API runtime.
The optional [model-routing mode](docs/model-routing.md) separates read-tool
choice from action planning and fails closed on planning-provider errors.
The [vLLM adapter](docs/self-hosted-model.md) has a tested HTTP contract but
still needs a GPU-backed server for live quality and serving measurements.
The [container deployment guide](docs/deployment.md) covers a local Compose
stack for PostgreSQL, migrations, API, and worker.

## Local development

### Prerequisites

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)
- Docker Desktop with Docker Compose

### Start the project

From the repository root, install the project and development dependencies:

```bash
uv sync
cp .env.example .env
```

Start PostgreSQL in Docker:

```bash
docker compose up -d postgres
docker compose ps
uv run alembic upgrade head
```

The database is published on `localhost:5433`. The host port is 5433 because
port 5432 may already be used by a locally installed PostgreSQL server. The
container still listens on its standard internal port, 5432.

In a separate terminal, start the API:

```bash
uv run uvicorn app.main:app --app-dir src --reload --env-file .env
```

The API listens at `http://127.0.0.1:8000`. Open `http://127.0.0.1:8000/docs`
for the interactive API documentation.

### Check the API

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
```

`/health` reports whether the API process is running. `/ready` runs a small
query against PostgreSQL and returns HTTP 503 when the database is unavailable.

Edit `.env` to change `APP_NAME` or `DATABASE_URL`. The local `.env` file is
ignored by Git. For a one-run title override, set `APP_NAME` before starting
Uvicorn:

```bash
APP_NAME="Test Operations API" uv run uvicorn app.main:app --app-dir src --reload --env-file .env
```

The example database URL is `postgresql+psycopg://operations:operations@localhost:5433/operations`.

For access outside localhost, configure `API_ACCESS_KEY` in `.env` and send it
as `X-API-Key` on incident/run/metrics requests. This is a shared local key,
not individual user authentication; approvals use a separate key. See the
[security model](docs/security.md) for coverage and limits.

### Review a simulated action

Set a long, random `APPROVAL_API_KEY` in your local `.env` and restart the API.
After a deployment-related run reaches `awaiting_approval`, inspect pending
requests and approve or deny a specific approval ID:

```bash
export APPROVAL_API_KEY="<same secret as in .env>"
curl -H "X-Approval-Key: $APPROVAL_API_KEY" -H "X-Operator-ID: harry" http://127.0.0.1:8000/approvals/pending
curl -X POST -H "X-Approval-Key: $APPROVAL_API_KEY" -H "X-Operator-ID: harry" http://127.0.0.1:8000/approvals/1/approve
```

Replace `1` with an ID returned by the pending endpoint. Use `/deny` instead
of `/approve` to reject it. This shared key is for local
development; `X-Operator-ID` is an audit label, not authenticated identity.
Approved actions execute only against the simulator. For a complete incident
walkthrough, follow the [V1 demo](docs/demo-v1.md).
The [failure model](docs/failure-model.md) explains crash windows and why an
uncertain write is not automatically retried.

### Run an incident in the background

Start a worker in another terminal after applying migrations:

```bash
PYTHONPATH=src uv run --env-file .env python -m app.jobs.worker
```

Create a run with `POST /incidents/{incident_id}/runs/background`, then inspect
`GET /runs/{run_id}/job` and `GET /runs/{run_id}/steps`. The worker pauses for
approval and resumes when the existing approval endpoint accepts the action.
The original `/runs/{run_id}/step` endpoint remains available for manual
walkthroughs. The [background execution guide](docs/background-execution.md)
explains leases, retry limits, shutdown, and failure recovery.

### Observe runs

The API exposes metrics at `http://127.0.0.1:8000/metrics`. Set
`WORKER_METRICS_PORT=9001` in `.env` for a separate worker metrics endpoint.
Application log events are JSON and responses include `X-Trace-ID`. Set
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to export spans to a collector. The
[observability guide](docs/observability.md) explains the Grafana dashboard,
Prometheus scrape setup, trace propagation, and privacy limits.

### Run quality checks

```bash
uv run ruff check .
uv run mypy
uv run pytest
PYTHONPATH=src uv run python -m app.evaluation --baseline evals/baseline.json
```

The evaluation command prints a JSON report and exits nonzero if its reviewed
scenario set, expected outcomes, tool-use budget, or safety thresholds regress.
CI uploads that report as an artifact. No PostgreSQL connection is needed for
the evaluation itself; the full test suite does require PostgreSQL. The
[evaluation guide](docs/evaluation.md) explains the metrics and coverage.

### Run the complete local stack in Docker

After creating `.env`, stop any host-side API on port 8000 and run:

```bash
docker compose up --build -d
docker compose ps
curl -i http://127.0.0.1:8000/ready
```

This starts PostgreSQL, applies migrations once, and runs the API and worker.
See the [container deployment guide](docs/deployment.md) for configuration,
logs, shutdown, and security limits. This is not a public-cloud deployment.

### Stop PostgreSQL

```bash
docker compose stop postgres
```

Start it again with `docker compose start postgres`. The named Docker volume
keeps the database data when the container is stopped.
