from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import Settings


class HttpBrainClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.brain_base_url.rstrip("/")
        self._timeout = max(settings.brain_timeout_seconds, 1)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._settings.brain_api_key:
            headers["Authorization"] = f"Bearer {self._settings.brain_api_key}"
        return headers

    async def healthcheck(self) -> dict[str, str]:
        url = f"{self._base_url}/health"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=self._headers())
                response.raise_for_status()
            payload = response.json()
            status = str(payload.get("status", "ok"))
            mode = str(payload.get("mode", "unknown"))
            provider = str(payload.get("provider", "unknown"))
            model = str(payload.get("model", "unknown"))
            detail = payload.get("detail")
            result = {"status": status, "mode": mode, "provider": provider, "model": model}
            if detail:
                result["detail"] = str(detail)
            return result
        except Exception as exc:
            return {
                "status": "degraded",
                "mode": "unknown",
                "model": "unknown",
                "detail": str(exc),
            }

    async def summarize(self, content: str) -> str:
        url = f"{self._base_url}/v1/summarize"
        body = {"content": content}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=body, headers=self._headers())
                response.raise_for_status()
            payload = response.json()
            summary = payload.get("summary")
            if isinstance(summary, str) and summary.strip():
                return summary.strip()
        except Exception:
            pass
        return f"[brain-unavailable] {content[:220]}"

    async def plan_task(self, task: str, max_steps: int) -> dict[str, Any]:
        url = f"{self._base_url}/v1/plan"
        body = {"task": task, "max_steps": max_steps}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=body, headers=self._headers())
                response.raise_for_status()
            payload = response.json()
            run_name = payload.get("run_name")
            steps = payload.get("steps")
            if not isinstance(run_name, str) or not run_name.strip():
                raise ValueError("Brain plan response missing run_name")
            if not isinstance(steps, list) or not steps:
                raise ValueError("Brain plan response missing steps")
            return {
                "run_name": run_name.strip(),
                "start_url": payload.get("start_url"),
                "steps": steps,
            }
        except Exception:
            url_match = re.search(r"https?://[^\s]+", task)
            start_url = _clean_url(url_match.group(0)) if url_match else "https://example.com"
            fallback_steps = [
                {"type": "wait", "until": "load_state", "load_state": "load", "ms": 10000},
                {"type": "verify_text", "selector": "h1", "match": "contains", "value": "Example"},
            ]
            return {
                "run_name": "ai-generated-run",
                "start_url": start_url,
                "steps": fallback_steps[:max(1, max_steps)],
            }

    async def next_action(
        self,
        goal: str,
        page: dict[str, Any],
        history: list[dict[str, Any]],
        remaining_steps: int,
        memory: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/v1/next-action"
        body = {
            "goal": goal,
            "page": page,
            "history": history,
            "remaining_steps": remaining_steps,
            "memory": memory or {},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=body, headers=self._headers())
                response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and payload.get("status") in {"action", "complete"}:
                return payload
        except Exception:
            pass
        return {
            "status": "complete",
            "summary": "Brain unavailable for autonomous next-action planning.",
            "action": None,
        }


def _clean_url(url: str) -> str:
    cleaned = url.strip()
    trailing_punctuation = {",", ".", ";", ":", "!", "?", ")", "]", "}", "'", '"', "`", ">"}
    while cleaned:
        last_char = cleaned[-1]
        if last_char in trailing_punctuation:
            cleaned = cleaned[:-1].rstrip()
            continue
        if last_char == "/" and len(cleaned) > 1 and cleaned[-2] in trailing_punctuation:
            cleaned = cleaned[:-1].rstrip()
            continue
        break
    return cleaned
