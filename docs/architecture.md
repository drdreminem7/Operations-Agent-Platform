# Architecture

## System boundary

The platform receives an incident and coordinates an auditable investigation.
It may read simulated operational data such as logs, metrics, deployments,
service health, dependencies, configuration, runbooks, and incident history.
Later it may perform controlled actions such as restarting a service,
rolling back a deployment, changing a feature flag, scaling workers, or
creating an incident note.

## Main components

- **API layer:** accepts incidents, starts runs, exposes run state, and exposes
  approval operations.
- **Run coordinator:** owns workflow progression and durable execution.
- **Agent runtime:** gathers context and produces a typed next decision.
- **State store:** persists incidents, runs, steps, tool executions, approvals,
  model calls, and audit events.
- **Tool registry and executor:** exposes explicit input/output contracts and
  executes only registered tools.
- **Policy engine:** determines whether a proposed action is permitted and
  whether approval is mandatory.
- **Approval system:** pauses dangerous work until an authorized human decides.
- **Audit and evaluation layers:** make behavior inspectable and measurable.

## Deterministic boundary versus LLM boundary

The application, not the LLM, owns:

- legal state transitions;
- tool availability and schemas;
- permission and approval decisions;
- persistence and transaction boundaries;
- retries, idempotency, budgets, and termination;
- execution and verification of side effects;
- audit records.

The model may help interpret evidence and select among permitted next steps.
Its output must be structured, validated, bounded by available tools, and
treated as an untrusted proposal rather than an instruction to execute.

## Initial state model

The intended workflow is:

```text
NEW -> TRIAGE -> GATHER_CONTEXT -> PLAN -> ACTION_SELECTED
                                      |             |
                                      |             +-> AWAITING_APPROVAL
                                      |                             |
                                      +-> ESCALATED                 v
                                      |                         EXECUTING
                                      +-> FAILED                     |
                                                                  v
                                                               VERIFY
                                                              /      \
                                                         RESOLVED   GATHER_CONTEXT
```

The application owns legal transitions. The LLM cannot invent states or jump
directly to an unsafe side effect.

## Safety classification

Read-only evidence gathering is safe by default but still constrained by
timeouts, schemas, budgets, and audit logging. Actions that change service
state, deployments, configuration, capacity, or external records are
dangerous and require policy evaluation plus human approval before execution.

## Persistence requirement

Persistent state is required because an agent run spans multiple steps and may
pause for approval, fail halfway through, or need to be replayed and audited.
The database is the source of truth for workflow state; in-memory context is
only an optimization.
