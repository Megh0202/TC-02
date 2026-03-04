from __future__ import annotations

from typing import Any, Protocol


class LLMProvider(Protocol):
    mode: str
    model_name: str

    async def healthcheck(self) -> dict[str, str]:
        ...

    async def summarize(self, content: str) -> str:
        ...

    async def plan_task(self, task: str, max_steps: int) -> dict[str, Any]:
        ...
