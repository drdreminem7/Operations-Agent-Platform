from ..tools.result import ToolResult
from .decision_provider import (
    ActionProposal,
    DeterministicDecisionProvider,
    ToolRequest,
)
from .provider import DecisionProvider
from .providers.errors import ModelProviderError


class RoutedDecisionProvider:
    def __init__(
        self,
        triage: DecisionProvider,
        planning: DecisionProvider,
        read_fallback: DecisionProvider | None = None,
    ) -> None:
        self._triage = triage
        self._planning = planning
        self._read_fallback = read_fallback or DeterministicDecisionProvider()

    async def choose_tool(
        self,
        *,
        title: str,
        service: str,
        description: str | None = None,
        evidence: list[ToolResult] | None = None,
    ) -> ToolRequest:
        try:
            return await self._triage.choose_tool(
                title=title,
                service=service,
                description=description,
                evidence=evidence,
            )
        except ModelProviderError:
            return await self._read_fallback.choose_tool(
                title=title,
                service=service,
                description=description,
                evidence=evidence,
            )

    async def propose_action(
        self,
        *,
        title: str,
        service: str,
        evidence: list[ToolResult],
    ) -> ActionProposal:
        try:
            return await self._planning.propose_action(
                title=title, service=service, evidence=evidence
            )
        except ModelProviderError:
            return ActionProposal(
                action="escalate",
                arguments={"service": service},
                reason="Planning provider unavailable; escalate for human review.",
            )
