from typing import Any

from pydantic import BaseModel, Field


class SummarizeRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


class SummarizeResponse(BaseModel):
    summary: str


class PlanRequest(BaseModel):
    task: str = Field(min_length=1, max_length=5000)
    max_steps: int = Field(default=20, ge=1, le=50)


class PlanResponse(BaseModel):
    run_name: str
    start_url: str | None = None
    steps: list[dict[str, Any]] = Field(min_length=1)
