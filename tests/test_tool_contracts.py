from app.tools.errors import ToolExecutionError
from app.tools.result import ToolResult


def test_tool_result_stores_tool_name_and_output() -> None:
    result = ToolResult(
        tool_name="get_service_health",
        output={"service": "checkout", "status": "healthy"},
    )

    assert result.tool_name == "get_service_health"
    assert result.output == {"service": "checkout", "status": "healthy"}


def test_tool_execution_error_is_a_regular_exception() -> None:
    error = ToolExecutionError("Tool execution failed")

    assert isinstance(error, Exception)
    assert str(error) == "Tool execution failed"
