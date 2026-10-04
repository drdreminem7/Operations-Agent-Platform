from .base import Tool
from .errors import ToolExecutionError
from .metadata import RetryClass, ToolMetadata
from .result import ToolResult
from .simulator import Simulator


class GetServiceHealthTool(Tool):
    def __init__(self, simulator: Simulator | None = None) -> None:
        metadata = ToolMetadata(
            name="get_service_health",
            description="Get simulated health information for a service",
            read_only=True,
            required_permissions=frozenset({"service:read"}),
            timeout_seconds=2.0,
            retry_class=RetryClass.READ_ONLY_IDEMPOTENT,
        )
        super().__init__(metadata)
        self._simulator = simulator or Simulator()

    def validate_input(
        self,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        service = arguments.get("service")

        if not isinstance(service, str) or not service.strip():
            raise ToolExecutionError("service must be a non-empty string")

        service = service.strip()

        self._simulator.service_health(service)

        return {"service": service}

    async def execute(self, validated_input: dict[str, object]) -> ToolResult:
        service = validated_input.get("service")

        if not isinstance(service, str):
            raise ToolExecutionError("Validated input is missing service")

        health = self._simulator.service_health(service)

        return ToolResult(
            tool_name=self.metadata.name, output={"service": service, **health}
        )
