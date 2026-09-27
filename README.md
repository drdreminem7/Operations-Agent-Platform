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

Distributed execution, Kubernetes, multi-region deployment, enterprise auth,
real production infrastructure, autonomous shell access, arbitrary code
execution, browser automation, multiple agents, and long-term semantic memory
are explicitly deferred.

## Project roadmap

Milestone 0 defines this charter. Milestone 1 establishes the runnable
repository and infrastructure baseline. Later milestones add incidents,
tools, the deterministic agent engine, model providers, policy, approvals,
durability, observability, evaluation, and hardening.

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
```

The database is published on `localhost:5433`. The host port is 5433 because
port 5432 may already be used by a locally installed PostgreSQL server. The
container still listens on its standard internal port, 5432.

In a separate terminal, start the API:

```bash
uv run uvicorn main:app --reload --env-file .env
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
APP_NAME="Test Operations API" uv run uvicorn main:app --reload --env-file .env
```

The example database URL is `postgresql+psycopg://operations:operations@localhost:5433/operations`.

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
