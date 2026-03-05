from __future__ import annotations

import re
from typing import Any


_LINE_PREFIX_RE = re.compile(r"^\s*(?:\d+[\).:-]\s*|[-*]\s+)")
_URL_RE = re.compile(r"https?://[^\s\"'>]+", flags=re.IGNORECASE)
_QUOTED_RE = re.compile(r"['\"]([^'\"]+)['\"]")


def parse_structured_task_steps(task: str, max_steps: int) -> list[dict[str, Any]]:
    """
    Parse explicit line-by-line user instructions into runnable steps.
    Returns an empty list when the task does not look like structured instructions.
    """
    lines = [_normalize_line(raw) for raw in task.splitlines()]
    instruction_lines = [line for line in lines if line]
    if len(instruction_lines) < 2:
        return []

    steps: list[dict[str, Any]] = []
    for line in instruction_lines:
        parsed = _parse_line(line)
        if parsed is None:
            continue
        steps.append(parsed)
        if len(steps) >= max_steps:
            break
    steps = _enforce_login_sequence(steps, max_steps=max_steps)
    steps = _enforce_form_create_sequence(steps, max_steps=max_steps)
    return steps[:max_steps]


def _normalize_line(raw: str) -> str:
    cleaned = (
        raw.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .strip()
    )
    cleaned = _LINE_PREFIX_RE.sub("", cleaned)
    return cleaned.strip()


def _parse_line(line: str) -> dict[str, Any] | None:
    lower = line.lower()
    quoted = _first_quoted(line)
    url = _extract_url(line)

    if url and any(token in lower for token in ("launch", "open", "navigate", "visit", "go to")):
        return {"type": "navigate", "url": url}

    if any(token in lower for token in ("enter email", "type email", "email -", "email:", "into email", "email field")):
        value = _after_delimiter(line)
        if value:
            return {"type": "type", "selector": "{{selector.email}}", "text": value, "clear_first": True}

    if any(
        token in lower
        for token in ("enter password", "type password", "password -", "password:", "into password", "password field")
    ):
        value = _after_delimiter(line)
        if value:
            return {"type": "type", "selector": "{{selector.password}}", "text": value, "clear_first": True}

    if "verify" in lower and "create form" in lower and "visible" in lower:
        return {
            "type": "wait",
            "until": "selector_visible",
            "selector": "{{selector.create_form}}",
            "ms": 6000,
        }

    if "click" in lower and "create form" in lower:
        return {"type": "click", "selector": "{{selector.create_form}}"}

    if "form name" in lower and any(token in lower for token in ("enter", "type")):
        value = _extract_form_name_value(line)
        return {"type": "type", "selector": "{{selector.form_name}}", "text": value, "clear_first": True}

    if "drag" in lower and any(token in lower for token in ("short answer", "email field", "email")):
        source_alias = "{{selector.short_answer_source}}"
        if "email" in lower and "short answer" not in lower:
            source_alias = "{{selector.email_field_source}}"
        return {
            "type": "drag",
            "source_selector": source_alias,
            "target_selector": "{{selector.form_canvas_target}}",
        }

    if any(token in lower for token in ("label", "first name")) and any(
        token in lower for token in ("enter", "type")
    ):
        value = quoted or "First Name"
        return {"type": "type", "selector": "{{selector.form_label}}", "text": value, "clear_first": True}

    if any(token in lower for token in ("required checkbox", "required check box", "required")) and any(
        token in lower for token in ("check", "select", "tick", "click")
    ):
        return {"type": "click", "selector": "{{selector.required_checkbox}}"}

    if "click" in lower and "save" in lower:
        return {"type": "click", "selector": "{{selector.save_form}}"}

    if "wait" in lower:
        return {"type": "wait", "until": "timeout", "ms": 1000}

    return None


def _first_quoted(text: str) -> str | None:
    match = _QUOTED_RE.search(text)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _extract_url(text: str) -> str | None:
    match = _URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,)")


def _after_delimiter(text: str) -> str | None:
    parts = re.split(r"\s[-:]\s", text, maxsplit=1)
    value = parts[1].strip() if len(parts) > 1 else ""
    return value or _first_quoted(text)


def _extract_form_name_value(text: str) -> str:
    quoted = _first_quoted(text)
    if quoted:
        normalized = quoted.replace("<timestamp>", "{{NOW_YYYYMMDD_HHMMSS}}")
        normalized = normalized.replace("<time stamp>", "{{NOW_YYYYMMDD_HHMMSS}}")
        return normalized
    return "QA_Form_{{NOW_YYYYMMDD_HHMMSS}}"


def _enforce_login_sequence(steps: list[dict[str, Any]], max_steps: int) -> list[dict[str, Any]]:
    has_email_type = any(
        step.get("type") == "type" and str(step.get("selector", "")).strip() == "{{selector.email}}"
        for step in steps
    )
    has_password_type = any(
        step.get("type") == "type" and str(step.get("selector", "")).strip() == "{{selector.password}}"
        for step in steps
    )
    needs_authenticated_flow = any(
        (step.get("type") == "verify_text" and "create form" in str(step.get("value", "")).lower())
        or (step.get("type") == "click" and "create_form" in str(step.get("selector", "")).lower())
        for step in steps
    )
    has_login_click = any(
        step.get("type") == "click"
        and any(
            token in str(step.get("selector", "")).lower()
            for token in ("login", "sign in", "signin", "submit", "selector.login_button")
        )
        for step in steps
    )

    if not (has_email_type and has_password_type and needs_authenticated_flow) or has_login_click:
        return steps

    password_index = next(
        (
            idx
            for idx, step in enumerate(steps)
            if step.get("type") == "type" and str(step.get("selector", "")).strip() == "{{selector.password}}"
        ),
        None,
    )
    if password_index is None:
        return steps

    login_sequence = [
        {"type": "click", "selector": "{{selector.login_button}}"},
        {"type": "wait", "until": "timeout", "ms": 1200},
    ]
    merged = steps[: password_index + 1] + login_sequence + steps[password_index + 1 :]
    return merged[:max_steps]


def _enforce_form_create_sequence(steps: list[dict[str, Any]], max_steps: int) -> list[dict[str, Any]]:
    """
    Ensure we click "Create" after entering form name before builder interactions.
    """
    form_name_index = next(
        (
            idx
            for idx, step in enumerate(steps)
            if step.get("type") == "type" and str(step.get("selector", "")).strip() == "{{selector.form_name}}"
        ),
        None,
    )
    if form_name_index is None:
        return steps

    # If there is no builder work afterwards, do nothing.
    has_builder_work_after = any(
        (
            step.get("type") == "drag"
            or (step.get("type") == "type" and "form_label" in str(step.get("selector", "")))
            or (step.get("type") == "click" and "required" in str(step.get("selector", "")).lower())
        )
        for step in steps[form_name_index + 1 :]
    )
    if not has_builder_work_after:
        return steps

    # If a create click already exists after form name typing, keep as-is.
    has_create_click_after = any(
        step.get("type") == "click"
        and "create_form" in str(step.get("selector", "")).lower()
        for step in steps[form_name_index + 1 :]
    )
    if has_create_click_after:
        return steps

    create_sequence = [
        {"type": "click", "selector": "{{selector.create_form_confirm}}"},
        {"type": "wait", "until": "timeout", "ms": 1000},
    ]
    merged = steps[: form_name_index + 1] + create_sequence + steps[form_name_index + 1 :]
    return merged[:max_steps]
