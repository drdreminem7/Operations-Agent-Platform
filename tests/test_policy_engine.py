import pytest

from app.policy import (
    RULES,
    SYSTEM_ACTOR,
    PermissionLevel,
    PolicyActor,
    PolicyContext,
    PolicyEngine,
    PolicyOutcome,
    PolicyRule,
)


def decide(
    tool_name: str,
    arguments: dict[str, object],
    *,
    actor: PolicyActor = SYSTEM_ACTOR,
    context: PolicyContext | None = None,
) -> PolicyOutcome:
    return PolicyEngine().evaluate(
        actor=actor,
        run_service="checkout",
        tool_name=tool_name,
        arguments=arguments,
        context=context or PolicyContext(),
    ).outcome


def test_read_tool_is_allowed() -> None:
    assert decide("get_service_health", {"service": "checkout"}) == PolicyOutcome.ALLOW


def test_rollback_requires_approval() -> None:
    assert decide(
        "rollback_deployment", {"service": "checkout", "version": "2.4.1"}
    ) == PolicyOutcome.REQUIRE_APPROVAL


def test_low_risk_write_is_configurable() -> None:
    arguments: dict[str, object] = {"service": "checkout"}
    assert decide("restart_service", arguments) == PolicyOutcome.REQUIRE_APPROVAL
    context = PolicyContext(allow_low_risk_without_approval=True)
    assert decide("restart_service", arguments, context=context) == PolicyOutcome.ALLOW


def test_unknown_and_cross_service_tools_are_denied() -> None:
    assert decide("unknown", {"service": "checkout"}) == PolicyOutcome.DENY
    assert decide("get_service_health", {"service": "payments"}) == PolicyOutcome.DENY


def test_actor_without_permission_is_denied() -> None:
    actor = PolicyActor(identifier="viewer", permissions=frozenset())
    assert (
        decide("get_service_health", {"service": "checkout"}, actor=actor)
        == PolicyOutcome.DENY
    )


def test_write_is_forbidden_outside_simulation_even_with_approval() -> None:
    context = PolicyContext(environment="production")
    assert (
        decide("rollback_deployment", {"service": "checkout"}, context=context)
        == PolicyOutcome.DENY
    )


def test_administrative_rule_is_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        RULES,
        "admin_reset",
        PolicyRule(PermissionLevel.ADMIN, "admin:reset"),
    )
    actor = PolicyActor("admin", frozenset({"admin:reset"}))
    assert (
        decide("admin_reset", {"service": "checkout"}, actor=actor)
        == PolicyOutcome.DENY
    )


def test_caller_supplied_risk_metadata_cannot_lower_server_policy() -> None:
    arguments: dict[str, object] = {
        "service": "checkout",
        "version": "2.4.1",
        "risk": "read",
    }
    assert decide("rollback_deployment", arguments) == PolicyOutcome.REQUIRE_APPROVAL
