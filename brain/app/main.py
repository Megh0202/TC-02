from __future__ import annotations

import logging
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException

from app.config import get_settings
from app.llm.factory import build_llm_provider
from app.schemas import (
    NextActionRequest,
    NextActionResponse,
    PlanRequest,
    PlanResponse,
    SummarizeRequest,
    SummarizeResponse,
)

LOGGER = logging.getLogger("tekno.phantom.brain")


def build_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    provider = build_llm_provider(settings)
    app = FastAPI(title="Tekno Phantom Brain", version="0.1.0")

    def ensure_auth(authorization: str | None) -> None:
        if not settings.brain_api_key:
            return
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        token = authorization.removeprefix("Bearer ").strip()
        if token != settings.brain_api_key:
            raise HTTPException(status_code=401, detail="Invalid bearer token")

    @app.get("/health")
    async def health(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        ensure_auth(authorization)
        status = await provider.healthcheck()
        return status

    @app.post("/v1/summarize", response_model=SummarizeResponse)
    async def summarize(
        request: SummarizeRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> SummarizeResponse:
        ensure_auth(authorization)
        LOGGER.debug("Summarize request received with %s chars", len(request.content))
        summary = await provider.summarize(request.content)
        return SummarizeResponse(summary=summary)

    @app.post("/v1/plan", response_model=PlanResponse)
    async def plan(
        request: PlanRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> PlanResponse:
        ensure_auth(authorization)
        LOGGER.debug("Plan request received with %s chars", len(request.task))
        payload = await provider.plan_task(request.task, request.max_steps)
        return PlanResponse.model_validate(payload)

    @app.post("/v1/next-action", response_model=NextActionResponse)
    async def next_action(
        request: NextActionRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> NextActionResponse:
        ensure_auth(authorization)
        payload = await provider.next_action(
            request.goal,
            request.page,
            request.history,
            request.remaining_steps,
            request.memory,
        )
        return NextActionResponse.model_validate(payload)

    return app


app = build_app()
