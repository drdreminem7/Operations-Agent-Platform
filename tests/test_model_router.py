import asyncio

import pytest

from app.agent.decision_provider import ActionProposal, ToolRequest
from app.agent.model_router import RoutedDecisionProvider
from app.agent.providers.errors import ModelProviderTimeoutError
from app.tools.result import ToolResult


class FakeProvider:
    def __init__(self, *, fail_read: bool = False, fail_plan: bool = False) -> None:
        self.fail_read = fail_read
        self.fail_plan = fail_plan
        self.read_calls = 0
        self.plan_calls = 0

    async def choose_tool(
        self,
        *,
        title: str,
        service: str,
        description: str | None = None,
        evidence: list[ToolResult] | None = None,
    ) -> ToolRequest:
        self.read_calls += 1
        if self.fail_read:
            raise ModelProviderTimeoutError("read timeout")
        return ToolRequest(
            tool_name="get_service_health",
            arguments={"service": service},
            reason="Inspect health",
        )

    async def propose_action(
        self, *, title: str, service: str, evidence: list[ToolResult]
    ) -> ActionProposal:
        self.plan_calls += 1
        if self.fail_plan:
            raise ModelProviderTimeoutError("planning timeout")
        return ActionProposal(
            action="escalate",
            arguments={"service": service},
            reason="Needs human review",
        )


def test_router_uses_separate_models_for_read_and_plan() -> None:
    triage = FakeProvider()
    planning = FakeProvider()
    router = RoutedDecisionProvider(triage, planning)

    request = asyncio.run(
        router.choose_tool(title="Checkout latency", service="checkout")
    )
    proposal = asyncio.run(
        router.propose_action(title="Checkout latency", service="checkout", evidence=[])
    )

    assert request.tool_name == "get_service_health"
    assert proposal.action == "escalate"
    assert (triage.read_calls, triage.plan_calls) == (1, 0)
    assert (planning.read_calls, planning.plan_calls) == (0, 1)


def test_read_model_timeout_uses_deterministic_fallback() -> None:
    router = RoutedDecisionProvider(FakeProvider(fail_read=True), FakeProvider())

    request = asyncio.run(
        router.choose_tool(title="Checkout latency", service="checkout")
    )

    assert request.tool_name == "get_service_health"
    assert request.reason == "The incident mentions latency, so inspect service health."


def test_planning_model_timeout_fails_closed_to_escalation() -> None:
    router = RoutedDecisionProvider(FakeProvider(), FakeProvider(fail_plan=True))

    proposal = asyncio.run(
        router.propose_action(
            title="Checkout latency after deploy", service="checkout", evidence=[]
        )
    )

    assert proposal.action == "escalate"
    assert proposal.arguments == {"service": "checkout"}


def test_unexpected_programming_error_is_not_a_provider_fallback() -> None:
    class BrokenProvider(FakeProvider):
        async def choose_tool(
            self,
            *,
            title: str,
            service: str,
            description: str | None = None,
            evidence: list[ToolResult] | None = None,
        ) -> ToolRequest:
            raise ValueError("bug")

    router = RoutedDecisionProvider(BrokenProvider(), FakeProvider())

    with pytest.raises(ValueError, match="bug"):
        asyncio.run(router.choose_tool(title="Checkout latency", service="checkout"))
