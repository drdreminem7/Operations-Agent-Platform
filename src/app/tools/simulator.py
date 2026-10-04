from copy import deepcopy

from .errors import ToolExecutionError
from .result import ToolResult


class Simulator:
    def __init__(self) -> None:
        self.health: dict[str, dict[str, object]] = {
            "checkout": {"status": "degraded", "latency_ms": 840},
            "payments": {"status": "healthy", "latency_ms": 120},
        }
        self.deployments: list[dict[str, str]] = [
            {
                "service": "checkout",
                "version": "2.4.1",
                "environment": "production",
                "status": "successful",
                "deployed_at": "2026-09-29T09:30:00Z",
            },
            {
                "service": "payments",
                "version": "1.8.0",
                "environment": "production",
                "status": "rolled_back",
                "deployed_at": "2026-09-28T16:45:00Z",
            },
            {
                "service": "checkout",
                "version": "2.4.0",
                "environment": "staging",
                "status": "successful",
                "deployed_at": "2026-09-28T14:10:00Z",
            },
        ]
        self.logs: list[dict[str, str]] = [
            {
                "service": "checkout",
                "level": "error",
                "message": "Payment provider timed out",
            },
            {
                "service": "checkout",
                "level": "info",
                "message": "Checkout request completed",
            },
            {
                "service": "payments",
                "level": "warning",
                "message": "Retrying payment provider request",
            },
        ]

    @classmethod
    def from_results(cls, results: list[ToolResult]) -> "Simulator":
        simulator = cls()
        for result in results:
            if result.tool_name == "rollback_deployment":
                service = result.output.get("service")
                version = result.output.get("version")
                if (
                    result.output.get("status") != "rolled_back"
                    or not isinstance(service, str)
                    or not isinstance(version, str)
                ):
                    raise ToolExecutionError("Saved rollback result is invalid")
                simulator.rollback_deployment(service, version)
            elif result.tool_name == "restart_service":
                service = result.output.get("service")
                if result.output.get("status") != "restarted" or not isinstance(
                    service, str
                ):
                    raise ToolExecutionError("Saved restart result is invalid")
                simulator.restart_service(service)
        return simulator

    def service_health(self, service: str) -> dict[str, object]:
        health = self.health.get(service)
        if health is None:
            raise ToolExecutionError(f"Unknown simulated service: {service}")
        return deepcopy(health)

    def recent_deployments(
        self, service: str | None, limit: int
    ) -> list[dict[str, str]]:
        return [
            deepcopy(deployment)
            for deployment in self.deployments
            if service is None or deployment["service"] == service
        ][:limit]

    def restart_service(self, service: str) -> dict[str, object]:
        self.service_health(service)
        self.health[service] = {"status": "healthy", "latency_ms": 120}
        return {"service": service, "status": "restarted", "simulated": True}

    def rollback_deployment(self, service: str, version: str) -> dict[str, object]:
        for deployment in self.deployments:
            if (
                deployment["service"] == service
                and deployment["version"] == version
                and deployment["environment"] == "production"
                and deployment["status"] == "successful"
            ):
                deployment["status"] = "rolled_back"
                self.health[service] = {"status": "healthy", "latency_ms": 120}
                return {
                    "service": service,
                    "version": version,
                    "status": "rolled_back",
                    "simulated": True,
                }
        raise ToolExecutionError("No active simulated production deployment matches")
