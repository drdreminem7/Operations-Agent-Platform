import asyncio
import logging
from time import perf_counter

from opentelemetry import trace

from ..observability.logging import bind_context, log_event
from ..observability.metrics import (
    tool_call_duration_seconds,
    tool_call_failures_total,
    tool_calls_total,
)
from .base import Tool
from .errors import ToolExecutionError
from .registry import ToolRegistry
from .result import ToolResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, object],
        *,
        granted_permissions: frozenset[str] = frozenset(),
    ) -> ToolResult:
        tool = self._registry.get(tool_name)
        name = tool.metadata.name
        started = perf_counter()
        tool_calls_total.labels(name).inc()
        with (
            bind_context(tool_name=name),
            tracer.start_as_current_span("tool.execute") as span,
        ):
            span.set_attribute("tool.name", name)
            span.set_attribute("tool.read_only", tool.metadata.read_only)
            try:
                result = await self._execute(tool, arguments, granted_permissions)
            except Exception as error:
                tool_call_failures_total.labels(name).inc()
                log_event(
                    logger,
                    logging.WARNING,
                    "tool_call_failed",
                    error_type=type(error).__name__,
                )
                raise
            finally:
                tool_call_duration_seconds.labels(name).observe(
                    perf_counter() - started
                )
            log_event(logger, logging.INFO, "tool_call_completed")
            return result

    async def _execute(
        self,
        tool: Tool,
        arguments: dict[str, object],
        granted_permissions: frozenset[str],
    ) -> ToolResult:
        tool_name = tool.metadata.name
        missing_permissions = tool.metadata.required_permissions - granted_permissions

        if missing_permissions:
            missing = ",".join(sorted(missing_permissions))
            raise ToolExecutionError(f"Missing required permissions: {missing}")

        try:
            validated_input = tool.validate_input(arguments)
        except ToolExecutionError:
            raise
        except Exception as error:
            raise ToolExecutionError(
                f"Input validation failed for tool: {tool_name}"
            ) from error

        try:
            result = await asyncio.wait_for(
                tool.execute(validated_input),
                timeout=tool.metadata.timeout_seconds,
            )
        except TimeoutError as error:
            raise ToolExecutionError(f"Tool timed out: {tool_name}") from error
        except ToolExecutionError:
            raise
        except Exception as error:
            raise ToolExecutionError(f"Tool execution failed: {tool_name}") from error

        if not isinstance(result, ToolResult):
            raise ToolExecutionError(f"Tool returned an invalid result: {tool_name}")

        if result.tool_name != tool.metadata.name:
            raise ToolExecutionError(
                "Result tool name does not match the registered tool"
            )

        if not isinstance(result.output, dict) or not all(
            isinstance(key, str) for key in result.output
        ):
            raise ToolExecutionError("Tool output must be a string-keyed dictionary")

        return result
