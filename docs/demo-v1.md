# V1 incident-response demo

This demo uses the deterministic provider and an isolated, in-memory simulator. It never changes a real service. PostgreSQL stores incidents, runs, approvals, and the audit trail.

1. Start PostgreSQL, apply migrations, and run the API as described in the [README](../README.md). In local `.env`, set `DECISION_PROVIDER=deterministic` and a long random `APPROVAL_API_KEY`. Restart Uvicorn after editing `.env`.
2. Open `http://127.0.0.1:8000/docs`. POST `/incidents` with:

   ```json
   {"title":"Checkout latency increased after deployment","service":"checkout","severity":"high"}
   ```

3. Copy the incident ID. POST `/incidents/{incident_id}/runs` and copy the run ID.
4. POST `/runs/{run_id}/step` seven times. The states should be `triage`, `gather_context`, `gather_context`, `gather_context`, `plan`, `action_selected`, `awaiting_approval`. No rollback has executed yet.
5. GET `/approvals/pending` with headers `X-Approval-Key: <the value in .env>` and `X-Operator-ID: <your audit label>`. Find the record for this run. Confirm its tool is `rollback_deployment` and its arguments name the `checkout` service and version `2.4.1`.
6. POST `/approvals/{approval_id}/approve` with the same headers. The run enters `executing`. To demonstrate rejection instead, use `/deny`; that run escalates and cannot execute.
7. POST `/runs/{run_id}/step` twice more. The first executes the simulator rollback and enters `verify`; the second checks health and deployment state, then enters `resolved` only if both checks pass.
8. GET `/runs/{run_id}/execution`, `/runs/{run_id}/steps`, `/runs/{run_id}`, and `/incidents/{incident_id}`. Show the saved idempotency key and execution status, read-tool results, provider decision traces, proposed action and policy reason, approval decision, rollback output, verification evidence, completed run, and resolved incident.

The run steps are the demo recording: they contain numbered state changes and structured evidence. In deterministic mode, a trace identifies `DeterministicDecisionProvider`; it is not an LLM call. With a valid Gemini key, decision traces additionally contain the model name, latency, and token counts, but the model may choose a different safe path. Prompts, raw model responses, and API keys are not persisted in run steps.

The simulator state is isolated per run and lives in the API process. If a successful action result was committed before a restart, a new engine rebuilds synthetic state from that saved result and can verify it. If the process died after the tool effect but before the result commit, the database only knows that execution started. After the stale interval, it marks the outcome `uncertain` and never automatically repeats the write. See the [failure model](failure-model.md). Do not use this approval API or tool setup for real production changes.
