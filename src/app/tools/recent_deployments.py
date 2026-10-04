from .base import Tool
from .errors import ToolExecutionError
from .metadata import RetryClass, ToolMetadata
from .result import ToolResult
from .simulator import Simulator


class GetRecentDeploymentsTool(Tool):
    def __init__(self, simulator: Simulator | None = None) -> None:
        super().__init__(
            ToolMetadata(
                name="get_recent_deployments",
                description="List recent simulated deployments",
                read_only=True,
                required_permissions=frozenset({"deployments:read"}),
                timeout_seconds=2.0,
                retry_class=RetryClass.READ_ONLY_IDEMPOTENT,
            )
        )
        self._simulator = simulator or Simulator()

    def validate_input(
        self,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        service = arguments.get("service")
        limit = arguments.get("limit", 5)

        if service is not None:
            if not isinstance(service, str) or not service.strip():
                raise ToolExecutionError(
                    "service must be a non-empty string when provided"
                )
            service = service.strip()

        # bool is a subclass of int in Python, so explicitly reject it.
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ToolExecutionError("limit must be an integer")

        if not 1 <= limit <= 10:
            raise ToolExecutionError("limit must be between 1 and 10")

        return {"service": service, "limit": limit}

    async def execute(self, validated_input: dict[str, object]) -> ToolResult:
        service = validated_input.get("service")
        limit = validated_input.get("limit")

        if service is not None and not isinstance(service, str):
            raise ToolExecutionError("Validated service must be a string")

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ToolExecutionError("Validated limit must be an integer")

        deployments = self._simulator.recent_deployments(service, limit)

        return ToolResult(
            tool_name=self.metadata.name,
            output={
                "service": service,
                "deployments": deployments,
            },
        )
