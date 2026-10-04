import json
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..agent.states import RunState
from ..tools.simulator import FaultKind


class IncidentFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    service: str = Field(min_length=1, max_length=100)
    severity: str = Field(min_length=1, max_length=20)
    description: str | None = None


class HealthFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy", "degraded"]
    latency_ms: int = Field(ge=0)


class DeploymentFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1)
    version: str = Field(min_length=1)
    environment: Literal["production", "staging"]
    status: Literal["successful", "rolled_back", "failed"]
    deployed_at: str = Field(min_length=1)


class LogFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1)
    level: Literal["error", "warning", "info"]
    message: str = Field(min_length=1)


class FaultFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: FaultKind
    service: str = Field(min_length=1)
    version: str | None = None

    @model_validator(mode="after")
    def check_version(self) -> Self:
        if self.kind == FaultKind.BAD_DEPLOYMENT and not self.version:
            raise ValueError("Bad deployment requires a version")
        if self.kind != FaultKind.BAD_DEPLOYMENT and self.version is not None:
            raise ValueError("Version only applies to a bad deployment")
        return self


class EnvironmentFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    health: dict[str, HealthFixture]
    deployments: list[DeploymentFixture]
    logs: list[LogFixture]
    faults: list[FaultFixture] = Field(default_factory=list)


class ExpectedOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_state: RunState | Literal["error", "incomplete"]
    required_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    proposed_action: str | None = None
    error_type: str | None = None
    approval_required: bool = False
    max_tool_calls: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_tool_sets(self) -> Self:
        if set(self.required_tools) & set(self.forbidden_tools):
            raise ValueError("Required and forbidden tools cannot overlap")
        if len(set(self.required_tools)) != len(self.required_tools):
            raise ValueError("Required tools must be unique")
        if len(set(self.forbidden_tools)) != len(self.forbidden_tools):
            raise ValueError("Forbidden tools must be unique")
        return self


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    incident: IncidentFixture
    environment: EnvironmentFixture
    root_cause: str = Field(min_length=1)
    approval_decision: Literal["approve", "deny", "pause"]
    expected: ExpectedOutcome
    max_steps: int = Field(default=12, ge=1, le=30)

    @model_validator(mode="after")
    def check_approval_expectation(self) -> Self:
        if self.approval_decision == "pause" and self.expected.approval_required:
            if self.expected.final_state != RunState.AWAITING_APPROVAL:
                raise ValueError("Paused approval must expect awaiting_approval")
        return self


def load_scenarios(directory: Path) -> list[Scenario]:
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError(f"No scenarios found in {directory}")
    scenarios: list[Scenario] = []
    seen: set[str] = set()
    for path in paths:
        scenario = Scenario.model_validate(json.loads(path.read_text()))
        if scenario.id in seen:
            raise ValueError(f"Duplicate scenario ID: {scenario.id}")
        seen.add(scenario.id)
        scenarios.append(scenario)
    return scenarios
