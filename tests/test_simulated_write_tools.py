import asyncio
from typing import cast

import pytest

from app.tools.defaults import create_default_registry
from app.tools.errors import ToolExecutionError
from app.tools.executor import ToolExecutor


def test_rollback_changes_shared_simulator_health_and_deployment() -> None:
    executor = ToolExecutor(create_default_registry())

    async def run() -> None:
        before = await executor.execute(
            "get_service_health",
            {"service": "checkout"},
            granted_permissions=frozenset({"service:read"}),
        )
        assert before.output["status"] == "degraded"

        result = await executor.execute(
            "rollback_deployment",
            {"service": "checkout", "version": "2.4.1"},
            granted_permissions=frozenset({"deployments:write"}),
        )
        assert result.output["status"] == "rolled_back"

        after = await executor.execute(
            "get_service_health",
            {"service": "checkout"},
            granted_permissions=frozenset({"service:read"}),
        )
        assert after.output["status"] == "healthy"

        deployments = await executor.execute(
            "get_recent_deployments",
            {"service": "checkout"},
            granted_permissions=frozenset({"deployments:read"}),
        )
        rows = cast(list[dict[str, str]], deployments.output["deployments"])
        assert rows[0]["status"] == "rolled_back"

    asyncio.run(run())


def test_simulated_write_requires_executor_permission() -> None:
    executor = ToolExecutor(create_default_registry())
    with pytest.raises(ToolExecutionError, match="Missing required permissions"):
        asyncio.run(executor.execute("restart_service", {"service": "checkout"}))


def test_rollback_rejects_stale_version() -> None:
    executor = ToolExecutor(create_default_registry())
    with pytest.raises(ToolExecutionError, match="No active simulated"):
        asyncio.run(
            executor.execute(
                "rollback_deployment",
                {"service": "checkout", "version": "2.3.0"},
                granted_permissions=frozenset({"deployments:write"}),
            )
        )
