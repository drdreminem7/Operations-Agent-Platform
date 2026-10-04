# Production AI Operations Agent Platform

## Purpose

This project is a stateful incident-response system for a simulated software
company. It helps an operator investigate incidents, gather evidence, choose
actions, obtain approval for dangerous changes, execute approved actions, and
verify outcomes.

It is an agent platform rather than a chatbot because the application owns
state, legal transitions, permissions, persistence, tool execution, retries,
verification, and audit history. The language model is one decision-making
component inside that controlled workflow.

## V0 charter

V0 must support the complete conceptual flow:

1. Create an incident.
2. Start an agent run.
3. Gather evidence through explicit tools.
4. Choose a next action.
5. Require approval for dangerous actions.
6. Execute approved tools.
7. Store execution history.
8. Show the final resolution.

The first implementation will be deterministic and testable without a real
LLM. Model integration comes later.

## Safety and reliability requirements

- Dangerous actions cannot execute without policy approval.
- Every state transition is persisted.
- Every tool call is auditable.
- Model outputs are validated before use.
- Failures cannot silently corrupt run state.

## V0 non-goals

Multi-region execution, Kubernetes, enterprise auth,
real production infrastructure, autonomous shell access, arbitrary code
execution, browser automation, multiple agents, and long-term semantic memory
are explicitly deferred.

## Project roadmap

Milestone 0 defines this charter. Milestone 1 establishes the runnable
repository and infrastructure baseline. Later milestones add incidents,
tools, the deterministic agent engine, model providers, policy, approvals,
durability, observability, evaluation, and hardening.

The [engineering journal](docs/engineering-journal.md) records the implemented
milestones, file-by-file flows, verification, and what you should be able to
explain. The [learning guide](docs/milestone-learning-guide.md) expands on the
concepts and later roadmap.
The [evaluation guide](docs/evaluation.md) describes the current eight-case
simulated benchmark, including a known unsafe rollback case.

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
```

### Stop PostgreSQL

```bash
docker compose stop postgres
```

Start it again with `docker compose start postgres`. The named Docker volume
keeps the database data when the container is stopped.
