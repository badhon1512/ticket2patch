from typing import Any, Literal

from pydantic import BaseModel, Field


class RunCreate(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    ticket_key: str = Field(min_length=1, max_length=120)
    repository: str = Field(min_length=1, max_length=240)
    status: str = Field(default="received", min_length=1, max_length=80)


class RunUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=80)
    summary: str | None = Field(default=None, max_length=4000)
    failure_reason: str | None = Field(default=None, max_length=4000)
    completed: bool = False


class ActivityCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=240)
    detail: str | None = Field(default=None, max_length=20_000)
    level: Literal["info", "success", "warning", "error"] = "info"
    actor: str = Field(default="system", min_length=1, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)
