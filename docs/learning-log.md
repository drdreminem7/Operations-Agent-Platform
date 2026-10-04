# Learning Log

## 2026-09-23

### Built

Milestone 0 project charter, initial architecture, and scope ADR.

### What I understood

The system is a stateful execution platform, not a prompt-to-answer chatbot.
The application must constrain and verify model proposals, persist progress,
protect dangerous actions, and record an audit trail.

### Design decision

Begin with deterministic behavior and explicit boundaries before introducing a
real LLM or orchestration framework.

### Next step

Implement Milestone 1: the repository and engineering baseline.

## 2026-10-04

### Built

Milestones 1 through 5, including the FastAPI/PostgreSQL baseline, incident
CRUD, bounded tool system, durable deterministic run engine, and Gemini model
provider abstraction.

### What I understood

The engine depends on an application-owned provider protocol rather than a
vendor SDK. Model output must pass provider-specific parsing, domain schema
validation, semantic evidence checks, application policy, and tool validation
before anything executes.

### Design decision

Keep deterministic mode as the default for tests and CI. Gemini is enabled by
configuration, receives simulated data only, and cannot choose approval
requirements or execute tools directly.

### Remaining setup

Replace the local placeholder `GEMINI_API_KEY` with a valid Google AI Studio
key and rerun the opt-in live provider test.

### Next step

Implement Milestone 6: a policy engine that returns allow, require approval,
or deny independently of model output.
