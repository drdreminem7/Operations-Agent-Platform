import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from opentelemetry import trace

_CONTEXT: ContextVar[dict[str, str | int] | None] = ContextVar(
    "log_context", default=None
)
_CONTEXT_FIELDS = frozenset(
    {"run_id", "incident_id", "step_id", "tool_name", "model_name"}
)
_EVENT_FIELDS = frozenset(
    {"state_before", "state_after", "outcome", "duration_ms", "error_type", "job_id"}
)


@contextmanager
def bind_context(**fields: str | int | None) -> Iterator[None]:
    context = (_CONTEXT.get() or {}).copy()
    for name, value in fields.items():
        if name not in _CONTEXT_FIELDS:
            raise ValueError(f"Unsupported log context field: {name}")
        if value is not None:
            context[name] = value
    token = _CONTEXT.set(context)
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **fields: str | int,
) -> None:
    if not logger.isEnabledFor(level):
        return
    if set(fields) - _EVENT_FIELDS:
        raise ValueError("Unsupported log event field")
    payload: dict[str, str | int] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event,
        **(_CONTEXT.get() or {}),
        **fields,
    }
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        payload["trace_id"] = format(span_context.trace_id, "032x")
    logger.log(level, json.dumps(payload, separators=(",", ":")))
