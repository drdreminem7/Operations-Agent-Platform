# Architecture

## System boundary

The platform receives an incident and coordinates an auditable investigation.
It currently reads simulated service health, logs, and deployment history, and
can restart or roll back a service in an in-memory simulator. Real production
integrations, runbooks, scaling, and configuration changes are not implemented.

## Main components

- **API layer:** accepts incidents, starts runs, exposes run state, and exposes
  approval operations.
- **Background worker:** polls a PostgreSQL job table, claims a timed lease,
  advances one run state, then requeues, pauses, or finishes the job.
- **Run coordinator:** owns workflow progression and persists a write intent
  before executing. Uncertain effects fail closed rather than being retried.
- **Agent runtime:** gathers context and produces a typed next decision.
- **State store:** persists incidents, runs, steps, approvals, jobs, and unique
  action execution records. Tool results and provider-call metadata are embedded in
  numbered run steps. Simulator state is rebuilt from saved synthetic results.
- **Tool registry and executor:** exposes explicit input/output contracts and
  executes only registered tools.
- **Policy engine:** determines whether a proposed action is permitted and
  whether approval is mandatory.
- **Approval system:** pauses dangerous work until an authorized human decides.
- **Audit layer:** run steps make behavior inspectable. A scenario-based
  evaluation framework is planned.
- **Observability layer:** JSON application events, Prometheus counters and
  histograms, and OpenTelemetry spans cover requests, run steps, decisions,
  tools, approvals, and persistence. Background jobs carry trace context.

## Deterministic boundary versus LLM boundary

The application, not the LLM, owns:

- legal state transitions;
- tool availability and schemas;
- permission and approval decisions;
- persistence and transaction boundaries;
- termination and the decision not to retry an uncertain write; a local
  idempotency key exists, but provider-enforced deduplication and budgets are
  future work;
- execution and verification of side effects;
- audit records.

The model may help interpret evidence and select among permitted next steps.
Its output must be structured, validated, bounded by available tools, and
treated as an untrusted proposal rather than an instruction to execute.

## Current state model

The implemented workflow includes repeated evidence gathering, approval,
execution, verification, and safe terminal states:

```text
NEW -> TRIAGE -> GATHER_CONTEXT <-> GATHER_CONTEXT -> PLAN
                                                  -> ACTION_SELECTED
                                                  -> AWAITING_APPROVAL
                                                  -> EXECUTING -> VERIFY
                                                     -> RESOLVED or FAILED

PLAN can also escalate or fail; denial escalates from AWAITING_APPROVAL.
```

The application owns legal transitions. The LLM cannot invent states or jump
directly to an unsafe side effect.

## Safety classification

Read-only evidence gathering is safe by default but still constrained by
timeouts, schemas, budgets, and audit logging. Actions that change service
state, deployments, configuration, capacity, or external records are
dangerous and require policy evaluation plus human approval before execution.

## Persistence requirement

Persistent state is required because a run spans multiple steps and may pause
for approval, fail halfway through, or need auditing. PostgreSQL is the source
of truth for workflow, approvals, and execution intent/results. The simulated
effect lives in process memory but can be reconstructed after a successful
result commit. If the effect occurred without a committed result, the outcome
is uncertain and no automatic write retry is allowed. See the
[failure model](failure-model.md).

The [background execution guide](background-execution.md) explains job leases,
approval pauses, bounded decision retries, and worker restart behavior.
The [observability guide](observability.md) distinguishes logs, metrics,
traces, and the durable audit trail.
