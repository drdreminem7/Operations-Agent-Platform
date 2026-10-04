# Operations Agent Platform

An incident-response API with persisted agent runs, bounded tools, human
approval, and an auditable execution history. The platform investigates a
simulated service environment; it does not connect to production monitoring or
deployment systems.

The default decision provider is deterministic, so the full workflow runs
without a model API key. Gemini, routed Gemini, and vLLM-compatible providers
can be selected through configuration. In every mode, the application—not the
provider—owns tool permissions, state transitions, approvals, and execution.

## Features

- Incident CRUD backed by PostgreSQL and Alembic migrations.
- Manual and background agent runs with durable steps, job leases, and recovery
  rules for interrupted work.
- Typed, time-bounded tools for simulated health, logs, deployments, restart,
  and rollback.
- Approval records bound to the exact run, tool, and arguments before a
  simulated write can execute.
- Independent post-action verification; uncertain writes are not retried
  automatically.
- Structured logs, Prometheus metrics, OpenTelemetry traces, and a 20-scenario
  evaluation gate in CI.

## Run with Docker Compose

Requires Docker Desktop or Docker Engine with Compose. From the repository
root, create `.env` from `.env.example` if you do not already have one. Set a
long random `APPROVAL_API_KEY` to use the approval endpoints; set
`API_ACCESS_KEY` if you want the local API's incident, run, and metrics routes
to require `X-API-Key`.

```bash
cp -n .env.example .env
docker compose up --build -d
docker compose ps
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
```

Compose starts PostgreSQL, applies migrations, then starts the API and worker.
Open the [API documentation](http://127.0.0.1:8000/docs) for request and
response schemas. Ports 8000 and 5433 must be available. The worker immediately
processes any queued jobs already in the database; use the isolated smoke
stack described in [deployment](docs/deployment.md) for a clean startup test.

Stop the stack with `docker compose down`. The named PostgreSQL volume remains;
`down -v` would delete it.

## Run from Python

Requires Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and Docker for the
local PostgreSQL container. Create `.env` first if needed, then:

```bash
uv sync --group experiment
docker compose up -d postgres
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir src --reload --env-file .env
```

To process background jobs, start a worker in another terminal:

```bash
PYTHONPATH=src uv run --env-file .env python -m app.jobs.worker
```

Do not start the Compose API and host-side Uvicorn on port 8000 at the same
time. `/health` checks the process; `/ready` also checks PostgreSQL and returns
503 when the database is unavailable.

## Using the API

Create an incident with `POST /incidents`. Start a manual run with
`POST /incidents/{incident_id}/runs` or enqueue a background run with
`POST /incidents/{incident_id}/runs/background`. Inspect a run at
`GET /runs/{run_id}` and its history at `GET /runs/{run_id}/steps`.
Manual runs advance through `POST /runs/{run_id}/step`; background runs advance
through the worker. When a write requires review, use
`GET /approvals/pending` and `POST /approvals/{approval_id}/approve` or `/deny`.

Approval requests require `X-Approval-Key` and an `X-Operator-ID` audit label.
The operator label is not authenticated identity. If `API_ACCESS_KEY` is set,
send it as `X-API-Key` to incident, run, and metrics routes. See the
[end-to-end walkthrough](docs/demo-v1.md),
[background execution](docs/background-execution.md), and
[security notes](docs/security.md) for the full behavior and limitations.

## Providers and observability

`DECISION_PROVIDER` accepts `deterministic` (default), `gemini`, `routed`, or
`vllm`. Gemini modes need `GEMINI_API_KEY`; routed mode also needs distinct
`GEMINI_TRIAGE_MODEL` and `GEMINI_PLANNING_MODEL` values. vLLM mode needs a
reachable `VLLM_BASE_URL` and `VLLM_MODEL`. Model URLs inside Compose must be
reachable from the container network, not just from the host. The
[routing](docs/model-routing.md) and [self-hosted model](docs/self-hosted-model.md)
guides cover configuration and measured limits.

The API exposes `/metrics`; responses include `X-Trace-ID`. Application logs
are structured JSON. An optional OTLP endpoint exports traces. See
[observability](docs/observability.md) for metrics, dashboard setup, and trace
propagation.

## Verify

With PostgreSQL running and migrations applied:

```bash
uv run ruff check .
uv run mypy
uv run --group experiment pytest
PYTHONPATH=src uv run python -m app.evaluation --baseline evals/baseline.json
```

The evaluation runs against isolated simulated incidents and does not need
PostgreSQL. CI also builds and starts a disposable Compose stack. See
[evaluation](docs/evaluation.md), [performance](docs/performance.md), and the
[failure model](docs/failure-model.md) for methods and known gaps.

## Scope

All health, log, deployment, restart, and rollback tools operate on a local
simulator. The API and approval controls use shared keys rather than per-user
identity, and the evaluation dataset contains synthetic cases. This repository
is suitable for local experimentation, not unattended control of production
infrastructure. Live model quality and self-hosted serving performance require
separate validation before operational use.
