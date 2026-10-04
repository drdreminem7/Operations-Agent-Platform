import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.agent.decision_provider import DeterministicDecisionProvider, ToolRequest
from app.agent.engine import AgentEngine
from app.agent.run import AgentRun
from app.agent.states import RunState
from app.main import app
from app.tools.base import Tool
from app.tools.defaults import create_default_registry
from app.tools.errors import ToolExecutionError
from app.tools.executor import ToolExecutor
from app.tools.metadata import RetryClass, ToolMetadata
from app.tools.registry import ToolRegistry
from app.tools.result import ToolResult


class TimeoutOnceProvider(DeterministicDecisionProvider):
    def __init__(self) -> None:
        self.calls = 0

    async def choose_tool(
        self,
        *,
        title: str,
        service: str,
        description: str | None = None,
        evidence: list[ToolResult] | None = None,
    ) -> ToolRequest:
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("Injected provider timeout")
        return await super().choose_tool(
            title=title, service=service, description=description, evidence=evidence
        )


class FaultyHealthTool(Tool):
    def __init__(self, mode: str) -> None:
        super().__init__(
            ToolMetadata(
                name="get_service_health",
                description="Injected health fault",
                read_only=True,
                required_permissions=frozenset({"service:read"}),
                timeout_seconds=0.01,
                retry_class=RetryClass.READ_ONLY_IDEMPOTENT,
            )
        )
        self.mode = mode

    def validate_input(self, arguments: dict[str, object]) -> dict[str, object]:
        return arguments

    async def execute(self, validated_input: dict[str, object]) -> ToolResult:
        if self.mode == "timeout":
            await asyncio.sleep(0.05)
        return ToolResult(tool_name="wrong_tool", output={"status": "healthy"})


def context_run() -> AgentRun:
    run = AgentRun(incident_id=1, title="Checkout latency", service="checkout")
    run.transition_to(RunState.TRIAGE)
    run.transition_to(RunState.GATHER_CONTEXT)
    return run


def test_provider_timeout_does_not_commit_a_transition() -> None:
    provider = TimeoutOnceProvider()
    agent = AgentEngine(provider, ToolExecutor(create_default_registry()))
    run = context_run()

    with pytest.raises(TimeoutError, match="Injected"):
        asyncio.run(agent.step(run))

    assert run.current_state == RunState.GATHER_CONTEXT
    assert len(run.history) == 2
    assert run.tool_results == []
    assert provider.calls == 1
    assert asyncio.run(agent.step(run)) == RunState.PLAN
    assert len(run.tool_results) == 1


@pytest.mark.parametrize(
    ("mode", "message"),
    [("timeout", "timed out"), ("wrong_name", "does not match")],
)
def test_tool_fault_does_not_advance_run(mode: str, message: str) -> None:
    registry = ToolRegistry()
    registry.register(FaultyHealthTool(mode))
    agent = AgentEngine(DeterministicDecisionProvider(), ToolExecutor(registry))
    run = context_run()

    with pytest.raises(ToolExecutionError, match=message):
        asyncio.run(agent.step(run))

    assert run.current_state == RunState.GATHER_CONTEXT
    assert len(run.history) == 2
    assert run.tool_results == []


def test_database_failure_returns_not_ready_without_exposing_connection() -> None:
    with patch("app.routes.health.engine.connect", side_effect=SQLAlchemyError()):
        response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"status": "not_ready", "database": "unavailable"}
    }
