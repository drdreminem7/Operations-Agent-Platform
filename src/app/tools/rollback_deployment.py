from .base import Tool
from .errors import ToolExecutionError
from .metadata import RetryClass, ToolMetadata
from .result import ToolResult
from .simulator import Simulator


class RollbackDeploymentTool(Tool):
    def __init__(self, simulator: Simulator) -> None:
        super().__init__(
            ToolMetadata(
                name="rollback_deployment",
                description="Roll back a simulated production deployment",
                read_only=False,
                required_permissions=frozenset({"deployments:write"}),
                timeout_seconds=2.0,
                retry_class=RetryClass.WRITE_NON_IDEMPOTENT,
            )
        )
        self._simulator = simulator

    def validate_input(self, arguments: dict[str, object]) -> dict[str, object]:
        service = arguments.get("service")
        version = arguments.get("version")
        if set(arguments) != {"service", "version"}:
            raise ToolExecutionError("service and version are required")
        if not isinstance(service, str) or not service.strip():
            raise ToolExecutionError("service must be non-empty")
        if not isinstance(version, str) or not version.strip():
            raise ToolExecutionError("version must be non-empty")
        return {"service": service.strip(), "version": version.strip()}

    async def execute(self, validated_input: dict[str, object]) -> ToolResult:
        service = validated_input["service"]
        version = validated_input["version"]
        if not isinstance(service, str) or not isinstance(version, str):
            raise ToolExecutionError("Validated service and version must be strings")
        output = self._simulator.rollback_deployment(service, version)
        return ToolResult(self.metadata.name, output)
