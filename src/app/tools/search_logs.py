from copy import deepcopy

from .base import Tool
from .errors import ToolExecutionError
from .metadata import RetryClass, ToolMetadata
from .result import ToolResult
from .simulator import Simulator


class SearchLogsTool(Tool):
    def __init__(self, simulator: Simulator | None = None) -> None:
        super().__init__(
            ToolMetadata(
                name="search_logs",
                description="Search simulated logs for a service and term",
                read_only=True,
                required_permissions=frozenset({"logs:read"}),
                timeout_seconds=2.0,
                retry_class=RetryClass.READ_ONLY_IDEMPOTENT,
            )
        )
        self._simulator = simulator or Simulator()

    def validate_input(self, arguments: dict[str, object]) -> dict[str, object]:
        service = arguments.get("service")
        query = arguments.get("query")

        if not isinstance(service, str) or not service.strip():
            raise ToolExecutionError("service must be a non-empty string")

        if not isinstance(query, str) or not query.strip():
            raise ToolExecutionError("query must be a non-empty string")

        return {"service": service.strip(), "query": query.strip()}

    async def execute(self, validated_input: dict[str, object]) -> ToolResult:
        service = validated_input.get("service")
        query = validated_input.get("query")

        if not isinstance(service, str) or not isinstance(query, str):
            raise ToolExecutionError("Validated input is missing service or query")

        matches = [
            deepcopy(log)
            for log in self._simulator.logs
            if log["service"] == service
            and query.casefold() in log["message"].casefold()
        ]

        return ToolResult(
            tool_name=self.metadata.name,
            output={"service": service, "query": query, "matches": matches},
        )
