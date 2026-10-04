import pytest

from app.tools.errors import ToolExecutionError
from app.tools.registry import ToolRegistry
from app.tools.service_health import GetServiceHealthTool


def test_registry_registers_and_retrieves_tool() -> None:
    registry = ToolRegistry()
    tool = GetServiceHealthTool()

    registry.register(tool)

    assert registry.get("get_service_health") is tool


def test_registry_rejects_duplicate_tool_name() -> None:
    registry = ToolRegistry()
    registry.register(GetServiceHealthTool())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(GetServiceHealthTool())


def test_registry_rejects_unknown_tool_name() -> None:
    registry = ToolRegistry()

    with pytest.raises(ToolExecutionError, match="Unknown tool"):
        registry.get("delete_everything")


def test_registry_lists_tool_metadata() -> None:
    registry = ToolRegistry()
    tool = GetServiceHealthTool()
    registry.register(tool)

    assert registry.list_tools() == [tool.metadata]
