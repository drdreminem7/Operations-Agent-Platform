import asyncio
import json
import logging

import pytest
from fastapi.testclient import TestClient
from google.genai import types
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import REGISTRY
from pydantic import BaseModel

from app.agent.factory import create_agent_engine
from app.agent.providers.gemini import GoogleGenAIStructuredOutputGenerator
from app.agent.repository import AgentRunRepository
from app.database import engine
from app.jobs.queue import RunJobQueue
from app.jobs.worker import RunWorker
from app.main import app
from app.observability.logging import bind_context, log_event
from app.observability.tracing import configure_tracing
from app.tools.defaults import create_default_registry
from app.tools.executor import ToolExecutor

client = TestClient(app)


class ExampleResponse(BaseModel):
    value: str


class FakeModelResponse:
    model_version: str | None = "test-model"
    usage_metadata: types.GenerateContentResponseUsageMetadata | None = (
        types.GenerateContentResponseUsageMetadata(
            prompt_token_count=12,
            candidates_token_count=7,
            total_token_count=19,
        )
    )

    @property
    def text(self) -> str | None:
        return '{"value":"ok"}'


class FakeModelCall:
    async def __call__(
        self,
        *,
        model: str,
        contents: str,
        config: types.GenerateContentConfig,
    ) -> FakeModelResponse:
        return FakeModelResponse()


def test_structured_log_includes_context_and_excludes_unapproved_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("app.observability.test")
    caplog.set_level(logging.INFO, logger=logger.name)

    with bind_context(run_id=42, incident_id=7, step_id=3, tool_name="search_logs"):
        with trace.get_tracer(__name__).start_as_current_span("test.log"):
            log_event(logger, logging.INFO, "tool_call_completed", outcome="success")

    payload = json.loads(caplog.records[-1].getMessage())
    assert payload["event"] == "tool_call_completed"
    assert payload["run_id"] == 42
    assert payload["incident_id"] == 7
    assert payload["step_id"] == 3
    assert payload["tool_name"] == "search_logs"
    assert len(payload["trace_id"]) == 32
    assert "secret-value" not in caplog.text
    with pytest.raises(ValueError, match="Unsupported log event field"):
        log_event(logger, logging.INFO, "unsafe", api_key="secret-value")


def test_metrics_expose_bounded_labels_without_identifiers() -> None:
    before = (
        REGISTRY.get_sample_value(
            "tool_calls_total", {"tool_name": "get_service_health"}
        )
        or 0
    )
    result = asyncio.run(
        ToolExecutor(create_default_registry()).execute(
            "get_service_health",
            {"service": "checkout"},
            granted_permissions=frozenset({"service:read"}),
        )
    )

    assert result.tool_name == "get_service_health"
    assert (
        REGISTRY.get_sample_value(
            "tool_calls_total", {"tool_name": "get_service_health"}
        )
        == before + 1
    )

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "agent_runs_total" in response.text
    assert "model_calls_total" in response.text
    assert "tool_calls_total" in response.text
    assert "approval_requests_total" in response.text
    assert "policy_denials_total" in response.text
    assert "active_runs" in response.text
    assert "run_id=" not in response.text
    assert "incident_id=" not in response.text
    assert len(response.headers["X-Trace-ID"]) == 32


def test_model_metrics_record_calls_duration_and_tokens() -> None:
    before_calls = REGISTRY.get_sample_value("model_calls_total") or 0
    before_input = REGISTRY.get_sample_value("model_input_tokens_total") or 0
    before_output = REGISTRY.get_sample_value("model_output_tokens_total") or 0
    generator = GoogleGenAIStructuredOutputGenerator(
        api_key="",
        model="test-model",
        generate_content=FakeModelCall(),
    )

    result = asyncio.run(
        generator.generate(prompt="Return a value.", response_schema=ExampleResponse)
    )

    assert result.text == '{"value":"ok"}'
    assert REGISTRY.get_sample_value("model_calls_total") == before_calls + 1
    assert REGISTRY.get_sample_value("model_input_tokens_total") == before_input + 12
    assert REGISTRY.get_sample_value("model_output_tokens_total") == before_output + 7
    assert REGISTRY.get_sample_value("model_call_duration_seconds_count") is not None


def test_approval_key_is_not_logged_or_traced(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("APPROVAL_API_KEY", "expected-approval-key")
    response = client.get(
        "/approvals/pending",
        headers={
            "X-Approval-Key": "secret-value",
            "X-Operator-ID": "test-operator",
        },
    )

    assert response.status_code == 403
    assert "secret-value" not in caplog.text


def test_background_worker_span_is_child_of_creation_request() -> None:
    exporter = InMemorySpanExporter()
    configure_tracing("operations-agent-api").add_span_processor(
        SimpleSpanProcessor(exporter)
    )
    incident = client.post(
        "/incidents",
        json={
            "title": "Checkout latency increased after deployment",
            "service": "checkout",
            "severity": "high",
        },
    )
    started = client.post(f"/incidents/{incident.json()['id']}/runs/background")
    assert started.status_code == 201
    run_id = started.json()["id"]
    job = RunJobQueue(engine).get_for_run(run_id)
    assert job is not None
    assert job.traceparent is not None

    repository = AgentRunRepository(engine)
    worker = RunWorker(
        RunJobQueue(engine),
        repository,
        create_agent_engine(repository),
        "trace-test-worker",
    )
    assert asyncio.run(worker.run_once(run_id=run_id))

    spans = exporter.get_finished_spans()
    request_span = next(
        span
        for span in spans
        if span.name == "POST /incidents/{incident_id}/runs/background"
    )
    worker_span = next(span for span in spans if span.name == "worker.job")
    agent_span = next(span for span in spans if span.name == "agent.step")
    assert worker_span.context is not None
    assert request_span.context is not None
    assert worker_span.parent is not None
    assert agent_span.parent is not None
    assert worker_span.context.trace_id == request_span.context.trace_id
    assert worker_span.parent.span_id == request_span.context.span_id
    assert agent_span.parent.span_id == worker_span.context.span_id
    assert all("secret-value" not in str(span.attributes) for span in spans)
