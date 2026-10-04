from .base import Tool
from .errors import ToolExecutionError
from .metadata import RetryClass, ToolMetadata
from .result import ToolResult
from .simulator import Simulator


class RestartServiceTool(Tool):
    def __init__(self, simulator: Simulator) -> None:
        super().__init__(
            ToolMetadata(
                name="restart_service",
                description="Restart a service in the simulator",
                read_only=False,
                required_permissions=frozenset({"service:write"}),
                timeout_seconds=2.0,
                retry_class=RetryClass.WRITE_NON_IDEMPOTENT,
            )
        )
        self._simulator = simulator

    def validate_input(self, arguments: dict[str, object]) -> dict[str, object]:
        service = arguments.get("service")
        if set(arguments) != {"service"} or not isinstance(service, str):
            raise ToolExecutionError("service must be the only argument")
        service = service.strip()
        if not service:
            raise ToolExecutionError("service must be non-empty")
        self._simulator.service_health(service)
        return {"service": service}

    async def execute(self, validated_input: dict[str, object]) -> ToolResult:
        service = validated_input["service"]
        if not isinstance(service, str):
            raise ToolExecutionError("Validated service must be a string")
        return ToolResult(self.metadata.name, self._simulator.restart_service(service))
