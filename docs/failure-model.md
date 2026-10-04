# Execution failure model

This document describes the current simulated rollback path. It is not a claim of exactly-once delivery to an external system.

The database stores a unique execution row per run. Its idempotency key is the SHA-256 hash of the run ID, tool name, and canonical arguments, matching the reviewed approval. A `started` row is committed before the tool runs. A successful tool result, `succeeded` execution status, `verify` run state, and numbered audit step are committed together. A controlled tool failure is conservatively recorded as `uncertain`, because an exception or timeout does not prove that no effect occurred. The same write is never automatically retried in an uncertain state.

| Crash or failure point | Persisted state | Current behavior |
| --- | --- | --- |
| Before approval | No approved action | Execution is refused. |
| Before execution-intent commit | Run is `executing`, no execution row | A later step may claim and attempt the action; no tool call happened yet. |
| After intent commit, before/during the tool | Execution is `started` | A second immediate request gets 409. After 10 seconds, the run becomes `failed` and execution becomes `uncertain`; no automatic write retry. |
| After tool effect, before result commit | Execution is still `started` | Same uncertain path. An operator must investigate whether the effect happened. |
| During result/state transaction | Either the entire result, step, and state change commit, or none do | If none commit, the intent becomes uncertain after the stale interval. |
| After result transaction, before HTTP response | Execution is `succeeded`; run is `verify` | A new step verifies; it does not execute the write again. |
| After process restart before verification | Run and successful result are persisted | The local simulator rebuilds its state from the saved synthetic result, then health/deployment checks can continue. This replay changes only in-memory simulation state, not an external service. |
| Verification fails | Action may have occurred; run becomes `failed` | Incident stays open for human review. |

Every registered tool has a retry class in its metadata. Health, logs, and deployment reads are `READ_ONLY_IDEMPOTENT`; restart and rollback are `WRITE_NON_IDEMPOTENT`. Custom tools default to `NO_RETRY`, and a read-only/write classification mismatch is rejected when metadata is constructed. `WRITE_IDEMPOTENT` is reserved for a future tool with a real idempotency guarantee; none of the current writes has one. These classes describe what may be safe to retry, not a promise that the runtime will retry a tool call. The background worker may retry a failed model/decision step with bounded backoff or reclaim a lost lease; it does not automatically retry an uncertain write. A caller can request another read, subject to policy and limits. The simulated restart reaches the same health state if repeated, but a real restart may not be harmless. Unknown tools and uncertain writes have no automatic tool-retry path.

The 10-second stale threshold is longer than the current simulated write-tool timeout of 2 seconds. It is a conservative detection rule, not proof that a worker died. A slow worker could still be active when another request marks its record uncertain; the second request nevertheless does not issue a duplicate write. A later result from the first worker will be rejected if its run state changed.

The `GET /runs/{run_id}/execution` endpoint exposes the execution row for local inspection. An `uncertain` outcome requires manual reconciliation. The current API does not provide a safe automatic resume or a manual “confirm effect” operation for that case. Its in-memory simulator cannot prove what a real external service did during a crash. A production adapter would need a provider-enforced idempotency key and/or a reliable query of operation status, with explicit recovery rules. Outbox/inbox patterns can close database/message handoff gaps, but a database transaction cannot magically include an arbitrary remote side effect.

The key is unique only within this database and includes the run ID. Starting a new run for the same incident creates a new key; cross-run deduplication is not implemented. The approval API uses a local shared secret rather than distinct authenticated operators, and the simulator is still not a real operations system.

The crash-recovery tests cover the no-effect and effect-before-persistence windows, a tool exception, stale intent after approval expiry, and a database failure during the result/state/step transaction. In that transaction-failure test the simulated effect has happened, but all database result/state/step changes roll back. A later stale-intent check records `uncertain` without another tool call. The end-to-end test covers a committed result followed by a fresh engine performing verification rather than executing again. No local test can prove delivery semantics for a real remote provider.

## Fault-injection coverage

| Injected fault | Expected behavior | Test |
|---|---|---|
| Decision provider times out before a tool choice | No transition or evidence is committed; a later explicit retry can proceed. | `test_fault_injection.py::test_provider_timeout_does_not_commit_a_transition` |
| Read tool exceeds its deadline | Tool error; run remains in `gather_context` without evidence. | `test_fault_injection.py::test_tool_fault_does_not_advance_run` |
| Read tool returns another tool's name | Executor rejects the malformed result; no transition. | `test_fault_injection.py::test_tool_fault_does_not_advance_run` |
| PostgreSQL connection fails during readiness | `/ready` returns 503 without a connection string. | `test_fault_injection.py::test_database_failure_returns_not_ready_without_exposing_connection` |
| Write effect may have occurred before result persistence | Execution becomes uncertain after the stale threshold; no automatic replay. | `test_agent_crash_recovery.py` |
| Approval is replayed or action arguments change | Approval is rejected and cannot authorize a different write. | `test_approvals.py` |
| Worker lease expires or is claimed twice | Token fencing and row locking prevent two successful owners. | `test_job_queue.py` |
| vLLM returns 429/500, malformed JSON, a partial/empty choice, or a connection error | Adapter reports a typed provider error without retrying or exposing the upstream body; the worker's existing bounded provider-error policy applies if a job is running. | `test_vllm_provider.py` |

The suite does not kill an OS process, sever a real network connection, or
exercise a live Gemini or vLLM 429/500 response in a deployed environment. Those
failures need controlled integration infrastructure and should not be
represented as covered by mocks alone.
