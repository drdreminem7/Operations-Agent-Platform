import asyncio
from typing import cast

import pytest

from app.tools.base import Tool
from app.tools.errors import ToolExecutionError
from app.tools.executor import ToolExecutor
from app.tools.metadata import ToolMetadata
from app.tools.registry import ToolRegistry
from app.tools.result import ToolResult
from app.tools.search_logs import SearchLogsTool


class EchoTool(Tool):
    def __init__(
        self,
        *,
        timeout_seconds: float = 1.0,
        delay_seconds: float = 0.0,
        should_crash: bool = False,
        wrong_result_name: bool = False,
        bad_output: bool = False,
    ) -> None:
        super().__init__(
            ToolMetadata(
                name="echo",
                description="Returns the supplied value",
                read_only=True,
                required_permissions=frozenset({"echo:read"}),
                timeout_seconds=timeout_seconds,
            )
        )
        self.delay_seconds = delay_seconds
        self.should_crash = should_crash
        self.wrong_result_name = wrong_result_name
        self.bad_output = bad_output

    def validate_input(
        self,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        value = arguments.get("value")
        if not isinstance(value, str):
            raise ToolExecutionError("value must be a string")
        return {"value": value}

    async def execute(
        self,
        validated_input: dict[str, object],
    ) -> ToolResult:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.should_crash:
            raise RuntimeError("simulated internal failure")

        result_name = "other" if self.wrong_result_name else self.metadata.name

        output: object
        if self.bad_output:
            output = ["not", "a", "dictionary"]
        else:
            output = {"value": validated_input["value"]}

        return ToolResult(
            tool_name=result_name,
            output=cast(dict[str, object], output),
        )


def make_executor(tool: Tool | None = None) -> ToolExecutor:
    registry = ToolRegistry()
    if tool is not None:
        registry.register(tool)
    return ToolExecutor(registry)


def test_executor_runs_registered_tool() -> None:
    tool = EchoTool()
    executor = make_executor(tool)

    result = asyncio.run(
        executor.execute(
            "echo",
            {"value": "hello"},
            granted_permissions=frozenset({"echo:read"}),
        )
    )

    assert result == ToolResult(tool_name="echo", output={"value": "hello"})


def test_executor_rejects_unknown_tool() -> None:
    executor = make_executor()

    with pytest.raises(ToolExecutionError, match="Unknown tool"):
        asyncio.run(executor.execute("missing", {}))


def test_executor_rejects_missing_permission() -> None:
    executor = make_executor(EchoTool())

    with pytest.raises(ToolExecutionError, match="Missing required permissions"):
        asyncio.run(executor.execute("echo", {"value": "hello"}))


def test_executor_wraps_invalid_input() -> None:
    executor = make_executor(EchoTool())

    with pytest.raises(ToolExecutionError, match="value must be a string"):
        asyncio.run(
            executor.execute(
                "echo",
                {},
                granted_permissions=frozenset({"echo:read"}),
            )
        )


def test_executor_enforces_timeout() -> None:
    tool = EchoTool(timeout_seconds=0.01, delay_seconds=0.1)
    executor = make_executor(tool)

    with pytest.raises(ToolExecutionError, match="timed out"):
        asyncio.run(
            executor.execute(
                "echo",
                {"value": "hello"},
                granted_permissions=frozenset({"echo:read"}),
            )
        )


def test_executor_wraps_internal_failure() -> None:
    executor = make_executor(EchoTool(should_crash=True))

    with pytest.raises(ToolExecutionError, match="execution failed"):
        asyncio.run(
            executor.execute(
                "echo",
                {"value": "hello"},
                granted_permissions=frozenset({"echo:read"}),
            )
        )


def test_executor_rejects_result_for_wrong_tool() -> None:
    executor = make_executor(EchoTool(wrong_result_name=True))

    with pytest.raises(ToolExecutionError, match="does not match"):
        asyncio.run(
            executor.execute(
                "echo",
                {"value": "hello"},
                granted_permissions=frozenset({"echo:read"}),
            )
        )


def test_executor_runs_search_logs_with_permission() -> None:
    registry = ToolRegistry()
    registry.register(SearchLogsTool())
    executor = ToolExecutor(registry)

    result = asyncio.run(
        executor.execute(
            "search_logs",
            {"service": "checkout", "query": "payment"},
            granted_permissions=frozenset({"logs:read"}),
        )
    )

    assert result.tool_name == "search_logs"
    assert result.output["service"] == "checkout"
    assert result.output["query"] == "payment"


def test_executor_rejects_search_logs_without_permission() -> None:
    registry = ToolRegistry()
    registry.register(SearchLogsTool())
    executor = ToolExecutor(registry)

    with pytest.raises(ToolExecutionError, match="Missing required permissions"):
        asyncio.run(
            executor.execute(
                "search_logs",
                {"service": "checkout", "query": "payment"},
            )
        )


def test_executor_rejects_non_dictionary_output() -> None:
    executor = make_executor(EchoTool(bad_output=True))

    with pytest.raises(ToolExecutionError, match="string-keyed dictionary"):
        asyncio.run(
            executor.execute(
                "echo",
                {"value": "hello"},
                granted_permissions=frozenset({"echo:read"}),
            )
        )
