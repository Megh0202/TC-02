from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

import pytest

from app.runtime.executor import AgentExecutor
from app.runtime.selector_memory import InMemorySelectorMemoryStore
from app.schemas import RunState, RunStatus, StepRuntimeState, StepStatus


def _executor(step_timeout_seconds: int = 15) -> AgentExecutor:
    executor = AgentExecutor.__new__(AgentExecutor)
    executor._settings = SimpleNamespace(
        step_timeout_seconds=step_timeout_seconds,
        selector_recovery_enabled=True,
        selector_recovery_attempts=2,
        selector_recovery_delay_ms=0,
    )
    executor._selector_memory = None
    return executor


class _RunStore:
    def __init__(self, run: RunState | None = None) -> None:
        self._run = run

    def get(self, run_id: str) -> RunState | None:
        if self._run and self._run.run_id == run_id:
            return self._run
        return None

    def persist(self, run: RunState) -> None:
        self._run = run


def test_selector_candidates_use_default_email_profile() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector="input[type='email']",
        step_type="type",
        selector_profile={},
        test_data={},
        run_domain=None,
        text_hint="qa@example.com",
    )

    assert candidates[0] == "input[type='email']"
    assert "input[name='username']" in candidates
    assert "input[type='email']" in candidates


def test_type_selector_candidates_prioritize_explicit_selector_before_email_aliases() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector="input[name='email']",
        step_type="type",
        selector_profile={},
        test_data={},
        run_domain=None,
        text_hint="qa@example.com",
    )

    assert candidates[0] == "input[name='email']"
    assert "#username" in candidates


def test_password_candidates_do_not_infer_email_from_password_value() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector="input[name='password']",
        step_type="type",
        selector_profile={},
        test_data={},
        run_domain=None,
        text_hint="Madhu@123",
    )

    assert candidates[0] == "input[name='password']"
    assert "input[placeholder*='Email']" not in candidates


def test_memory_candidates_match_selector_case_and_quote_variants() -> None:
    executor = _executor()
    memory = InMemorySelectorMemoryStore()
    memory.remember_success(
        "app.stag.dr-adem.com",
        "click",
        "button:has-text('english')",
        "button:has-text('English')",
    )
    executor._selector_memory = memory

    candidates = executor._memory_candidates(
        "app.stag.dr-adem.com",
        "click",
        'button:has-text("English")',
    )

    assert "button:has-text('English')" in candidates


def test_click_memory_candidates_match_across_text_selector_forms() -> None:
    executor = _executor()
    memory = InMemorySelectorMemoryStore()
    memory.remember_success(
        "app.stag.dr-adem.com",
        "click",
        "text::sign up",
        "button.text-\\[12px\\].font-ibm-plex.font-medium.text-black.underline.ml-1.hover\\:opacity-80:visible",
    )
    executor._selector_memory = memory

    candidates = executor._memory_candidates(
        "app.stag.dr-adem.com",
        "click",
        'button:has-text("Sign Up")',
    )

    assert "button.text-\\[12px\\].font-ibm-plex.font-medium.text-black.underline.ml-1.hover\\:opacity-80:visible" in candidates


def test_click_alias_candidates_prefer_remembered_selector_before_profile_defaults() -> None:
    executor = _executor()
    memory = InMemorySelectorMemoryStore()
    memory.remember_success(
        "app.stag.dr-adem.com",
        "click",
        "login_button",
        "[data-testid='login-button']",
    )
    executor._selector_memory = memory

    candidates = executor._selector_candidates(
        raw_selector="{{selector.login_button}}",
        step_type="click",
        selector_profile={},
        test_data={},
        run_domain="app.stag.dr-adem.com",
    )

    assert candidates[0] == "[data-testid='login-button']"
    assert "button:has-text('Login')" in candidates


def test_memory_candidates_skip_unsafe_root_level_selectors() -> None:
    executor = _executor()
    memory = InMemorySelectorMemoryStore()
    memory.remember_success("app.stag.dr-adem.com", "click", "cta", "xpath=//body")
    memory.remember_success("app.stag.dr-adem.com", "click", "cta", "button:has-text('Continue')")
    executor._selector_memory = memory

    candidates = executor._memory_candidates("app.stag.dr-adem.com", "click", "cta")

    assert "xpath=//body" not in candidates
    assert "button:has-text('Continue')" in candidates


def test_selector_fallback_tries_multiple_candidates() -> None:
    executor = _executor(step_timeout_seconds=6)
    attempted: list[str] = []

    async def operation(selector: str) -> str:
        attempted.append(selector)
        if selector == "input[name='username']":
            return f"Typed into {selector} (after clear)"
        raise ValueError(f"Missing {selector}")

    result = asyncio.run(
        executor._run_with_selector_fallback(
            raw_selector="input[type='email']",
            step_type="type",
            selector_profile={},
            test_data={},
            run_domain=None,
            operation=operation,
            text_hint="qa@example.com",
        )
    )

    assert result == "Typed into input[name='username'] (after clear)"
    assert attempted[0] == "input[type='email']"
    assert attempted[1] == "#username"


def test_selector_fallback_error_lists_attempts() -> None:
    executor = _executor(step_timeout_seconds=4)

    async def operation(selector: str) -> str:
        raise ValueError(f"Missing {selector}")

    with pytest.raises(ValueError) as exc_info:
        asyncio.run(
            executor._run_with_selector_fallback(
                raw_selector="input[type='email']",
                step_type="type",
                selector_profile={},
                test_data={},
                run_domain=None,
                operation=operation,
                text_hint="qa@example.com",
            )
        )

    message = str(exc_info.value)
    assert "All selector candidates failed" in message
    assert "#username" in message
    assert "input[type='email']" in message


def test_execute_step_switches_to_waiting_for_input_on_selector_failure() -> None:
    executor = _executor(step_timeout_seconds=4)

    async def _raise_selector_error(run: RunState, raw_step: dict) -> str:
        raise ValueError("All selector candidates failed: pass 1: button:has-text('Workflows') -> timeout")

    executor._dispatch_step = _raise_selector_error
    executor._files = SimpleNamespace(
        write_text_artifact=lambda *args, **kwargs: None,
        write_bytes_artifact=lambda *args, **kwargs: None,
    )
    executor._capture_failure_screenshot = lambda *args, **kwargs: asyncio.sleep(0)

    run = RunState(run_name="selector-help-run", steps=[])
    step = StepRuntimeState(
        index=0,
        type="click",
        input={"type": "click", "selector": "button:has-text('Workflows')"},
    )

    asyncio.run(executor._execute_step(run, step))

    assert step.status == StepStatus.waiting_for_input
    assert step.user_input_kind == "selector"
    assert "Please provide a Playwright selector" in (step.user_input_prompt or "")
    assert step.requested_selector_target == "button:has-text('Workflows')"


def test_click_selector_parse_error_still_requests_selector_help() -> None:
    executor = _executor(step_timeout_seconds=4)

    async def _raise_selector_error(run: RunState, raw_step: dict) -> str:
        raise ValueError(
            'All selector candidates failed: pass 1: page.get_by_text("Workflows", exact=True) '
            '-> Unexpected token "get_by_text(" while parsing css selector'
        )

    executor._dispatch_step = _raise_selector_error
    executor._files = SimpleNamespace(
        write_text_artifact=lambda *args, **kwargs: None,
        write_bytes_artifact=lambda *args, **kwargs: None,
    )
    executor._capture_failure_screenshot = lambda *args, **kwargs: asyncio.sleep(0)

    run = RunState(run_name="selector-help-run", steps=[])
    step = StepRuntimeState(
        index=0,
        type="click",
        input={"type": "click", "selector": 'page.get_by_text("Workflows", exact=True)'},
    )

    asyncio.run(executor._execute_step(run, step))

    assert step.status == StepStatus.waiting_for_input
    assert step.user_input_kind == "selector"


def test_execute_type_step_fails_on_plain_timeout_without_selector_resolution_error() -> None:
    executor = _executor(step_timeout_seconds=1)

    async def _hang(run: RunState, raw_step: dict) -> str:
        await asyncio.sleep(2)
        return "never"

    executor._dispatch_step = _hang
    executor._files = SimpleNamespace(
        write_text_artifact=lambda *args, **kwargs: None,
        write_bytes_artifact=lambda *args, **kwargs: None,
    )
    executor._capture_failure_screenshot = lambda *args, **kwargs: asyncio.sleep(0)

    run = RunState(run_name="selector-help-run", steps=[])
    step = StepRuntimeState(
        index=0,
        type="type",
        input={"type": "type", "selector": "input[name='email']", "text": "qa@example.com"},
    )

    asyncio.run(executor._execute_step(run, step))

    assert step.status == StepStatus.failed
    assert step.user_input_kind is None
    assert step.requested_selector_target is None


def test_apply_manual_selector_hint_updates_step_without_premature_selector_memory() -> None:
    executor = _executor()
    memory = InMemorySelectorMemoryStore()
    run = RunState(
        run_id="run-1",
        run_name="selector-help-run",
        start_url="https://test.vitaone.io/workflows",
        status=RunStatus.waiting_for_input,
        steps=[
            StepRuntimeState(
                step_id="step-1",
                index=0,
                type="click",
                input={"type": "click", "selector": "button:has-text('Workflows')"},
                status=StepStatus.waiting_for_input,
                user_input_kind="selector",
                requested_selector_target="button:has-text('Workflows')",
            )
        ],
    )
    executor._run_store = _RunStore(run)
    executor._selector_memory = memory

    updated = executor.apply_manual_selector_hint("run-1", "step-1", "a:has-text('Workflows')")

    assert updated is not None
    step = updated.steps[0]
    assert step.status == StepStatus.pending
    assert step.input["selector"] == "a:has-text('Workflows')"
    assert step.provided_selector == "a:has-text('Workflows')"
    remembered = memory.get_candidates("test.vitaone.io", "click", "button:has-text('Workflows')")
    assert remembered == []
    assert step.input["_selector_help_original"] == "button:has-text('Workflows')"


def test_selector_variants_include_id_case_and_contains_conversions() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector='button#create_form:contains("Create Form")',
        step_type="click",
        selector_profile={},
        test_data={},
        run_domain=None,
    )

    assert 'button#create_form:contains("Create Form")' in candidates
    assert 'button#createForm:contains("Create Form")' in candidates
    assert 'button#create_form:has-text("Create Form")' in candidates
    assert "text=Create Form" in candidates


def test_click_text_selector_variants_include_link_and_text_fallbacks() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector="button:has-text('Sign Up')",
        step_type="click",
        selector_profile={},
        test_data={},
        run_domain=None,
    )

    assert "button:has-text('Sign Up')" in candidates
    assert 'a:has-text("Sign Up")' in candidates
    assert '[role="button"]:has-text("Sign Up")' in candidates
    assert ':text-is("Sign Up")' in candidates
    assert "text=Sign Up" in candidates


def test_selector_variants_include_amazon_result_fallbacks() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector="div.s-main-slot div[data-index='0'] h2 a",
        step_type="click",
        selector_profile={},
        test_data={},
        run_domain=None,
    )

    assert "div[data-component-type='s-search-result'] h2 a" in candidates
    assert "h2 a.a-link-normal" in candidates


def test_selector_candidates_include_amazon_result_defaults_for_h2_visible() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector="h2 a:visible",
        step_type="click",
        selector_profile={},
        test_data={},
        run_domain=None,
    )

    assert "div[data-component-type='s-search-result'] h2 a" in candidates
    assert "h2 a.a-link-normal" in candidates
    assert "h2 a" in candidates


def test_selector_candidates_include_amazon_add_to_cart_defaults() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector="button:has-text('Add to Cart')",
        step_type="click",
        selector_profile={},
        test_data={},
        run_domain=None,
    )

    assert "#add-to-cart-button" in candidates
    assert "input[name='submit.add-to-cart']" in candidates


def test_selector_candidates_include_form_name_defaults() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector="input[name='formName']",
        step_type="type",
        selector_profile={},
        test_data={},
        run_domain=None,
        text_hint="QA_Form_20260223_154500",
    )

    assert "input[name='formName']" in candidates
    assert "input[name='name']" in candidates
    assert "input#formName" in candidates


def test_selector_candidates_include_create_form_defaults() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector="button#create_form",
        step_type="verify_text",
        selector_profile={},
        test_data={},
        run_domain=None,
    )

    assert "button#createForm" in candidates
    assert "button:has-text('Create Form')" in candidates


def test_verify_text_hint_promotes_create_form_candidates() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector="h1",
        step_type="verify_text",
        selector_profile={},
        test_data={},
        run_domain=None,
        text_hint="Create Form",
    )

    assert candidates[0] == "button#createForm"
    assert "button:has-text('Create Form')" in candidates
    assert "h1" in candidates


def test_verify_text_hint_promotes_login_candidates() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector="body",
        step_type="verify_text",
        selector_profile={},
        test_data={},
        run_domain=None,
        text_hint="Login successful",
    )

    assert "button[name='login']" in candidates
    assert "button[type='submit']" in candidates
    assert "body" in candidates


def test_selector_candidates_include_drag_defaults() -> None:
    executor = _executor()
    source_candidates = executor._selector_candidates(
        raw_selector="short answer",
        step_type="drag",
        selector_profile={},
        test_data={},
        run_domain=None,
    )
    target_candidates = executor._selector_candidates(
        raw_selector="form canvas",
        step_type="drag",
        selector_profile={},
        test_data={},
        run_domain=None,
    )

    assert "[draggable='true']:has-text('Short answer')" in source_candidates
    assert ".form-canvas" in target_candidates
    assert "[data-testid='form-builder-canvas']" in target_candidates


def test_selector_candidates_include_form_label_defaults() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector="[data-testid='form-builder-canvas'] input[name='label']",
        step_type="type",
        selector_profile={},
        test_data={},
        run_domain=None,
        text_hint="First Name",
    )

    assert "[data-testid='form-builder-canvas'] input[placeholder='Label']" in candidates
    assert "textarea[placeholder='Label']" in candidates


def test_apply_template_expands_now_macro() -> None:
    executor = _executor()
    output = executor._apply_template("QA_Form_{{NOW_YYYYMMDD_HHMMSS}}", {})
    assert re.match(r"^QA_Form_\d{8}_\d{6}$", output)


def test_initialize_runtime_test_data_stabilizes_now_templates() -> None:
    executor = _executor()
    data = executor._initialize_runtime_test_data({})

    first = executor._apply_template("InitialState_{{NOW_YYYYMMDD_HHMMSS}}", data)
    second = executor._apply_template("SubmittedState_{{NOW_YYYYMMDD_HHMMSS}}", data)

    assert re.match(r"^InitialState_\d{8}_\d{6}$", first)
    assert re.match(r"^SubmittedState_\d{8}_\d{6}$", second)
    assert first.split("_", 1)[1] == second.split("_", 1)[1]


def test_selector_memory_prioritizes_previous_successes() -> None:
    executor = _executor()
    memory = InMemorySelectorMemoryStore()
    memory.remember_success("test.vitaone.io", "click", "create_form", "button#createForm")
    memory.remember_success("test.vitaone.io", "click", "create_form", "button#createForm")
    memory.remember_success("test.vitaone.io", "click", "create_form", "button#create_form")
    executor._selector_memory = memory

    candidates = executor._selector_candidates(
        raw_selector="button#create_form",
        step_type="click",
        selector_profile={},
        test_data={},
        run_domain="test.vitaone.io",
    )

    assert candidates[0] == "button#createForm"


def test_selector_memory_prefers_stable_click_selector_over_brittle_css() -> None:
    executor = _executor()
    memory = InMemorySelectorMemoryStore()
    memory.remember_success(
        "test.vitaone.io",
        "click",
        "button:has-text('Login')",
        "button.flex.items-center.gap-1\\.5.rounded-md.text-white:visible",
    )
    memory.remember_success(
        "test.vitaone.io",
        "click",
        "button:has-text('Login')",
        "button:has-text('Login')",
    )
    executor._selector_memory = memory

    candidates = executor._memory_candidates(
        "test.vitaone.io",
        "click",
        "button:has-text('Login')",
    )

    assert candidates[0] == "button:has-text('Login')"


def test_click_candidate_timeout_is_capped_for_single_candidate() -> None:
    executor = _executor(step_timeout_seconds=60)

    assert executor._candidate_timeout_seconds(1, step_type="click") == 8.0


def test_click_memory_candidates_exclude_form_fields_for_button_like_targets() -> None:
    executor = _executor()
    memory = InMemorySelectorMemoryStore()
    memory.remember_success(
        "test.vitaone.io",
        "click",
        "button:has-text('English')",
        "xpath=//input[@placeholder='Enter email']",
    )
    memory.remember_success(
        "test.vitaone.io",
        "click",
        "button:has-text('English')",
        "button:has-text('English')",
    )
    executor._selector_memory = memory

    candidates = executor._memory_candidates(
        "test.vitaone.io",
        "click",
        "button:has-text('English')",
    )

    assert "xpath=//input[@placeholder='Enter email']" not in candidates
    assert candidates[0] == "button:has-text('English')"


def test_selector_fallback_retries_transient_timeout_and_recovers() -> None:
    executor = _executor(step_timeout_seconds=4)
    call_count = 0

    async def operation(selector: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("Timeout 15000ms exceeded")
        return f"Clicked {selector}"

    result = asyncio.run(
        executor._run_with_selector_fallback(
            raw_selector="#onlytarget",
            step_type="click",
            selector_profile={},
            test_data={},
            run_domain=None,
            operation=operation,
        )
    )

    assert result == "Clicked #onlytarget"
    assert call_count == 2


def test_transition_label_candidates_include_common_prompt_typo_variant() -> None:
    executor = _executor()

    candidates = executor._selector_candidates(
        raw_selector="{{selector.transition_canvas_label}}",
        step_type="click",
        selector_profile={},
        test_data={"NOW_YYYYMMDD_HHMMSS": "20260320_111947"},
        run_domain=None,
        text_hint="Tranisition_{{NOW_YYYYMMDD_HHMMSS}}",
    )

    assert "text=Tranisition_20260320_111947" in candidates
    assert "text=Transition_20260320_111947" in candidates


def test_login_click_timeout_recovers_when_create_form_appears() -> None:
    executor = _executor(step_timeout_seconds=4)

    class _Browser:
        async def click(self, selector: str) -> str:
            raise TimeoutError("TimeoutError()")

        async def wait_for(
            self,
            *,
            until: str,
            ms: int,
            selector: str | None = None,
            load_state: str | None = None,
        ) -> str:
            if selector == "button#createForm":
                return "visible"
            raise TimeoutError(f"Missing {selector}")

    executor._browser = _Browser()

    result = asyncio.run(
        executor._dispatch_step(
            SimpleNamespace(test_data={}, selector_profile={}, start_url=None, steps=[]),
            {
                "type": "click",
                "selector": "{{selector.login_button}}",
            },
        )
    )

    assert result == "Login click likely succeeded; Create Form became visible"


def test_login_click_hang_recovers_before_outer_step_timeout() -> None:
    executor = _executor(step_timeout_seconds=6)

    class _Browser:
        async def click(self, selector: str) -> str:
            await asyncio.sleep(3.5)
            return f"Clicked {selector}"

        async def wait_for(
            self,
            *,
            until: str,
            ms: int,
            selector: str | None = None,
            load_state: str | None = None,
        ) -> str:
            if selector == "button#createForm":
                return "visible"
            raise TimeoutError(f"Missing {selector}")

    executor._browser = _Browser()

    result = asyncio.run(
        executor._dispatch_step(
            SimpleNamespace(test_data={}, selector_profile={}, start_url=None, steps=[]),
            {
                "type": "click",
                "selector": "{{selector.login_button}}",
            },
        )
    )

    assert result == "Login click likely succeeded; Create Form became visible"


def test_transition_canvas_click_short_circuits_when_label_is_visible() -> None:
    executor = _executor(step_timeout_seconds=6)

    class _Browser:
        async def wait_for(
            self,
            *,
            until: str,
            ms: int,
            selector: str | None = None,
            load_state: str | None = None,
        ) -> str:
            if selector == "text=Transition_20260320_123745":
                return "visible"
            raise TimeoutError(f"Missing {selector}")

        async def click(self, selector: str) -> str:
            raise AssertionError("click should not be attempted when transition label is already visible")

    executor._browser = _Browser()

    result = asyncio.run(
        executor._dispatch_step(
            SimpleNamespace(
                test_data={"NOW_YYYYMMDD_HHMMSS": "20260320_123745"},
                selector_profile={},
                start_url=None,
                steps=[],
            ),
            {
                "type": "click",
                "selector": "{{selector.transition_canvas_label}}",
                "text_hint": "Tranisition_{{NOW_YYYYMMDD_HHMMSS}}",
            },
        )
    )

    assert result == "Transition label is visible on canvas"


def test_transition_canvas_click_becomes_non_blocking_when_editor_is_visible() -> None:
    executor = _executor(step_timeout_seconds=6)

    class _Browser:
        async def wait_for(
            self,
            *,
            until: str,
            ms: int,
            selector: str | None = None,
            load_state: str | None = None,
        ) -> str:
            if selector == "button:has-text('Save Changes')":
                return "visible"
            raise TimeoutError(f"Missing {selector}")

        async def click(self, selector: str) -> str:
            raise AssertionError("click should not be attempted when transition click is treated as non-blocking")

    executor._browser = _Browser()

    result = asyncio.run(
        executor._dispatch_step(
            SimpleNamespace(
                test_data={"NOW_YYYYMMDD_HHMMSS": "20260320_155646"},
                selector_profile={},
                start_url=None,
                steps=[],
            ),
            {
                "type": "click",
                "selector": "{{selector.transition_canvas_label}}",
                "text_hint": "Tranisition_{{NOW_YYYYMMDD_HHMMSS}}",
            },
        )
    )

    assert result == "Transition canvas click treated as non-blocking"


def test_email_candidates_exclude_password_selectors_from_memory() -> None:
    executor = _executor()
    memory = InMemorySelectorMemoryStore()
    memory.remember_success("test.vitaone.io", "type", "email", "#password")
    memory.remember_success("test.vitaone.io", "type", "email", "input[name='username']")
    executor._selector_memory = memory

    candidates = executor._selector_candidates(
        raw_selector="email field",
        step_type="type",
        selector_profile={},
        test_data={},
        run_domain="test.vitaone.io",
        text_hint="qa@example.com",
    )

    assert "#password" not in candidates
    assert "input[name='username']" in candidates


def test_password_value_with_at_symbol_does_not_trigger_email_candidates() -> None:
    executor = _executor()
    candidates = executor._selector_candidates(
        raw_selector="password field",
        step_type="type",
        selector_profile={},
        test_data={},
        run_domain=None,
        text_hint="PasswordVitaone1@",
    )

    assert "#password" in candidates
    assert "#username" not in candidates


def test_selector_fallback_does_not_retry_non_transient_error() -> None:
    executor = _executor(step_timeout_seconds=4)
    call_count = 0

    async def operation(selector: str) -> str:
        nonlocal call_count
        call_count += 1
        raise ValueError("No option with value '2' found")

    with pytest.raises(ValueError) as exc_info:
        asyncio.run(
            executor._run_with_selector_fallback(
                raw_selector="#onlytarget",
                step_type="select",
                selector_profile={},
                test_data={},
                run_domain=None,
                operation=operation,
            )
        )

    assert "All selector candidates failed" in str(exc_info.value)
    assert call_count == 1


def test_drag_fallback_retries_transient_timeout_and_recovers() -> None:
    executor = _executor(step_timeout_seconds=4)

    class _Browser:
        def __init__(self) -> None:
            self.calls = 0

        async def drag_and_drop(self, source_selector: str, target_selector: str) -> str:
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("Timeout 15000ms exceeded")
            return f"Dragged {source_selector} to {target_selector}"

    browser = _Browser()
    executor._browser = browser

    result = asyncio.run(
        executor._run_with_drag_fallback(
            raw_source_selector="#source",
            raw_target_selector="#target",
            selector_profile={},
            test_data={},
            run_domain=None,
        )
    )

    assert result == "Dragged #source to #target"
    assert browser.calls == 2
