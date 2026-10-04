import asyncio

import pytest

from app.tools.errors import ToolExecutionError
from app.tools.service_health import GetServiceHealthTool


def test_service_health_tool_returns_simulated_health() -> None:
    tool = GetServiceHealthTool()
    validated_input = tool.validate_input({"service": "checkout"})

    result = asyncio.run(tool.execute(validated_input))

    assert result.tool_name == "get_service_health"
    assert result.output == {
        "service": "checkout",
        "status": "degraded",
        "latency_ms": 840,
    }


def test_service_health_tool_rejects_missing_service() -> None:
    tool = GetServiceHealthTool()

    with pytest.raises(ToolExecutionError):
        tool.validate_input({})


def test_service_health_tool_rejects_unknown_service() -> None:
    tool = GetServiceHealthTool()

    with pytest.raises(ToolExecutionError):
        tool.validate_input({"service": "unknown"})
