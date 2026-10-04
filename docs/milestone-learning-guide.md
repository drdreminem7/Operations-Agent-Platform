# Milestone-by-Milestone Learning Guide

This is the learning companion to [`production-ai-operations-agent-platform-plan.md`](../production-ai-operations-agent-platform-plan.md). It explains what each milestone is for, how information moves through its files, and what you should be able to explain before moving on.

## How to use this guide

For each milestone:

1. Read the purpose and workflow.
2. Open the listed files and trace one complete request or operation through them.
3. Explain the concepts in your own words without relying on memorized definitions.
4. Run the relevant tests and quality checks.
5. Record important decisions, surprises, and remaining limitations in `docs/learning-log.md`.

File paths marked **planned** are suggested homes for future work. They do not necessarily exist yet; adjust them when the future design is reviewed. The repository has the functional incident path through Milestone 11's observability layer, a 20-case Milestone 12 evaluation set, a Milestone 13 regression gate, and initial Milestone 14 fault profiles. See the [engineering journal](engineering-journal.md) for the actual file-by-file record and verified limitations. The later milestones remain roadmap.

## The system in one picture

```text
operator/client
  -> FastAPI routes and Pydantic schemas
  -> deterministic run engine
  -> decision provider chooses bounded next work
  -> tool executor checks tool registration, permissions, validation and timeout
  -> simulated read and approved write tools return structured results
  -> SQLAlchemy repository records run transitions and steps in PostgreSQL
  -> API returns a response; tests verify behavior and persistence
```

The Gemini provider, policy, approval records, simulated side-effect tools, crash-safe execution intent, background worker, and observability layer now exist. Later milestones add evaluation and deployment. The application—not a model—must remain the owner of legal transitions, authorization, persistence, retries, and execution boundaries.

---

## Milestone 0 — Project charter

**Purpose:** Decide what is being built, why it is an agent platform rather than a chatbot, and which risks and features are deliberately out of scope.

**Workflow:** Requirements and non-goals are stated in the README; the architecture document describes the intended boundaries and flow; the ADR records why the initial scope was selected; the learning log records what was learned and what comes next.

**Files:**

- `README.md` — project purpose, initial scope, setup instructions, and commands. It is the entry point for a developer, not the complete design specification.
- `docs/architecture.md` — components and their responsibilities; it distinguishes deterministic application responsibilities from model suggestions and describes the state/persistence boundary.
- `docs/adr/0001-initial-scope.md` — an Architecture Decision Record. It preserves the decision, context, alternatives, and consequences so a future reader knows why scope was chosen.
- `docs/learning-log.md` — dated progress notes: what was built, what you understood, design decisions, and the next step.
- `production-ai-operations-agent-platform-plan.md` — the longer roadmap and engineering expectations. It is a plan; it is not evidence that every listed subsystem exists.

**Be able to explain:** why explicit state, bounded tools, approvals, and audit history make this different from a chat interface; what the model may suggest versus what the application must control; which operations are read-only and which could change production; why process memory is insufficient for a run that can pause or restart.

---

## Milestone 1 — Repository and engineering baseline

**Purpose:** Make the service reproducibly installable, runnable, testable, configurable, and connected to PostgreSQL before adding business behavior.

**Request/runtime workflow:** `pyproject.toml` defines the package and dependencies; `uv` creates/uses the environment; Docker Compose starts PostgreSQL; environment settings configure the app; Uvicorn imports `app.main:app`; FastAPI handles `/health` and `/ready`; pytest verifies behavior; Ruff and mypy catch style/type issues; CI repeats checks after a push.

**Files and infrastructure:**

- `pyproject.toml` — package metadata, runtime/development dependencies, and tool configuration. `uv.lock` (if present) pins resolved dependency versions reproducibly.
- `docker-compose.yml` — local PostgreSQL service, port mapping, and named data volume. The image is the packaged template; the container is the running instance; the volume keeps database files beyond a container lifecycle.
- `.env.example` — safe names and example values for required configuration. `.env` contains local values and must remain untracked.
- `.gitignore` — excludes virtual environments, local secrets, caches, and generated artifacts from Git.
- `alembic.ini` — Alembic configuration and migration-script location.
- `migrations/env.py` — connects Alembic to application metadata and the configured database when migrations run.
- `migrations/versions/*.py` — ordered, version-controlled schema changes. Alembic applies them to the database; the ORM class alone does not change an existing database.
- `.github/workflows/*.yml` (CI file, if present in the repository) — automates the agreed lint/type/test checks on GitHub. CI does not replace local verification.
- `src/app/main.py` — constructs the FastAPI application, loads configuration, includes routers, and provides health/readiness endpoints.
- `src/app/database.py` — database engine/session setup and configuration access. The engine manages connectivity/pooling; a Session represents a unit of database work.
- `tests/test_health.py` — endpoint behavior tests; readiness tests distinguish a live web process from a usable database connection.

**Concepts to explain:** virtual environments and dependency locking; image vs container vs volume; host/container port mapping; liveness vs readiness; environment configuration and secret hygiene; migration purpose; what CI proves and what it does not prove.

---

## Milestone 2 — Incidents and database foundations

**Purpose:** Learn the HTTP, validation, ORM, PostgreSQL, transaction, and migration basics using one real domain record.

**Create workflow:** client JSON -> request schema validation -> incident route -> SQLAlchemy Session -> ORM `Incident` -> `add`/`commit`/`refresh` -> response schema -> JSON response. Invalid input stops at schema validation; no insert occurs.

**Read/update workflow:** route receives an ID -> session fetches the row -> not found becomes 404 -> patch schema preserves omitted-vs-explicit-null meaning -> only supplied fields are assigned -> commit and refresh -> serialized response.

**Files:**

- `src/app/models.py` — ORM mappings for database tables, columns, constraints, and indexes. This describes desired schema to SQLAlchemy/Alembic; it is not itself an applied migration.
- `src/app/schemas.py` — Pydantic request/response contracts. Request schemas validate client data; response schemas control returned fields and use ORM attribute reading where needed.
- `src/app/routes/incidents.py` — incident HTTP endpoints and the application logic connecting validation, sessions, database operations, HTTP errors, and response models.
- `src/app/main.py` — includes the incidents router so its endpoints become part of the app.
- `migrations/versions/a7e280eb7b1e_create_incidents_table.py` — creates the incidents table and its initial database structure.
- `migrations/versions/b550434f6626_index_incidents_by_creation_time.py` — adds an index to support the creation-time ordering/query under study.
- `migrations/env.py` and `alembic.ini` — let Alembic compare metadata and apply migrations using the project configuration.
- `tests/test_incidents.py` — API behavior and PostgreSQL integration tests: valid create/read/update, validation failures, missing records, and persistence behavior.
- `tests/test_health.py` — continues to cover the base operational endpoints.

**Concepts to explain:** ORM model vs Pydantic schema vs migration; primary key, foreign key, nullability, uniqueness, defaults, and index; `commit` vs `refresh`; transaction and rollback; HTTP methods and status codes; PATCH omitted fields vs explicit `null`; why a small table may use a sequential scan despite an index; what `EXPLAIN ANALYZE` measures.

---

## Milestone 3 — Tool system

**Purpose:** Give the agent a small, explicit, testable set of capabilities without granting arbitrary function or shell access. Current tools are deterministic simulator/read tools, not live production integrations.

**Tool call workflow:** decision provider names a tool and arguments -> registry resolves only registered tools -> executor checks permission metadata against caller-granted permissions -> input validation -> timeout-bounded async execution -> output validation -> structured `ToolResult` or a controlled error. In a later milestone, the run repository will persist the result as part of an auditable step.

**Core files:**

- `src/app/tools/base.py` — abstract tool contract: the shape all tools must implement, including metadata, input validation, and asynchronous execution.
- `src/app/tools/metadata.py` — immutable descriptive contract for a tool: its stable name, description, argument/output expectations, and permission requirements.
- `src/app/tools/registry.py` — controlled name-to-tool lookup. Rejects duplicate registration and unknown names rather than allowing arbitrary callable lookup.
- `src/app/tools/executor.py` — common execution boundary. Applies permission checks, validation, timeout behavior, result checks, and error translation in one place.
- `src/app/tools/result.py` — standard structured result returned from execution, including the tool identity and output.
- `src/app/tools/errors.py` — tool-specific exception types so callers can distinguish controlled tool failures from unrelated errors.
- `src/app/tools/defaults.py` — constructs/registers the standard simulated tools as one reusable registry.
- `src/app/tools/service_health.py` — simulated health lookup for a named service.
- `src/app/tools/search_logs.py` — simulated log search using validated service/query/limit arguments.
- `src/app/tools/recent_deployments.py` — simulated deployment history lookup for a service.
- `src/app/tools/__init__.py` — package marker and, if defined, public exports for the tools package.

**Tests, file by file:**

- `tests/test_tool_contracts.py` — each tool satisfies the shared interface/contract.
- `tests/test_tool_metadata.py` — metadata defaults, validation, and immutability/read-only behavior.
- `tests/test_tool_registry.py` — registration, duplicate names, and unknown tool lookup.
- `tests/test_tool_executor.py` — executor-level permissions, argument/output validation, timeout, success, and exception handling.
- `tests/test_default_tools.py` — default registry composition and simulator behavior.
- `tests/test_service_health_tool.py` — health tool inputs and result cases.
- `tests/test_search_logs_tool.py` — log-search inputs, limits, and results.
- `tests/test_recent_deployments_tool.py` — deployment lookup inputs and results.

**Concepts to explain:** interface/abstract base class; why `@property` may expose read-only metadata; why async `execute` exists; registry vs executor; validation vs permission checking; timeout and output validation; why tool output is data and must not become trusted instructions; why a model requests a named contract instead of calling Python directly.

---

## Milestone 4 — Deterministic agent engine

**Purpose:** Prove workflow control and persistence before bringing in nondeterministic model behavior. The decision rules are intentionally simple; correct boundaries, legal state changes, and recoverability matter more.

**Current workflow:** API creates/reloads a run -> engine applies one deterministic step -> state transition table validates the edge -> repository persists the step/state -> in-memory object is updated only after persistence succeeds -> the API returns state/history. During context gathering, the engine selects a read tool and executes it. Planning produces a deterministic proposal. Approval can move the run into execution; current execution/verification are explicitly simulated and do not change an external system.

**Agent files:**

- `src/app/agent/states.py` — finite set of named workflow states. A state is the run's current position, not a free-form model response.
- `src/app/agent/transitions.py` — allowed-edge table and transition validation. It rejects illegal jumps and blocks continuation from terminal states.
- `src/app/agent/run.py` — in-memory domain object for one run: incident context, current state, transition history, tool results, and optional action proposal. It prepares and applies validated transitions.
- `src/app/agent/decision_provider.py` — deterministic stand-in for a future model. It chooses a tool and forms a typed action proposal from controlled rules.
- `src/app/agent/engine.py` — orchestrates a single step: consults the provider, calls tools through the executor, chooses a legal state transition, records reasons/payloads, and handles the approval decision. It owns workflow sequencing, not the database schema.
- `src/app/agent/repository.py` — database persistence boundary: creates and fetches runs, records transitions/steps, lists history, and reconstructs domain state after restart.
- `src/app/agent/__init__.py` — marks the agent package and may expose its supported public API.
- `src/app/models.py` — persistent `AgentRunRecord` and `RunStepRecord` ORM rows, alongside incidents.
- `src/app/schemas.py` — API-facing run/step response structures; keeps returned JSON independent from internal ORM/domain representation.
- `src/app/routes/runs.py` — HTTP endpoints to create, step, inspect a run, and inspect its steps; translates domain failures to appropriate HTTP errors.
- `src/app/main.py` — mounts the run router.
- `migrations/versions/42f41ea0209a_add_agent_run_tables.py` — creates persistent run and step tables. It must be reviewed and applied; an ORM model does not update PostgreSQL by itself.
- `tests/test_agent_transitions.py` — legal/illegal edges and terminal behavior.
- `tests/test_agent_run.py` — run object's transition/history behavior.
- `tests/test_decision_provider.py` — deterministic decision rules and proposal behavior.
- `tests/test_agent_engine.py` — orchestration behavior across steps, tools, proposals, and approval decisions without requiring database persistence.
- `tests/test_agent_repository.py` — persistence-level behavior against PostgreSQL.
- `tests/test_agent_engine_persistence.py` — integration of engine/repository and reload/resume behavior.
- `tests/test_runs.py` — HTTP/API behavior for run endpoints and response models.
- `tests/test_agent_execution_simulation.py` — approved proposal moves through simulated execution and verification to a terminal state; asserts it cannot continue afterward.

**Important limitation:** simulated execution is not a real rollback. A failure after a future external side effect succeeds but before its success is durably recorded could cause the action to be attempted again after restart. This crash-consistency/idempotency issue is deliberately not solved by a green test suite; Milestone 9 addresses it.

**Concepts to explain:** state vs event/history; legal transition ownership; why model output cannot pick arbitrary states; proposal vs approval vs execution; database as source of truth vs in-memory object; atomic DB update of run/step; why update memory after commit; reconstruction after process restart; crash window and duplicate side-effect risk; terminal state semantics.

---

## Milestone 5 — Model provider abstraction

**Purpose:** Add a real model behind an application-owned interface. Provider SDK data must not leak through the rest of the system.

**Files:**

- `src/app/agent/provider.py` — asynchronous provider protocol used by the engine. The engine depends on this behavior rather than a Gemini SDK type.
- `src/app/agent/decision_provider.py` — typed domain decisions, allowed tool/action names, argument validation, and the deterministic provider used by default and in tests.
- `src/app/agent/providers/gemini.py` — Gemini transport, provider-specific response schemas, bounded prompts, domain conversion, timeout handling, semantic evidence checks, latency measurement, token accounting, and structured model-call logs.
- `src/app/agent/providers/errors.py` — stable application exceptions for provider, timeout, and invalid-response failures.
- `src/app/agent/providers/factory.py` — selects deterministic or Gemini behavior from environment configuration.
- `src/app/agent/action_policy.py` — application-owned approval rule. Model output cannot state whether its own action requires approval.
- `src/app/routes/runs.py` — translates provider timeout and failure errors to HTTP 504 and 502 responses.
- `.env.example` — documents provider, model, timeout, logging, and key settings without containing a secret.
- `tests/test_decision_schemas.py` — unknown tools/actions, invalid arguments, extra fields, and bounded reasons.
- `tests/test_gemini_decision_provider.py` — prompt context, malformed/plain responses, service isolation, approval-field rejection, and evidence-grounded rollback validation.
- `tests/test_gemini_generator.py` — SDK response handling, timeout, exception translation, latency/token capture, and logging without network use.
- `tests/test_provider_factory.py` — deterministic default and Gemini configuration validation.
- `tests/test_gemini_live.py` — opt-in call against the configured Gemini API; skipped during ordinary test runs.
- `tests/test_runs.py` — API mapping for provider timeout and provider failure.

**Workflow:** engine requests a decision through `DecisionProvider` -> deterministic or Gemini implementation is selected from configuration -> Gemini receives bounded simulated incident context and an explicit response schema -> provider-specific output is parsed -> domain schema and semantic evidence checks run -> engine applies application-owned policy -> tool execution remains inside the application.

**Current operational status:** all offline behavior is verified. The opt-in live test reaches Google with a supported schema, but requires a valid `GEMINI_API_KEY` in local `.env`.

**Explain:** protocol vs implementation; why network methods are async; provider wire schema vs domain schema; structural validation vs semantic validation vs authorization; why the model cannot control approval; timeout and error translation; why prompts and responses are not logged; how model name, latency, and token counts are recorded; why deterministic mode remains the default for tests and CI.

---

## Milestone 6 — Policy engine

**Purpose:** Centrally decide whether an actor may use a tool/action, whether approval is needed, or whether it is forbidden. The model cannot set its own permission level.

**Files:** `src/app/policy.py` owns the server-side decision rules and actor/context contracts; `src/app/agent/engine.py` applies those decisions. `src/app/tools/simulator.py` provides shared synthetic state; `restart_service.py`, `rollback_deployment.py`, `service_health.py`, and `recent_deployments.py` write/read it; `defaults.py` assembles them.

**Tests:** `tests/test_policy_engine.py`, `tests/test_simulated_write_tools.py`, `tests/test_default_tools.py`, and `tests/test_agent_engine.py` cover risk decisions, prohibited/unknown tools, metadata manipulation, permission enforcement, simulator mutations, and engine behavior.

**Workflow:** typed proposal -> canonical tool and arguments resolved -> policy evaluates actor/run/tool/context -> ALLOW proceeds, REQUIRE_APPROVAL pauses, DENY terminates/blocks with reason -> audit result. Tool input validation, authorization, approval, and execution are distinct stages.

---

## Milestone 7 — Human approval workflow

**Purpose:** Pause dangerous operations for an authorized human and ensure that approval applies only to the exact action reviewed.

**Files:** `src/app/agent/approval.py` hashes a canonical action; `src/app/agent/repository.py` transactionally records requests and decisions; `src/app/agent/engine.py` verifies authorization again before execution. `src/app/models.py` and `migrations/versions/7f31d9c2a008_add_approvals.py` define the persisted record; `src/app/schemas.py` describes responses; `src/app/routes/approvals.py` handles protected endpoints; `src/app/main.py` mounts them.

**Tests:** `tests/test_approvals.py` covers key checks, request listing, approval, denial, expiry, replay, action mutation, ended runs, and simultaneous decisions; `tests/test_agent_engine_persistence.py` covers reload and durable decisions.

**Workflow:** policy requests approval -> immutable action/tool/arguments/run/hash are saved -> operator reviews record -> one authorized decision is recorded -> execution recomputes and compares the action hash -> only exact, valid, unexpired approval proceeds.

**Explain:** an LLM can request an action but cannot authorize it; what is frozen; how replay/tampering is detected; why the operator shared key is not enterprise identity; why the simulator and side-effect delivery are still not durable.

---

## Milestone 8 — End-to-end V1 functional path

**Purpose:** Demonstrate one complete, inspectable incident workflow through evidence, a proposed rollback, human approval, execution, verification, and resolution.

**Files:** `src/app/agent/engine.py`, `decision_provider.py`, `provider.py`, `transitions.py`, and `providers/gemini.py` coordinate three evidence calls and retain decision metadata; `src/app/agent/repository.py` records resolution and timestamps. `src/app/tools/defaults.py` allows a per-run simulator registry; `src/app/routes/runs.py` constructs one. `tests/test_incident_response_e2e.py`, `tests/test_agent_execution_simulation.py`, and `docs/demo-v1.md` prove and demonstrate the path. The [engineering journal](engineering-journal.md) has the full file map.

**Workflow:** create incident -> create run -> gather health/deployment/log evidence -> plan -> policy requires approval -> pause -> approve -> execute simulator action -> verify health -> resolve -> inspect all run steps and audit data.

**Explain:** every layer touched by the demo; what the audit trail proves; which behavior is deterministic; why verification can fail; why process restarts between a side effect and verification remain unsafe. The `v0.1.0` tag and demo recording have not been made on the current uncommitted worktree.

---

## Milestone 9 — Durable execution and crash recovery

**Purpose:** Prevent process failure from silently losing progress or blindly repeating unsafe side effects.

**Files now:** `src/app/models.py` and `migrations/versions/e4d8a9b6c201_add_action_executions.py` define the execution record. `src/app/agent/repository.py` commits intent before the tool and commits result/state/step together. `src/app/agent/engine.py` refuses duplicate/uncertain execution. `src/app/tools/metadata.py` defines retry classes, with each default tool classified in its own file. `src/app/tools/simulator.py` can rebuild synthetic state from persisted results. `src/app/routes/runs.py` exposes `GET /runs/{id}/execution`. `docs/failure-model.md` records the crash windows. Retry scheduling, external idempotency, and manual reconciliation remain future work.

**Tests now:** `tests/test_tool_metadata.py` checks classification and fail-closed defaults. `tests/test_agent_crash_recovery.py` injects stale intent, a tool effect without persisted result, a persistence failure after the effect, a tool error, and a transaction failure during the result/state/step write. `tests/test_incident_response_e2e.py` reconstructs a successful simulated result in a fresh engine. External-provider fault tests remain future work.

**Workflow:** persist intent/idempotency key -> execute simulated action once -> commit result/state/step together, or leave the outcome uncertain -> recover a committed success on restart or fail a stale intent without replaying the write. Retry classes document safety, but this version never automatically retries a write.

**Explain:** exactly-once limitations; idempotency and deduplication; safe vs unsafe retries; transaction/outbox/provider guarantees; each crash window and actual recovery behavior.

---

## Milestone 10 — Background execution

**Purpose:** Keep long agent work off the HTTP request while making jobs resumable and safe under worker failure/duplicate delivery.

**Files:** `src/app/models.py` and `migrations/versions/f21c67a4d092_add_run_jobs.py` define the job table. `src/app/jobs/queue.py` handles enqueue, lease claim, heartbeat, completion, and bounded failures. `src/app/jobs/worker.py` polls and advances one run state per claim. `src/app/agent/factory.py` shares engine construction between API and worker. `src/app/agent/repository.py` creates run/job atomically and resumes a paused job when approval commits. `src/app/routes/runs.py` retains manual runs and adds background start plus job inspection/enqueue endpoints. `src/app/schemas.py` defines the job response. `docs/background-execution.md` is the operating and failure guide.

**Tests:** `tests/test_job_queue.py` covers creation, concurrent claims, lease ownership/expiry, heartbeat, bounded retry, and approval gating. `tests/test_worker.py` covers approval pause/resume, safe simulated execution, transient provider failure, and graceful stop. These use PostgreSQL; they do not prove behavior against real operations APIs.

**Workflow:** background-run request atomically persists run and job -> worker claims a lease -> advances one run state while heartbeating -> requeues, pauses at approval, or completes -> expired leases can be reclaimed. The M9 execution intent prevents duplicate unsafe writes.

**Explain:** polling vs broker choice; why leases and heartbeats are needed; the difference between a job retry and retrying a dangerous tool; how approval pauses and resumes a job; graceful shutdown; one-job-per-worker concurrency; at-least-once delivery and exactly-once limitations; why Kafka is unnecessary here.

---

## Milestone 11 — Observability

**Purpose:** Make run behavior, latency, failures, and resource/cost use visible without leaking secrets or creating unusable metrics.

**Files:** `src/app/observability/logging.py` creates allowlisted JSON log events and context; `metrics.py` defines counters, histograms, and an active-run database gauge; `tracing.py` configures OpenTelemetry; `http.py` instruments route templates and exposes `/metrics`. `src/app/agent/engine.py`, `repository.py`, `providers/gemini.py`, `src/app/policy.py`, `src/app/tools/executor.py`, `src/app/routes/approvals.py`, and `src/app/jobs/worker.py` record events, spans, and metrics at their respective boundaries. `src/app/models.py` and `migrations/versions/68d4f7a92731_add_job_trace_context.py` carry a trace across the job handoff. `ops/prometheus/prometheus.yml` and `ops/grafana/operations-agent.json` define the local scrape targets and dashboard. `docs/observability.md` explains setup and limits.

**Tests:** `tests/test_observability.py` checks structured context, allowlisted fields, metrics without per-run labels, model and tool counters, approval-key exclusion, and an API-to-worker parent/child trace through PostgreSQL.

**Workflow:** HTTP span accepts trace context -> background-run request stores `traceparent` with its job -> worker extracts it -> agent step nests policy, model, tool, and persistence spans -> JSON events carry trace/run/step context -> separate API/worker metrics endpoints feed Prometheus -> Grafana summarizes rates and latency.

**Explain:** logs vs metrics vs traces vs the durable audit trail; why the worker needs persisted trace context; p50/p95/p99; histogram estimates and counter resets; high-cardinality labels; why IDs belong in logs/traces rather than metric labels; why keys, prompts, and raw arguments are excluded from telemetry.

---

## Milestone 12 — Evaluation framework (in progress)

**Purpose:** Measure agent quality on fixed scenarios instead of relying on anecdotes or subjective impressions.

**Files built:** `evals/scenarios/*.json` holds 20 complete fixtures; `src/app/evaluation/scenario.py` validates and loads them; `runner.py` seeds an isolated simulator and grades the actual agent; `metrics.py` aggregates observed measurements; `__main__.py` prints a JSON report; `src/app/tools/simulator.py`, `search_logs.py`, and `defaults.py` share seeded logs. `docs/evaluation.md` explains labels, metrics, and limits. Root-cause accuracy, cost, and recovery rates remain unmeasured rather than fabricated.

**Tests:** `tests/test_evaluation_scenarios.py` checks schema and dataset integrity; `tests/test_evaluation_runner.py` checks isolation, metrics, and the deliberately failing safety scenario.

**Workflow:** load scenario -> seed simulator -> execute agent -> collect trace/actions/outcome -> score objective measures and human-reviewed criteria -> generate comparable report.

**Explain:** ground truth vs evaluator judgment; scenario coverage/quality; success, unsafe-action, tool-use, latency, and cost metrics; why an LLM judge is not automatically ground truth; how the current 20/20 baseline guards against a rollback without corroborating evidence and why unmeasured values remain null.

---

## Milestone 13 — Evaluation regression gate (implemented for deterministic scenarios)

**Purpose:** Prevent prompt/model/tool/state changes from silently degrading agent behavior.

**Files:** `evals/baseline.json` lists reviewed IDs and thresholds; `src/app/evaluation/gate.py` validates and compares them; `__main__.py` exposes `--baseline`; `.github/workflows/ci.yml` enforces the comparison and uploads its report; `tests/test_evaluation_gate.py` checks missing cases and quality/safety regressions; `docs/evaluation.md` explains interpretation.

**Workflow:** code/model/prompt change -> run fixed evaluation set -> compare candidate to baseline -> fail or request review when meaningful thresholds regress -> publish the report as CI artifact.

**Explain:** why fixed and versioned test data matters; metric noise and thresholds; why compare safety separately from success/latency/cost; what a regression gate does not guarantee.

The current gate covers only 20 deterministic simulator cases. It does not prove the live Gemini path or production safety.

---

## Milestone 14 — Realistic incident simulator (in progress)

**Purpose:** Produce correlated, controllable service data so incident investigations test reasoning rather than hard-coded happy paths.

**Files built:** `src/app/tools/simulator.py` now contains nine service states, a dependency graph, synthetic metrics, ten fault profiles, and rollback behavior that heals only a deployment-caused fault. `src/app/evaluation/scenario.py` accepts a fault fixture; `runner.py` injects it into an isolated simulator; `evals/scenarios/09-*.json` through `20-*.json` exercise the fault families and adversarial evidence. Metrics and dependencies are not yet available as separate agent tools, and the provider does not predict structured root causes.

**Tests:** `tests/test_simulator_faults.py` covers cross-signal consistency, rollback recovery, unrelated-fault persistence, false alarms, and invalid setup. Evaluation tests check the 20-case set and its gate.

**Workflow:** scenario declares cause and initial conditions -> simulator creates realistic signals -> tools expose bounded evidence -> agent investigates -> simulated action changes environment -> verification reads resulting signals.

**Explain:** causal consistency between logs/metrics/deployments; seed reproducibility; misleading/incomplete evidence; why some scenarios should end in escalation.

---

## Milestone 15 — Security pass (in progress)

**Purpose:** Threat-model and mitigate realistic abuse across API, model, tools, approvals, data, and dependencies.

**Files built:** `docs/security.md` records trust boundaries, threats, mitigations, and residual risks; `src/app/security.py` protects incident/run/metrics endpoints with an optional shared key; `main.py` installs that middleware; `schemas.py` limits incident descriptions; `.env.example` lists the new setting; `tests/test_security.py` checks key enforcement and input bounds. This is not individual identity, rate limiting, dependency scanning, or public-deployment security.

**Tests:** `tests/test_security.py` covers the optional API gate and description limits. Earlier approval, policy, telemetry, and evaluation tests cover replay/tampering, authorization, secret exclusion, and one adversarial log case. Tenant isolation is not implemented.

**Workflow:** identify assets/trust boundaries/threats -> define mitigations -> enforce at server-side boundaries -> adversarial tests -> document residual risks.

**Explain:** untrusted incident/log data; prompt injection vs authorization; least privilege; approval replay; secret handling; project limitations without claiming enterprise security.

---

## Milestone 16 — Performance baseline (in progress)

**Purpose:** Establish repeatable measurements before attempting optimizations.

**Files built:** `src/app/benchmarks/control_plane.py` measures serial in-process health, readiness, pooled database, and deterministic agent paths and emits machine/sample/CPU/RSS metadata. `tests/test_control_plane_benchmark.py` checks percentile and no-database operation. `docs/performance.md` records one measured local baseline and limitations. Concurrent worker throughput, live model latency, and a before/after optimization experiment remain unmeasured.

**Workflow:** define control-plane and end-to-end workload -> fix environment and concurrency -> collect p50/p95/p99, throughput, CPU/memory/DB use -> archive raw results and methodology.

**Explain:** measurement boundaries; warm/cold behavior; percentile interpretation; why LLM and approval wait should be separated from server overhead where relevant.

---

## Milestone 17 — Fault injection (in progress)

**Purpose:** Check that known failures produce controlled, observable, recoverable outcomes.

**Files built:** `tests/test_fault_injection.py` injects a one-time provider timeout, read-tool timeout, malformed tool result, and database-readiness failure. `tests/test_vllm_provider.py` adds mocked 429/500, connection failure, malformed JSON, and partial/empty response cases; provider configuration rejects non-finite timeouts. Existing crash-recovery, approval, queue, Gemini adapter, and worker tests cover other modeled windows. `docs/failure-model.md` maps these cases to expected behavior and lists untested real process/network failures.

**Workflow:** inject one failure at a named boundary -> observe persisted state and returned error -> restart/retry if relevant -> assert no unauthorized action, silent corruption, or infinite loop.

**Explain:** fault injection vs ordinary happy-path testing; where to inject; expected recovery guarantees; how test fakes differ from real infrastructure tests.

---

## Milestone 18 — Compare runtime with LangGraph (isolated experiment)

**Purpose:** Make an informed framework decision after understanding the workflow and persistence problems in your own implementation.

**Files built:** `src/app/experiments/langgraph_workflow.py` contains an isolated graph using the existing policy, typed executor, and deterministic provider; it checkpoints in memory and exercises pause/approve/deny/verification. `tests/test_langgraph_experiment.py` verifies the workflow. `pyproject.toml` and `uv.lock` hold LangGraph in an optional `experiment` group; CI installs that group for the test. `docs/runtime-comparison.md` compares graph and custom runtime boundaries. The graph is not the API implementation and its in-memory checkpoint is not process-durable.

**Workflow:** implement same scenario in isolated graph -> compare checkpoint, interrupt/resume, persistence, recovery, complexity, and operational control -> document what framework owns and what remains yours.

**Explain:** checkpointing and resume semantics; abstraction benefits/costs; lock-in; why a framework does not automatically solve policy, idempotency, or application correctness.

---

## Milestone 19 — Model routing (in progress)

**Purpose:** Route work among model tiers based on measured quality, latency, and cost—not trendiness.

**Files built:** `src/app/agent/model_router.py` routes read-tool choice and action planning to separate providers, falls back to deterministic reads on known provider errors, and escalates on planning-provider failure. `src/app/agent/providers/factory.py` builds two separately configured Gemini models in `routed` mode; `.env.example` names the settings. `tests/test_model_router.py` and `tests/test_provider_factory.py` verify routing and configuration; `docs/model-routing.md` explains the unmeasured quality/cost trade-off. A live head-to-head evaluation still requires valid model access and billed usage data.

**Workflow:** classify bounded task -> choose eligible provider -> fallback only under explicit policy -> record model/cost/latency -> compare quality through evaluation.

**Explain:** routing signal and fallback; provider-specific capability differences; quality/cost trade-offs; how to prevent fallback loops or policy bypass.

---

## Milestone 20 — Self-hosted model with vLLM (adapter built; live run pending)

**Purpose:** Compare local inference with cloud providers and learn serving constraints, only after the provider boundary and evaluation suite exist.

**Files built:** `src/app/agent/providers/vllm.py` implements an asynchronous JSON-schema chat-completions adapter with URL/auth guardrails, response validation, timeout mapping, and token metadata. `providers/gemini.py` exposes a shared structured-decision parser while preserving the Gemini class; `providers/factory.py` adds `vllm` selection; `.env.example` lists settings; `httpx` is a direct dependency. `tests/test_vllm_provider.py` uses a mock transport. `docs/self-hosted-model.md` records the unmeasured live-serving work and security boundary. No GPU server, selected model, or live cloud/local comparison has been run.

**Workflow:** deploy model service locally -> connect via existing provider interface -> run identical evaluations/workloads -> record hardware, security boundary, reliability, and quality results.

**Explain:** serving vs model weights; GPU memory and throughput; structured output/tool reliability; network/auth protection; cloud/local cost assumptions.

---

## Optional Milestone 21 — Go gateway (planned)

**Purpose:** Add a Go service only when a measured, justified infrastructure boundary exists (for example auth, rate limits, streaming proxy, or tenant quotas).

**Suggested files (planned):** a separate `gateway/` Go module with its own tests/build/CI; API contract shared or documented in `docs/`; Python continues to own agent behavior and evaluation.

**Workflow:** gateway validates/authenticates/limits/routes HTTP -> Python service handles agent runtime -> trace/request identity propagates across services.

**Explain:** why a second language/process is justified; service boundary and failure modes; latency/operations cost; why rewriting working agent code is not the goal.

---

## Optional Milestone 22 — Multi-tenancy (planned)

**Purpose:** Isolate data, permissions, budgets, and audit records for multiple customers.

**Suggested files (planned):** tenant identity/security modules; `tenant_id` schema and migration on every tenant-owned record; query scoping in repository layer; tenant quotas/policies; `docs/tenancy.md`.

**Tests (planned):** cross-tenant read/write denial, approval isolation, cache isolation, quota enforcement, and audit separation.

**Workflow:** authenticate tenant -> attach trusted tenant identity to request -> scope every database/tool/policy operation -> record tenant audit context -> test adversarial cross-tenant access.

**Explain:** tenant isolation at every layer; why client-supplied tenant IDs are untrusted; migration/index implications; cache and metrics leakage risks.

---

## Optional Milestone 23 — Local Compose deployment (built; cloud deployment pending)

**Purpose:** Operate the application outside a developer laptop with managed configuration, health checks, database migrations, logs, and rollback planning.

**Files built:** `Dockerfile` packages the locked runtime and application without development dependencies; `.dockerignore` excludes local environment, tests, and Git history; `docker-compose.yml` starts PostgreSQL, a one-shot Alembic migration job, the API, and a worker with readiness ordering; `compose.smoke.yml` uses a fresh isolated database and no published host ports for the CI deployment check; `docs/deployment.md` describes startup, rollback caveats, and security limits. A cloud target, registry, image publishing, managed database, and live production verification are still pending.

**Workflow:** build immutable image -> scan/test -> configure secrets externally -> provision database -> apply migrations in controlled release -> start service/worker -> health-check/observe -> rollback safely when needed.

**Explain:** image immutability; secrets/config separation; readiness/liveness probes; graceful shutdown; schema compatibility during rollout; resource requests/limits and rolling update if using Kubernetes.

---

## Cross-milestone file map

| Concern | Main files | What flows through them |
|---|---|---|
| HTTP app | `src/app/main.py`, `src/app/routes/*.py`, `src/app/schemas.py` | request -> validation -> route -> response/error |
| Database | `src/app/database.py`, `src/app/models.py`, `migrations/*` | settings -> engine/session -> ORM metadata -> versioned schema changes |
| Tools | `src/app/tools/*.py` | registered capability -> permission/validation/timeout -> typed result/error |
| Agent | `src/app/agent/*.py` | current run -> decision -> legal transition -> tool/approval workflow |
| Persistence | `src/app/agent/repository.py`, ORM run/step records | domain transition -> transactional database write -> reloaded domain state |
| Tests | `tests/test_*.py` | pure unit behavior and DB/API integration behavior; each should state which boundary it verifies |
| Operations | `docker-compose.yml`, `.env.example`, CI workflow | reproducible local dependencies/configuration and automated checks |
| Learning/design | `README.md`, `docs/*.md`, ADRs, plan | onboarding, rationale, current architecture, known limits, next work |

## Explanation checklist for any subsystem

Before calling a subsystem understood, be ready to answer:

1. What problem does it solve, and what happens if it is removed?
2. What inputs does it accept, and what outputs/errors can it produce?
3. Which component owns the decision and which merely carries it out?
4. What state changes, where is it persisted, and what is the transaction boundary?
5. What happens on invalid input, timeout, duplicate request, or process crash?
6. Which tests prove the behavior, and which important behavior is not tested?
7. What trade-off or limitation remains, and what would change at ten times the load?
