from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    service: str = Field(min_length=1, max_length=100)
    severity: str = Field(min_length=1, max_length=20)
    description: str | None = Field(default=None, max_length=4000)
    started_at: datetime | None = None
    status: str = Field(default="open", min_length=1, max_length=20)


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    service: str
    severity: str
    description: str | None
    status: str
    started_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IncidentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    service: str | None = Field(default=None, min_length=1, max_length=100)
    severity: str | None = Field(default=None, min_length=1, max_length=20)
    description: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, min_length=1, max_length=20)
    started_at: datetime | None = None

    @field_validator("title", "service", "severity", "status", mode="before")
    @classmethod
    def reject_null_for_required_fields(cls, value: object) -> object:
        if value is None:
            raise ValueError("This field cannot be null")
        return value


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: int
    status: str
    current_state: str
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


class RunStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    sequence_number: int
    state_before: str
    state_after: str
    step_type: str
    reason: str
    payload_json: dict[str, object] | None
    created_at: datetime


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    tool_name: str
    arguments_json: dict[str, object]
    action_hash: str
    status: str
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    decided_by: str | None


class ActionExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    idempotency_key: str
    tool_name: str
    arguments_json: dict[str, object]
    status: str
    result_json: dict[str, object] | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class RunJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    status: str
    attempts: int
    failure_count: int
    available_at: datetime
    lease_owner: str | None
    lease_until: datetime | None
    heartbeat_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
