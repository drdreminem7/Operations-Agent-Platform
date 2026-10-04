import asyncio

import pytest

from app.tools.search_logs import SearchLogsTool
from app.tools.simulator import FaultKind, Simulator


@pytest.mark.parametrize(
    ("kind", "service"),
    [
        (FaultKind.DATABASE_SATURATION, "postgres"),
        (FaultKind.DOWNSTREAM_FAILURE, "payment-service"),
        (FaultKind.CPU_SATURATION, "api-gateway"),
        (FaultKind.MEMORY_LEAK, "inventory-service"),
        (FaultKind.MISCONFIGURATION, "checkout-api"),
        (FaultKind.FEATURE_FLAG, "inventory-service"),
        (FaultKind.WORKER_BACKLOG, "worker-service"),
        (FaultKind.RATE_LIMIT, "api-gateway"),
    ],
)
def test_fault_profiles_produce_correlated_health_and_logs(
    kind: FaultKind, service: str
) -> None:
    simulator = Simulator()

    simulator.inject_fault(kind, service)

    assert simulator.service_health(service)["status"] == "degraded"
    assert simulator.metrics[service]["error_rate"] > 0
    assert any(
        log["service"] == service and log["level"] == "error"
        for log in simulator.logs
    )
    if kind in {FaultKind.DATABASE_SATURATION, FaultKind.DOWNSTREAM_FAILURE}:
        assert simulator.service_health("checkout-api")["status"] == "degraded"
        assert service in simulator.dependencies["checkout-api"]


def test_bad_deployment_can_be_rolled_back() -> None:
    simulator = Simulator()
    simulator.inject_fault(
        FaultKind.BAD_DEPLOYMENT, "inventory-service", version="3.0.0"
    )

    result = simulator.rollback_deployment("inventory-service", "3.0.0")

    assert result["status"] == "rolled_back"
    assert simulator.service_health("inventory-service")["status"] == "healthy"
    assert simulator.metrics["inventory-service"]["error_rate"] == 0.0
    assert "inventory-service" not in simulator.faults


def test_rollback_does_not_heal_an_unrelated_database_fault() -> None:
    simulator = Simulator()
    simulator.inject_fault(FaultKind.DATABASE_SATURATION, "postgres")
    simulator.deployments.insert(
        0,
        {
            "service": "checkout-api",
            "version": "4.2.0",
            "environment": "production",
            "status": "successful",
            "deployed_at": "2026-09-29T09:30:00Z",
        },
    )

    simulator.rollback_deployment("checkout-api", "4.2.0")

    assert simulator.service_health("checkout-api")["status"] == "degraded"


def test_invalid_bad_deployment_does_not_mutate_simulator() -> None:
    simulator = Simulator()
    before = simulator.service_health("inventory-service")

    with pytest.raises(ValueError, match="requires a version"):
        simulator.inject_fault(FaultKind.BAD_DEPLOYMENT, "inventory-service")

    assert simulator.service_health("inventory-service") == before
    assert "inventory-service" not in simulator.faults


def test_false_alarm_stays_healthy() -> None:
    simulator = Simulator()

    simulator.inject_fault(FaultKind.FALSE_ALARM, "payment-service")

    assert simulator.service_health("payment-service")["status"] == "healthy"
    assert "payment-service" not in simulator.faults


def test_log_tool_reads_injected_fault_evidence() -> None:
    simulator = Simulator()
    simulator.inject_fault(FaultKind.MISCONFIGURATION, "checkout-api")
    tool = SearchLogsTool(simulator)

    result = asyncio.run(
        tool.execute({"service": "checkout-api", "query": "error"})
    )

    matches = result.output["matches"]
    assert isinstance(matches, list)
    assert any(
        isinstance(match, dict) and "configuration" in match["message"]
        for match in matches
    )
