from datetime import datetime

from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..models import AgentRunRecord

agent_runs_total = Counter("agent_runs_total", "Agent runs created")
agent_runs_completed_total = Counter(
    "agent_runs_completed_total", "Runs resolved or escalated"
)
agent_runs_failed_total = Counter("agent_runs_failed_total", "Runs failed")
agent_run_duration_seconds = Histogram(
    "agent_run_duration_seconds",
    "Run duration",
    buckets=(1, 5, 10, 30, 60, 300, 900, 3600, 86400, float("inf")),
)

model_calls_total = Counter("model_calls_total", "Model calls")
model_call_duration_seconds = Histogram(
    "model_call_duration_seconds",
    "Model call duration",
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, float("inf")),
)
model_input_tokens_total = Counter("model_input_tokens_total", "Model input tokens")
model_output_tokens_total = Counter("model_output_tokens_total", "Model output tokens")
model_errors_total = Counter("model_errors_total", "Model errors")

tool_calls_total = Counter("tool_calls_total", "Tool calls", ["tool_name"])
tool_call_duration_seconds = Histogram(
    "tool_call_duration_seconds", "Tool call duration", ["tool_name"]
)
tool_call_failures_total = Counter(
    "tool_call_failures_total", "Tool call failures", ["tool_name"]
)

approval_requests_total = Counter("approval_requests_total", "Approval requests")
approval_denials_total = Counter("approval_denials_total", "Approval denials")
policy_denials_total = Counter("policy_denials_total", "Policy denials")

active_runs = Gauge("active_runs", "Runs not in a terminal state")
http_requests_total = Counter(
    "http_requests_total", "HTTP requests", ["method", "route", "status"]
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "HTTP request duration", ["method", "route"]
)


def configure_active_runs(db_engine: Engine) -> None:
    def count_active() -> float:
        try:
            with Session(db_engine) as session:
                count = session.scalar(
                    select(func.count())
                    .select_from(AgentRunRecord)
                    .where(AgentRunRecord.status.in_(("running", "awaiting_approval")))
                )
                return float(count or 0)
        except SQLAlchemyError:
            return float("nan")

    active_runs.set_function(count_active)


def record_run_terminal(
    state: str, started_at: datetime | None, finished_at: datetime | None
) -> None:
    if state == "failed":
        agent_runs_failed_total.inc()
    else:
        agent_runs_completed_total.inc()
    if started_at is not None and finished_at is not None:
        agent_run_duration_seconds.observe(
            max(0.0, (finished_at - started_at).total_seconds())
        )
