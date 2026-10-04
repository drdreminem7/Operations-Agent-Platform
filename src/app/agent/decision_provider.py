from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..tools.result import ToolResult
from .evidence import supports_rollback

ToolName = Literal[
    "get_service_health",
    "search_logs",
    "get_recent_deployments",
]
ActionName = Literal["rollback_deployment", "escalate"]


class DecisionTrace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    latency_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


def _string_argument(arguments: dict[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _exact_arguments(
    arguments: dict[str, object],
    expected: set[str],
) -> None:
    if set(arguments) != expected:
        names = ", ".join(sorted(expected))
        raise ValueError(f"arguments must contain exactly: {names}")


class ToolRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: ToolName
    arguments: dict[str, object]
    reason: str = Field(min_length=1, max_length=500)
    trace: DecisionTrace | None = None

    @model_validator(mode="after")
    def validate_arguments(self) -> Self:
        if self.tool_name == "get_service_health":
            _exact_arguments(self.arguments, {"service"})
            _string_argument(self.arguments, "service")
        elif self.tool_name == "search_logs":
            _exact_arguments(self.arguments, {"query", "service"})
            _string_argument(self.arguments, "service")
            _string_argument(self.arguments, "query")
        else:
            _exact_arguments(self.arguments, {"limit", "service"})
            _string_argument(self.arguments, "service")
            limit = self.arguments.get("limit")
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise ValueError("limit must be an integer")
            if not 1 <= limit <= 10:
                raise ValueError("limit must be between 1 and 10")
        return self


class ActionProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: ActionName
    arguments: dict[str, object]
    reason: str = Field(min_length=1, max_length=500)
    trace: DecisionTrace | None = None

    @model_validator(mode="after")
    def validate_arguments(self) -> Self:
        if self.action == "rollback_deployment":
            _exact_arguments(self.arguments, {"service", "version"})
            _string_argument(self.arguments, "service")
            _string_argument(self.arguments, "version")
        else:
            _exact_arguments(self.arguments, {"service"})
            _string_argument(self.arguments, "service")
        return self


class DeterministicDecisionProvider:
    async def choose_tool(
        self,
        *,
        title: str,
        service: str,
        description: str | None = None,
        evidence: list[ToolResult] | None = None,
    ) -> ToolRequest:
        incident_text = f"{title} {description or ''}".casefold()

        title_text = title.casefold()
        if "latency" in title_text and "deploy" in title_text:
            seen = {result.tool_name for result in evidence or []}
            if "get_service_health" not in seen:
                return ToolRequest(
                    tool_name="get_service_health",
                    arguments={"service": service},
                    reason="Inspect service health before assessing the deployment.",
                )
            if "get_recent_deployments" not in seen:
                return ToolRequest(
                    tool_name="get_recent_deployments",
                    arguments={"service": service, "limit": 5},
                    reason="Inspect recent deployments for a correlated change.",
                )
            return ToolRequest(
                tool_name="search_logs",
                arguments={"service": service, "query": "timed out"},
                reason="Inspect error logs for supporting evidence.",
            )

        if "latency" in incident_text:
            return ToolRequest(
                tool_name="get_service_health",
                arguments={"service": service},
                reason="The incident mentions latency, so inspect service health.",
            )

        if "deploy" in incident_text:
            return ToolRequest(
                tool_name="get_recent_deployments",
                arguments={"service": service, "limit": 5},
                reason=(
                    "The incident mentions a deployment, so inspect recent deployments."
                ),
            )

        return ToolRequest(
            tool_name="search_logs",
            arguments={"service": service, "query": "error"},
            reason="No latency clue was found, so search the service logs for errors.",
        )

    async def propose_action(
        self,
        *,
        title: str,
        service: str,
        evidence: list[ToolResult],
    ) -> ActionProposal:
        incident_text = title.casefold()

        if "deploy" in incident_text:
            for result in evidence:
                if result.tool_name != "get_recent_deployments":
                    continue

                deployments = result.output.get("deployments")
                if not isinstance(deployments, list):
                    continue

                for deployment in deployments:
                    if not isinstance(deployment, dict):
                        continue
                    if deployment.get("service") != service:
                        continue
                    if deployment.get("environment") != "production":
                        continue
                    if deployment.get("status") != "successful":
                        continue

                    version = deployment.get("version")
                    if not isinstance(version, str):
                        continue

                    if not supports_rollback(
                        evidence, service=service, version=version
                    ):
                        continue

                    return ActionProposal(
                        action="rollback_deployment",
                        arguments={"service": service, "version": version},
                        reason=(
                            "A recent production deployment exists and the "
                            "incident mentions a deployment; propose rollback "
                            "for human review."
                        ),
                    )

        return ActionProposal(
            action="escalate",
            arguments={"service": service},
            reason="The simulated evidence is insufficient to safely act.",
        )
