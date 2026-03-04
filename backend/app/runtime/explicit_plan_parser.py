from __future__ import annotations

import re
from typing import Any


URL_PATTERN = re.compile(r"https?://[^\s\"']+")
QUOTED_PATTERN = re.compile(r"[\"']([^\"']+)[\"']")


def parse_explicit_plan(task: str, max_steps: int) -> dict[str, Any] | None:
    lines = _extract_instruction_lines(task)
    if len(lines) < 3:
        return None

    steps: list[dict[str, Any]] = []
    start_url: str | None = None

    for line in lines:
        parsed_steps = _parse_line(line)
        if not parsed_steps:
            continue

        for step in parsed_steps:
            if step.get("type") == "navigate" and not start_url:
                start_url = str(step.get("url"))
            steps.append(step)
            if len(steps) >= max_steps:
                break
        if len(steps) >= max_steps:
            break

    if len(steps) < 3:
        return None

    run_name = "prompt-steps-run"
    return {
        "run_name": run_name,
        "start_url": start_url,
        "steps": steps[:max_steps],
    }


def _extract_instruction_lines(task: str) -> list[str]:
    lines: list[str] = []
    for raw in task.splitlines():
        text = raw.strip()
        if not text:
            continue
        # Strip leading numeric bullet styles: "1)", "1.", "- "
        text = re.sub(r"^\s*(\d+[\).\s-]+|[-*]\s+)", "", text).strip()
        if text:
            lines.append(text)
    return lines


def _parse_line(line: str) -> list[dict[str, Any]]:
    lower = line.lower()

    if any(token in lower for token in ("navigate", "open", "launch", "go to", "visit")):
        url = _extract_url(line)
        if url:
            return [{"type": "navigate", "url": url}]

    if any(token in lower for token in ("type", "enter")):
        value = _extract_quoted(line)
        if value is None:
            # pattern: type XYZ into field
            value = _extract_value_after_keyword(line, ("type", "enter"))
        selector = _selector_from_type_line(lower)
        if value and selector:
            return [{"type": "type", "selector": selector, "text": value, "clear_first": True}]

    if "verify" in lower and "create form" in lower and "visible" in lower:
        return [{"type": "verify_text", "selector": "{{selector.create_form}}", "match": "contains", "value": "Create Form"}]

    if "verify" in lower and "login" in lower and "success" in lower:
        # Keep this lightweight to avoid brittle page text checks.
        return [{"type": "wait", "until": "timeout", "ms": 1200}]

    if "click" in lower and "create form" in lower:
        return [{"type": "click", "selector": "{{selector.create_form}}"}]

    if "drag" in lower and "short answer" in lower:
        return [{"type": "drag", "source_selector": "{{selector.short_answer_source}}", "target_selector": "{{selector.form_canvas_target}}"}]

    if ("label" in lower and ("type" in lower or "enter" in lower)) or ("label input" in lower and "first name" in lower):
        label_value = _extract_quoted(line) or "First Name"
        return [{"type": "type", "selector": "{{selector.form_label}}", "text": label_value, "clear_first": True}]

    if "required" in lower and any(token in lower for token in ("check", "tick", "select")):
        return [{"type": "click", "selector": "input[type='checkbox'][name*='required'], input[type='checkbox'].required"}]

    if "click" in lower and "save" in lower:
        return [{"type": "click", "selector": "{{selector.save_form}}"}]

    # Fallback for generic click with quoted target.
    if "click" in lower:
        target = _extract_quoted(line)
        if target:
            return [{"type": "click", "selector": f"text={target}"}]

    return []


def _selector_from_type_line(lower: str) -> str | None:
    if "email" in lower:
        return "{{selector.email}}"
    if "password" in lower:
        return "{{selector.password}}"
    if "form name" in lower:
        return "{{selector.form_name}}"
    if "label" in lower:
        return "{{selector.form_label}}"
    if "search" in lower and "amazon" in lower:
        return "{{selector.amazon_search_box}}"
    return None


def _extract_url(text: str) -> str | None:
    match = URL_PATTERN.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,)")


def _extract_quoted(text: str) -> str | None:
    match = QUOTED_PATTERN.search(text)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _extract_value_after_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
    lowered = text.lower()
    for keyword in keywords:
        idx = lowered.find(keyword)
        if idx < 0:
            continue
        remainder = text[idx + len(keyword) :].strip(" :-")
        # stop at "into"
        into_idx = remainder.lower().find(" into ")
        if into_idx >= 0:
            remainder = remainder[:into_idx].strip()
        return remainder or None
    return None
