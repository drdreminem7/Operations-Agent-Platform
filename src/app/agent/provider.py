from typing import Protocol

from ..tools.result import ToolResult
from .decision_provider import ActionProposal, ToolRequest


class DecisionProvider(Protocol):
    async def choose_tool(
        self,
        *,
        title: str,
        service: str,
        description: str | None = None,
        evidence: list[ToolResult] | None = None,
    ) -> ToolRequest: ...

    async def propose_action(
        self,
        *,
        title: str,
        service: str,
        evidence: list[ToolResult],
    ) -> ActionProposal: ...
