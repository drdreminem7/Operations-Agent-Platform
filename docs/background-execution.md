# Background run execution

The manual `POST /runs/{run_id}/step` endpoint remains available. To let a worker advance a run, create it with `POST /incidents/{incident_id}/runs/background`. That request commits the run and its unique job in one PostgreSQL transaction, then returns immediately. The worker is a separate process; API requests do not wait for model calls or tool execution.

Start the API and worker in separate terminals after `uv run alembic upgrade head`:

```bash
uv run uvicorn app.main:app --app-dir src --reload --env-file .env
PYTHONPATH=src uv run --env-file .env python -m app.jobs.worker
```

Inspect progress with `GET /runs/{run_id}`, `GET /runs/{run_id}/steps`, and `GET /runs/{run_id}/job`. `POST /runs/{run_id}/job` queues a manual run or requeues a failed job after investigation. It refuses a run that is awaiting approval or already terminal. A background job paused for approval is requeued in the same transaction that approves the action; denial completes the job without executing it.

## Queue contract

| Job state | Meaning |
| --- | --- |
| `queued` | Eligible when `available_at` has passed. |
| `running` | A worker owns a lease and is advancing one run state. |
| `paused` | The run is waiting for human approval. |
| `completed` | The run resolved or escalated. |
| `failed` | The run failed or the job needs operator attention. |

The worker polls PostgreSQL and claims one eligible job with `FOR UPDATE SKIP LOCKED`. A claim receives a fresh token and a 60-second lease; a heartbeat renews it every 10 seconds while the step runs. Only that token can finish or fail the job. The worker performs one agent step per claim, then requeues the job if the run remains active. One worker process handles one step at a time; multiple processes can claim different jobs. `SIGINT` and `SIGTERM` stop new claims after the current step completes.

The background-run request stores a W3C `traceparent` with the job. A worker extracts it before running the step, so spans from the API request and worker can share one trace without storing credentials or request bodies. See the [observability guide](observability.md).

A lost worker's lease can be reclaimed. Three consecutive expired leases fail the job, avoiding an endless hot loop. Model-provider errors before a successful step get at most two automatic reattempts with short exponential delays; successful steps reset that failure count. Other unexpected errors fail the job for inspection. These are **job/decision retries**, not automatic retries of a write tool. The approved write still uses the durable intent and uncertain-outcome rules in the [failure model](failure-model.md).

## Crash boundaries and limits

- Before a claim: the queued job remains available.
- After a claim but before a step commits: another worker can reclaim after lease expiry. A read or model decision may be repeated; database state transitions still enforce the saved state.
- After a step commits but before the job is acknowledged: reclaiming loads the current run state and proceeds from there, rather than replaying the completed transition.
- During an approved write: the separate action-execution record prevents a second write claim. If the result was not persisted, the outcome becomes `uncertain`; the worker does not assume failure and retry it.
- After three lease expirations: the job remains `failed` until an operator investigates and explicitly requeues it. A run may still display its last persisted state, so inspect both the job and run.

The database queue is intentionally small. It has no broker, fleet-wide concurrency budget, dead-letter service, or automatic reconciliation with a real operations provider. Lease expiry cannot prove a process is dead. The token prevents stale acknowledgements, while the run's state checks and the action intent protect against duplicate unsafe effects. A PostgreSQL transaction cannot make an external side effect exactly once.
