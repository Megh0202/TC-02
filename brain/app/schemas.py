from typing import Any

from pydantic import BaseModel, Field


class SummarizeRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


class SummarizeResponse(BaseModel):
    summary: str


class PlanRequest(BaseModel):
    task: str = Field(min_length=1, max_length=5000)
    max_steps: int = Field(default=300, ge=1, le=500)


class PlanResponse(BaseModel):
    run_name: str
    start_url: str | None = None
    steps: list[dict[str, Any]] = Field(min_length=1)


class NextActionRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=5000)
    page: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    remaining_steps: int = Field(default=1, ge=1, le=500)
    memory: dict[str, Any] = Field(default_factory=dict)


class NextActionResponse(BaseModel):
    status: str = Field(pattern="^(action|complete)$")
    summary: str = ""
    action: dict[str, Any] | None = None
