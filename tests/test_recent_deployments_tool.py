import asyncio

import pytest

from app.tools.errors import ToolExecutionError
from app.tools.recent_deployments import GetRecentDeploymentsTool


def test_recent_deployments_returns_all_by_default() -> None:
    tool = GetRecentDeploymentsTool()
    validated_input = tool.validate_input({})

    result = asyncio.run(tool.execute(validated_input))

    assert result.tool_name == "get_recent_deployments"
    assert result.output["service"] is None
    assert result.output["deployments"] == [
        {
            "service": "checkout",
            "version": "2.4.1",
            "environment": "production",
            "status": "successful",
            "deployed_at": "2026-09-29T09:30:00Z",
        },
        {
            "service": "payments",
            "version": "1.8.0",
            "environment": "production",
            "status": "rolled_back",
            "deployed_at": "2026-09-28T16:45:00Z",
        },
        {
            "service": "checkout",
            "version": "2.4.0",
            "environment": "staging",
            "status": "successful",
            "deployed_at": "2026-09-28T14:10:00Z",
        },
    ]


def test_recent_deployments_filters_by_service_and_limit() -> None:
    tool = GetRecentDeploymentsTool()
    validated_input = tool.validate_input({"service": "checkout", "limit": 1})

    result = asyncio.run(tool.execute(validated_input))

    assert result.output["service"] == "checkout"
    assert result.output["deployments"] == [
        {
            "service": "checkout",
            "version": "2.4.1",
            "environment": "production",
            "status": "successful",
            "deployed_at": "2026-09-29T09:30:00Z",
        }
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        {"service": ""},
        {"service": 123},
        {"limit": 0},
        {"limit": 11},
        {"limit": "2"},
        {"limit": True},
    ],
)
def test_recent_deployments_rejects_invalid_input(
    arguments: dict[str, object],
) -> None:
    tool = GetRecentDeploymentsTool()

    with pytest.raises(ToolExecutionError):
        tool.validate_input(arguments)
