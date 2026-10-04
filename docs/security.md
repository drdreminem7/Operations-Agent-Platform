# Security model

This project controls simulated tools, not production infrastructure. Its
security goal is to keep model output and incident evidence inside explicit
application-owned boundaries. It is not an enterprise identity or multi-tenant
system.

| Threat | Boundary and current mitigation | Residual risk |
|---|---|---|
| Unauthorized incident/run access | Set `API_ACCESS_KEY` and send `X-API-Key`; the API checks it on `/incidents`, `/runs`, and `/metrics`. | Key is optional for local development, shared by all callers, and has no per-user audit identity or rate limit. |
| Unauthorized approval | `/approvals` requires `APPROVAL_API_KEY` and an operator label. Approval is bound to a run, action, and argument hash; replay and expiry are checked in PostgreSQL. | The operator label is not authenticated identity; stolen shared keys can be reused until rotated. |
| Prompt injection in incidents or logs | Incident/log text is data supplied to a constrained provider. The application validates named tool requests and actions, checks policy, and rejects rollback without corroborating service evidence. | A live model may still make poor decisions; the 20-case deterministic suite does not prove prompt-injection resistance. |
| Tool privilege escalation | Tool metadata and policy rules are server-owned; unknown tools are denied; the executor checks granted permissions and validates inputs and outputs. | Simulator results do not prove real external systems have equivalent authorization. |
| Unbounded input and resource use | Incident descriptions are limited to 4,000 characters; other incident fields have length limits. Provider calls and tools have timeouts; worker retries are bounded. | No request-body byte limit, per-client quota, or distributed rate limiter is installed. |
| Approval tampering or duplicate side effects | Canonical action hashes, row locks, single-use decisions, execution intent, and fail-closed uncertain states protect the simulated workflow. | A remote system would need its own idempotency key and reconciliation procedure. |
| Sensitive telemetry | Application-owned logs and spans use allowlisted fields and omit prompts, raw tool arguments, request headers, and API keys. | Third-party logs and collector access require separate configuration and review. |
| SQL injection and dependency compromise | SQLAlchemy uses bound parameters for application queries; CI installs from `uv.lock`, runs tests, lint, type checks, and evaluation. | Locking dependencies is not a vulnerability scan; dependency update and image scanning policy remain to be added. |

For local use, leave `API_ACCESS_KEY` blank and bind Uvicorn to localhost. If
you expose the API, set distinct random values for `API_ACCESS_KEY` and
`APPROVAL_API_KEY`, use TLS and a network access control in front of it, and
protect the metrics endpoint. The current shared-key scheme is not sufficient
for public deployment or tenant isolation. `/health`, `/ready`, API docs, and
the OpenAPI schema remain public to anyone who can reach the process; network
policy must account for them.
