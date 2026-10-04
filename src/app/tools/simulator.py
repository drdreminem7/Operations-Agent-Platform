from copy import deepcopy
from enum import StrEnum

from .errors import ToolExecutionError
from .result import ToolResult


class FaultKind(StrEnum):
    BAD_DEPLOYMENT = "bad_deployment"
    DATABASE_SATURATION = "database_saturation"
    DOWNSTREAM_FAILURE = "downstream_failure"
    CPU_SATURATION = "cpu_saturation"
    MEMORY_LEAK = "memory_leak"
    MISCONFIGURATION = "misconfiguration"
    FEATURE_FLAG = "feature_flag"
    WORKER_BACKLOG = "worker_backlog"
    RATE_LIMIT = "rate_limit"
    FALSE_ALARM = "false_alarm"


class Simulator:
    def __init__(self) -> None:
        self.health: dict[str, dict[str, object]] = {
            "checkout": {"status": "degraded", "latency_ms": 840},
            "payments": {"status": "healthy", "latency_ms": 120},
            "api-gateway": {"status": "healthy", "latency_ms": 80},
            "checkout-api": {"status": "healthy", "latency_ms": 120},
            "payment-service": {"status": "healthy", "latency_ms": 90},
            "inventory-service": {"status": "healthy", "latency_ms": 95},
            "postgres": {"status": "healthy", "latency_ms": 20},
            "redis": {"status": "healthy", "latency_ms": 8},
            "worker-service": {"status": "healthy", "latency_ms": 110},
        }
        self.metrics: dict[str, dict[str, float | int]] = {
            service: {"cpu_percent": 20.0, "memory_percent": 30.0, "error_rate": 0.0}
            for service in self.health
        }
        self.dependencies = {
            "api-gateway": ["checkout-api"],
            "checkout-api": [
                "payment-service",
                "inventory-service",
                "postgres",
                "redis",
            ],
            "worker-service": ["postgres", "redis"],
        }
        self.faults: dict[str, FaultKind] = {"checkout": FaultKind.BAD_DEPLOYMENT}
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

    def inject_fault(
        self, kind: FaultKind, service: str, *, version: str | None = None
    ) -> None:
        if not service.strip():
            raise ValueError("Fault service must be non-empty")
        if kind == FaultKind.BAD_DEPLOYMENT and (
            version is None or not version.strip()
        ):
            raise ValueError("Bad deployment requires a version")
        self.health.setdefault(service, {"status": "healthy", "latency_ms": 100})
        metrics = self.metrics.setdefault(
            service,
            {"cpu_percent": 20.0, "memory_percent": 30.0, "error_rate": 0.0},
        )
        if kind == FaultKind.FALSE_ALARM:
            self.logs.append(
                {"service": service, "level": "info", "message": "Alert cleared"}
            )
            return

        self.faults[service] = kind
        self.health[service] = {"status": "degraded", "latency_ms": 900}
        metrics["error_rate"] = 0.25
        messages = {
            FaultKind.BAD_DEPLOYMENT: "error: requests timed out after release",
            FaultKind.DATABASE_SATURATION: "error: connection pool exhausted",
            FaultKind.DOWNSTREAM_FAILURE: "error: downstream provider unavailable",
            FaultKind.CPU_SATURATION: "error: CPU saturation increased latency",
            FaultKind.MEMORY_LEAK: "error: memory growth caused OOM",
            FaultKind.MISCONFIGURATION: "error: required configuration is missing",
            FaultKind.FEATURE_FLAG: "error: feature flag variant raised exception",
            FaultKind.WORKER_BACKLOG: "error: worker queue backlog exceeded limit",
            FaultKind.RATE_LIMIT: "error: request rate limited with 429",
        }
        self.logs.append(
            {"service": service, "level": "error", "message": messages[kind]}
        )
        if kind == FaultKind.BAD_DEPLOYMENT:
            assert version is not None
            self.deployments.insert(
                0,
                {
                    "service": service,
                    "version": version,
                    "environment": "production",
                    "status": "successful",
                    "deployed_at": "2026-09-29T09:30:00Z",
                },
            )
        elif kind == FaultKind.CPU_SATURATION:
            metrics["cpu_percent"] = 96.0
        elif kind == FaultKind.MEMORY_LEAK:
            metrics["memory_percent"] = 97.0
        elif kind == FaultKind.WORKER_BACKLOG:
            metrics["queue_depth"] = 2500
        elif kind == FaultKind.RATE_LIMIT:
            metrics["rate_limited_requests"] = 500
        elif kind in {FaultKind.DATABASE_SATURATION, FaultKind.DOWNSTREAM_FAILURE}:
            self.health["checkout-api"] = {"status": "degraded", "latency_ms": 760}
            self.logs.append(
                {
                    "service": "checkout-api",
                    "level": "error",
                    "message": f"error: {service} dependency is unavailable",
                }
            )
            if kind == FaultKind.DATABASE_SATURATION:
                metrics["active_connections"] = 100

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
                if self.faults.get(service) == FaultKind.BAD_DEPLOYMENT:
                    self.health[service] = {"status": "healthy", "latency_ms": 120}
                    self.metrics[service]["error_rate"] = 0.0
                    self.faults.pop(service, None)
                return {
                    "service": service,
                    "version": version,
                    "status": "rolled_back",
                    "simulated": True,
                }
        raise ToolExecutionError("No active simulated production deployment matches")
