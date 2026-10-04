import asyncio

from app.tools.defaults import create_default_registry
from app.tools.executor import ToolExecutor


def test_default_registry_contains_all_five_tools() -> None:
    registry = create_default_registry()

    tool_names = {metadata.name for metadata in registry.list_tools()}

    assert tool_names == {
        "get_service_health",
        "search_logs",
        "get_recent_deployments",
        "restart_service",
        "rollback_deployment",
    }


def test_default_tools_run_through_executor_with_permissions() -> None:
    executor = ToolExecutor(create_default_registry())

    async def run_tools() -> None:
        health = await executor.execute(
            "get_service_health",
            {"service": "checkout"},
            granted_permissions=frozenset({"service:read"}),
        )
        assert health.output["status"] == "degraded"

        logs = await executor.execute(
            "search_logs",
            {"service": "checkout", "query": "payment"},
            granted_permissions=frozenset({"logs:read"}),
        )
        assert logs.output["query"] == "payment"

        deployments = await executor.execute(
            "get_recent_deployments",
            {"service": "checkout", "limit": 1},
            granted_permissions=frozenset({"deployments:read"}),
        )
        assert deployments.output["service"] == "checkout"

    asyncio.run(run_tools())
