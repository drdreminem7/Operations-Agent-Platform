# Model routing

`DECISION_PROVIDER=routed` sends read-tool choice to one configured Gemini model
and action planning to another. Set `GEMINI_API_KEY`,
`GEMINI_TRIAGE_MODEL`, and `GEMINI_PLANNING_MODEL` in `.env`; the model names
must be nonempty and distinct. The existing `deterministic` and single-model
`gemini` modes remain available.

The router is intentionally asymmetric. If the triage model reports a known
provider error or timeout, a deterministic provider may select a read-only
tool. If the planning model fails, the router proposes escalation for human
review; it never substitutes a weaker model's rollback proposal. Unexpected
programming errors are not swallowed. The engine still validates proposals,
requires corroborating evidence for rollback, applies server-owned policy,
and enforces approval before execution. Gemini decision traces retain the
actual model name, latency, and observed token counts.

`src/app/agent/model_router.py` owns the stage routing and failure behavior;
`src/app/agent/providers/factory.py` builds two independently configured
Gemini providers. `tests/test_model_router.py` tests stage selection and both
fallback paths; `tests/test_provider_factory.py` checks configuration.

No live routed run has been measured. The deterministic evaluation suite does
not compare the two models' quality, latency, or price, and the project does
not contain a verified pricing table. Before claiming routing is better than
one model, run the same reviewed incidents with both configurations and
compare safety and outcome first, then model-call counts, latency, token use,
and actual billed cost. A failed action-planning call increasing escalation is
a deliberate safety trade-off, not evidence of improved quality.
