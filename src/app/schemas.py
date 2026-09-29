from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    service: str = Field(min_length=1, max_length=100)
    severity: str = Field(min_length=1, max_length=20)
    description: str | None = None
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
    description: str | None = None
    status: str | None = Field(default=None, min_length=1, max_length=20)
    started_at: datetime | None = None

    @field_validator("title", "service", "severity", "status", mode="before")
    @classmethod
    def reject_null_for_required_fields(cls, value: object) -> object:
        if value is None:
            raise ValueError("This field cannot be null")
        return value
