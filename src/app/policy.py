import logging
from dataclasses import dataclass
from enum import StrEnum

from opentelemetry import trace

from .observability.logging import log_event
from .observability.metrics import policy_denials_total

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class PermissionLevel(StrEnum):
    READ = "read"
    WRITE_LOW_RISK = "write_low_risk"
    WRITE_HIGH_RISK = "write_high_risk"
    ADMIN = "admin"


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyActor:
    identifier: str
    permissions: frozenset[str]


@dataclass(frozen=True)
class PolicyContext:
    environment: str = "simulation"
    allow_low_risk_without_approval: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    reason: str
    granted_permissions: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PolicyRule:
    level: PermissionLevel
    permission: str


RULES: dict[str, PolicyRule] = {
    "get_service_health": PolicyRule(PermissionLevel.READ, "service:read"),
    "search_logs": PolicyRule(PermissionLevel.READ, "logs:read"),
    "get_recent_deployments": PolicyRule(PermissionLevel.READ, "deployments:read"),
    "restart_service": PolicyRule(PermissionLevel.WRITE_LOW_RISK, "service:write"),
    "rollback_deployment": PolicyRule(
        PermissionLevel.WRITE_HIGH_RISK, "deployments:write"
    ),
}


SYSTEM_ACTOR = PolicyActor(
    identifier="agent",
    permissions=frozenset(rule.permission for rule in RULES.values()),
)


class PolicyEngine:
    def evaluate(
        self,
        *,
        actor: PolicyActor,
        run_service: str,
        tool_name: str,
        arguments: dict[str, object],
        context: PolicyContext,
    ) -> PolicyDecision:
        with tracer.start_as_current_span("policy.evaluate") as span:
            span.set_attribute("tool.name", tool_name)
            decision = self._evaluate(
                actor=actor,
                run_service=run_service,
                tool_name=tool_name,
                arguments=arguments,
                context=context,
            )
            span.set_attribute("policy.outcome", decision.outcome.value)
            if decision.outcome == PolicyOutcome.DENY:
                policy_denials_total.inc()
                log_event(logger, logging.WARNING, "policy_denied", outcome="deny")
            return decision

    def _evaluate(
        self,
        *,
        actor: PolicyActor,
        run_service: str,
        tool_name: str,
        arguments: dict[str, object],
        context: PolicyContext,
    ) -> PolicyDecision:
        rule = RULES.get(tool_name)
        if rule is None:
            return PolicyDecision(PolicyOutcome.DENY, "Tool is not in the policy")

        if rule.level == PermissionLevel.ADMIN:
            return PolicyDecision(
                PolicyOutcome.DENY, "Administrative tools are forbidden"
            )

        if rule.permission not in actor.permissions:
            return PolicyDecision(PolicyOutcome.DENY, "Actor lacks tool permission")

        if arguments.get("service") != run_service:
            return PolicyDecision(PolicyOutcome.DENY, "Tool service differs from run")

        if rule.level != PermissionLevel.READ and context.environment != "simulation":
            return PolicyDecision(PolicyOutcome.DENY, "Writes are simulation-only")

        granted = frozenset({rule.permission})
        if rule.level == PermissionLevel.READ:
            return PolicyDecision(PolicyOutcome.ALLOW, "Read-only tool", granted)

        if (
            rule.level == PermissionLevel.WRITE_LOW_RISK
            and context.allow_low_risk_without_approval
        ):
            return PolicyDecision(
                PolicyOutcome.ALLOW, "Configured low-risk write", granted
            )

        return PolicyDecision(
            PolicyOutcome.REQUIRE_APPROVAL,
            "Human approval required for simulated write",
            granted,
        )
