from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import Settings


class AnthropicProvider:
    mode = "cloud"
    provider = "anthropic"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.model_name = settings.anthropic_model
        self._base_url = "https://api.anthropic.com/v1/messages"

    async def healthcheck(self) -> dict[str, str]:
        if not self._settings.anthropic_api_key:
            return {
                "status": "degraded",
                "mode": self.mode,
                "provider": self.provider,
                "model": self.model_name,
                "detail": "ANTHROPIC_API_KEY is not configured",
            }
        return {
            "status": "ok",
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model_name,
        }

    async def summarize(self, content: str) -> str:
        if not self._settings.anthropic_api_key:
            return f"[cloud:{self.model_name}] {content[:220]}"

        text = await self._create_message(
            system_prompt="Summarize this automation run in one concise sentence.",
            user_content=content[:3000],
            max_tokens=80,
        )
        return text.strip() if text.strip() else "Run finished."

    async def plan_task(self, task: str, max_steps: int) -> dict[str, Any]:
        if not self._settings.anthropic_api_key:
            return self._fallback_plan(task, max_steps)

        text = await self._create_message(
            system_prompt=(
                "You are a web automation planner for any application or website. "
                "Return ONLY strict JSON with keys: run_name, start_url, steps. "
                "steps must use types: navigate, click, type, select, drag, scroll, wait, "
                "handle_popup, verify_text, verify_image. "
                "Cover every explicit user instruction in order when max_steps allows, even for long prompts. "
                "Do not invent extra requirements not present in the task. "
                "Prefer the smallest reliable step sequence and avoid unnecessary waits."
            ),
            user_content=(
                f"Task: {task}\n"
                f"Max steps: {max_steps}\n"
                "Return compact valid JSON only."
            ),
            max_tokens=1400,
        )
        if text.strip():
            try:
                payload = self._extract_json_object(text)
                return self._normalize_plan(payload, task, max_steps)
            except Exception:
                pass
        return self._fallback_plan(task, max_steps)

    async def next_action(
        self,
        goal: str,
        page: dict[str, Any],
        history: list[dict[str, Any]],
        remaining_steps: int,
        memory: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._settings.anthropic_api_key:
            return {
                "status": "complete",
                "summary": "Anthropic API key is not configured for autonomous browser reasoning.",
                "action": None,
            }

        screenshot_base64 = str(page.get("screenshot_base64") or "").strip()
        screenshot_mime_type = str(page.get("screenshot_mime_type") or "image/jpeg").strip() or "image/jpeg"
        user_blocks: list[dict[str, Any]] = []
        user_payload = json.dumps(
            {
                "goal": goal,
                "remaining_steps": remaining_steps,
                "memory": memory or {},
                "page": {k: v for k, v in page.items() if k not in {"screenshot_base64", "screenshot_mime_type"}},
                "history": history[-8:],
            },
            ensure_ascii=False,
        )
        user_blocks.append({"type": "text", "text": user_payload})
        if screenshot_base64:
            user_blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": screenshot_mime_type,
                        "data": screenshot_base64,
                    },
                }
            )

        text = await self._create_message_with_blocks(
            system_prompt=(
                "You are a browser automation agent for any application or website. "
                "Return ONLY strict JSON with keys: status, summary, action. "
                "status must be 'action' or 'complete'. "
                "If status is 'action', action must contain exactly one supported runtime step using one of: "
                "navigate, click, type, select, drag, scroll, wait, handle_popup, verify_text, verify_image. "
                "Choose the single best next browser action toward the goal based on the page snapshot and recent history. "
                "Treat history as authoritative progress already completed. "
                "Continue the user's remaining instructions in order and do not repeat finished steps. "
                "Use memory from previous successful runs and previously proven selectors when it is relevant to the current page/domain. "
                "Do not stop early if explicit prompt steps remain unfinished, even for long multi-step prompts. "
                "Do not invent unrelated navigation or extra checks unless needed to unblock the next explicit instruction. "
                "When page.interactive_elements include selectors, prefer reusing those selectors directly. "
                "Use the screenshot as visual evidence when DOM data is ambiguous. "
                "Do not ask the user for selector help unless the action is impossible to infer from the page state. "
                "Prefer stable Playwright selectors using id, name, label, role, data-testid, or text selectors. "
                "Move quickly: avoid unnecessary pauses or exploratory clicks when a direct supported action is available. "
                "Do not return markdown or explanations outside JSON."
            ),
            user_blocks=user_blocks,
            max_tokens=800,
        )
        if text.strip():
            try:
                payload = self._extract_json_object(text)
                status = str(payload.get("status", "")).strip().lower()
                if status == "complete":
                    return {
                        "status": "complete",
                        "summary": str(payload.get("summary", "")).strip(),
                        "action": None,
                    }
                if status == "action" and isinstance(payload.get("action"), dict):
                    return {
                        "status": "action",
                        "summary": str(payload.get("summary", "")).strip(),
                        "action": payload["action"],
                    }
            except Exception:
                pass

        return {
            "status": "complete",
            "summary": "The model did not return a valid autonomous browser action.",
            "action": None,
        }

    async def _create_message(self, system_prompt: str, user_content: str, max_tokens: int) -> str:
        return await self._create_message_with_blocks(
            system_prompt=system_prompt,
            user_blocks=[{"type": "text", "text": user_content}],
            max_tokens=max_tokens,
        )

    async def _create_message_with_blocks(
        self,
        system_prompt: str,
        user_blocks: list[dict[str, Any]],
        max_tokens: int,
    ) -> str:
        headers = {
            "x-api-key": self._settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_blocks}],
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(self._base_url, headers=headers, json=payload)
                response.raise_for_status()
            data = response.json()
            return self._extract_text(data)
        except Exception:
            return ""

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        content = payload.get("content")
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts).strip()

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any]:
        stripped = text.strip()
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        raise ValueError("No valid JSON object found in plan response")

    @staticmethod
    def _normalize_plan(payload: dict[str, Any], task: str, max_steps: int) -> dict[str, Any]:
        run_name = payload.get("run_name")
        if not isinstance(run_name, str) or not run_name.strip():
            run_name = f"ai-plan-{task[:24].strip() or 'run'}"
        run_name = run_name.strip()[:80]

        start_url = payload.get("start_url")
        if not isinstance(start_url, str) or not start_url.strip():
            start_url = None
        else:
            start_url = start_url.strip()

        steps_raw = payload.get("steps")
        steps: list[dict[str, Any]] = []
        if isinstance(steps_raw, list):
            for step in steps_raw:
                if not isinstance(step, dict):
                    continue
                step_type = step.get("type")
                if step_type not in {
                    "navigate",
                    "click",
                    "type",
                    "select",
                    "drag",
                    "scroll",
                    "wait",
                    "handle_popup",
                    "verify_text",
                    "verify_image",
                }:
                    continue
                steps.append(step)
                if len(steps) >= max_steps:
                    break

        steps = AnthropicProvider._enforce_task_constraints(task, steps, max_steps)

        if not steps:
            return AnthropicProvider._fallback_plan(task, max_steps)

        return {
            "run_name": run_name,
            "start_url": start_url,
            "steps": steps,
        }

    @staticmethod
    def _fallback_plan(task: str, max_steps: int) -> dict[str, Any]:
        url_match = re.search(r"https?://[^\s]+", task)
        start_url = _clean_url(url_match.group(0)) if url_match else "https://example.com"
        steps = [
            {"type": "wait", "until": "load_state", "load_state": "load", "ms": 10000},
            {"type": "verify_text", "selector": "h1", "match": "contains", "value": "Example"},
        ]
        return {
            "run_name": "ai-generated-run",
            "start_url": start_url,
            "steps": steps[:max(1, max_steps)],
        }

    @staticmethod
    def _enforce_task_constraints(
        task: str,
        steps: list[dict[str, Any]],
        max_steps: int,
    ) -> list[dict[str, Any]]:
        task_lower = task.lower()

        if "image" in task_lower and not any(step.get("type") == "verify_image" for step in steps):
            image_step: dict[str, Any] = {"type": "verify_image"}

            baseline_match = re.search(
                r"(artifacts/[^\s\"']+\.(?:png|jpg|jpeg))",
                task,
                flags=re.IGNORECASE,
            )
            if baseline_match:
                image_step["baseline_path"] = baseline_match.group(1)

            threshold_match = re.search(
                r"threshold\s*[:=]?\s*([0-9]*\.?[0-9]+)",
                task,
                flags=re.IGNORECASE,
            )
            if threshold_match:
                try:
                    image_step["threshold"] = float(threshold_match.group(1))
                except ValueError:
                    pass

            selector_match = re.search(
                r"image(?:\s+verification)?\s+on\s+([#.\w:-]+)",
                task,
                flags=re.IGNORECASE,
            )
            if selector_match:
                image_step["selector"] = selector_match.group(1)

            if len(steps) < max_steps:
                steps.append(image_step)
            elif steps:
                steps[-1] = image_step
            else:
                steps = [image_step]

        return steps


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
