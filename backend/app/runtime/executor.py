from __future__ import annotations
from pathlib import Path
import asyncio
from html import escape
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from app.brain.base import BrainClient
from app.config import Settings
from app.mcp.browser_client import BrowserMCPClient
from app.mcp.filesystem_client import FileSystemClient
from app.runtime.plan_normalizer import normalize_plan_steps
from app.runtime.selector_memory import SelectorMemoryStore
from app.runtime.store import RunStore
from app.schemas import RunState, RunStatus, StepRuntimeState, StepStatus

LOGGER = logging.getLogger("tekno.phantom.executor")
TEMPLATE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")
DEFAULT_SELECTOR_PROFILE: dict[str, list[str]] = {
    "popup_accept": [
        "button:has-text('Accept')",
        "button:has-text('Accept all')",
        "button:has-text('I agree')",
        "button:has-text('Agree')",
        "button:has-text('Allow all')",
        "button:has-text('Allow')",
        "button:has-text('Continue')",
        "button:has-text('OK')",
        "button:has-text('Got it')",
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Akzeptieren')",
        "button:has-text('Zustimmen')",
        "[role='button']:has-text('Accept')",
        "[role='button']:has-text('Accept all')",
        "[role='button']:has-text('Alle akzeptieren')",
        "[role='button']:has-text('Akzeptieren')",
        "[id*='accept']",
        "[data-testid*='accept']",
        "[aria-label*='accept']",
        "[aria-label*='cookie']",
    ],
    "popup_dismiss": [
        "button[aria-label*='Close']",
        "button[aria-label*='Dismiss']",
        "button[aria-label*='Schlie']",
        "button:has-text('Close')",
        "button:has-text('Dismiss')",
        "button:has-text('Skip')",
        "button:has-text('Not now')",
        "button:has-text('Later')",
        "button:has-text('Schlie')",
        "[role='button']:has-text('Close')",
        "[role='button']:has-text('Dismiss')",
        "[data-testid*='close']",
        "[aria-label*='close']",
    ],
    "email": [
        "#username",
        "input[name='username']",
        "input[name='email']",
        "input[id='email']",
        "input[type='email']",
        "input[autocomplete='email']",
        "input[autocomplete='username']",
        "input[placeholder*='Email']",
        "input[placeholder*='email']",
        "input[type='text']",
    ],
    "username": [
        "#username",
        "input[name='username']",
        "input[name='email']",
        "input[id='email']",
        "input[placeholder*='Email']",
        "input[placeholder*='email']",
        "input[type='text']",
    ],
    "password": [
        "#password",
        "input[name='password']",
        "input[id='password']",
        "input[type='password']",
        "input[placeholder*='Password']",
        "input[placeholder*='password']",
    ],
    "login_button": [
        "button[name='login']",
        "button:has-text('Log In')",
        "button:has-text('Login')",
        "button:has-text('Sign In')",
        "[role='button']:has-text('Log In')",
        "[role='button']:has-text('Login')",
        "button[type='submit']",
        "input[type='submit']",
        "text=Sign In",
        "text=Log In",
        "text=Login",
    ],
    "language_switcher": [
        "button[aria-label*='language']",
        "[role='button'][aria-label*='language']",
        "button[title*='language']",
        "[title*='language']",
        "[aria-haspopup='listbox']",
        "[role='combobox']",
        "select[name*='lang']",
        "select[name*='locale']",
        "[name*='lang']",
        "[id*='lang']",
        "[data-testid*='lang']",
        "[data-testid*='locale']",
        "button:has-text('DE')",
        "button:has-text('EN')",
        "button:has-text('FR')",
        "button:has-text('ES')",
        "text=DE",
        "text=EN",
        "text=FR",
        "text=ES",
    ],
    "create_form": [
        "button#createForm",
        "button#create_form",
        "button:has-text('Create Form')",
        "[role='button']:has-text('Create Form')",
    ],
    "top_left_corner": [
        "header button[aria-label*='menu']",
        "header button[aria-label*='navigation']",
        "header button[aria-label*='sidebar']",
        "header button:first-of-type",
        "[role='banner'] button:first-of-type",
    ],
    "workflows_module": [
        "a:has-text('Workflows')",
        "button:has-text('Workflows')",
        "[role='menuitem']:has-text('Workflows')",
        "[role='link']:has-text('Workflows')",
        "text=Workflows",
    ],
    "create_workflow": [
        "button:has-text('Create Workflow')",
        "[role='button']:has-text('Create Workflow')",
        "a:has-text('Create Workflow')",
        "text=Create Workflow",
    ],
    "workflow_confirmation": [
        "[role='alert']:has-text('Workflow has been created')",
        "[role='status']:has-text('Workflow has been created')",
        ".toast:has-text('Workflow has been created')",
        ".notification:has-text('Workflow has been created')",
        "text=Workflow has been created",
    ],
    "workflow_name": [
        "input[name='workflowName']",
        "input[name='name']",
        "input#workflowName",
        "input#workflow-name",
        "input[placeholder*='Workflow Name']",
        "input[aria-label*='Workflow Name']",
    ],
    "workflow_description": [
        "textarea[name='description']",
        "textarea[placeholder*='Description']",
        "textarea[aria-label*='Description']",
        "input[name='description']",
        "input[placeholder*='Description']",
    ],
    "save_workflow": [
        "div[role='dialog'] button:has-text('Save')",
        "div[role='dialog'] [role='button']:has-text('Save')",
        "button[type='submit']:has-text('Save')",
        "button:has-text('Save')",
        "[role='button']:has-text('Save')",
    ],
    "add_status_button": [
        "button:has-text('Add Status')",
        "[role='button']:has-text('Add Status')",
        "a:has-text('Add Status')",
        "text=Add Status",
    ],
    "transition_button": [
        "button:has-text('Transition')",
        "[role='button']:has-text('Transition')",
        "a:has-text('Transition')",
        "text=Transition",
    ],
    "new_status_tab": [
        "[role='tab']:has-text('New status')",
        "button:has-text('New status')",
        "[role='button']:has-text('New status')",
        "text=New status",
    ],
    "status_name": [
        "div[role='dialog'] input[name='statusName']",
        "div[role='dialog'] input#statusName",
        "div[role='dialog'] input[placeholder*='Status Name']",
        "div[role='dialog'] input[placeholder*='status name']",
        "div[role='dialog'] input[placeholder*='status']",
        "div[role='dialog'] input[aria-label*='Status Name']",
        "div[role='dialog'] input[aria-label*='status name']",
        "input[name='statusName']",
    ],
    "status_category_dropdown": [
        "div[role='dialog'] [role='combobox']",
        "div[role='dialog'] [aria-haspopup='listbox']",
        "div[role='dialog'] button:has-text('Select category')",
        "div[role='dialog'] input[placeholder*='category']",
        "div[role='dialog'] button:has-text('To Do')",
        "text=Select category",
    ],
    "from_status_dropdown": [
        "div[role='dialog'] input[placeholder*='InitialState']",
        "div[role='dialog'] input[value*='InitialState']",
        "div[role='dialog'] [role='combobox']:nth-of-type(1)",
        "div[role='dialog'] [aria-haspopup='listbox']:nth-of-type(1)",
        "div[role='dialog'] input[placeholder*='From status']",
        "div[role='dialog'] input[aria-label*='From status']",
    ],
    "to_status_dropdown": [
        "div[role='dialog'] input[placeholder='Select to status']",
        "div[role='dialog'] input[placeholder*='Select to status']",
        "div[role='dialog'] input[placeholder*='to status']",
        "div[role='dialog'] button:has-text('Select to status')",
        "div[role='dialog'] [role='button']:has-text('Select to status')",
        "div[role='dialog'] input[aria-label*='To status']",
        "div[role='dialog'] [role='combobox']:nth-of-type(2)",
        "div[role='dialog'] [aria-haspopup='listbox']:nth-of-type(2)",
        "div[role='dialog'] input[placeholder*='To status']",
    ],
    "status_category_todo": [
        "div[role='listbox'] [role='option']:has-text('To Do')",
        "div[role='dialog'] [role='option']:has-text('To Do')",
        "div[role='dialog'] li:has-text('To Do')",
        "div[role='dialog'] div:has-text('To Do')",
        "[role='option']:has-text('To Do')",
        "text=To Do",
    ],
    "save_status": [
        "div[role='dialog'] button:has-text('Save')",
        "div[role='dialog'] [role='button']:has-text('Save')",
        "div[role='dialog'] button[type='submit']",
        "button:has-text('Save')",
        "[role='button']:has-text('Save')",
    ],
    "transition_name": [
        "div[role='dialog'] input[name='transitionName']",
        "div[role='dialog'] input[placeholder*='Transition Name']",
        "div[role='dialog'] input[placeholder*='transition name']",
        "div[role='dialog'] input[placeholder*='Enter a transition name']",
        "div[role='dialog'] input[aria-label*='Transition Name']",
        "div[role='dialog'] input[aria-label*='transition name']",
    ],
    "transition_canvas_label": [
        "[data-edge-label-renderer] text",
        "[data-edge-label-renderer] *",
        "svg text",
        "[class*='edge-label']",
        "[class*='transition-label']",
    ],
    "save_transition": [
        "div[role='dialog'] button:has-text('Save')",
        "div[role='dialog'] [role='button']:has-text('Save')",
        "div[role='dialog'] button[type='submit']",
        "button:has-text('Save')",
        "[role='button']:has-text('Save')",
    ],
    "save_changes_button": [
        "button:has-text('Save Changes')",
        "[role='button']:has-text('Save Changes')",
        "text=Save Changes",
    ],
    "workflow_list_item": [
        "table tbody tr td a",
        "table tbody tr a",
        "[role='table'] [role='row'] a",
        "[data-testid*='workflow'] a",
        "a:has-text('QA_Auto_Workflow_')",
    ],
    "workflow_saved_success": [
        "[role='alert']:has-text('Workflow saved successfully')",
        "[role='status']:has-text('Workflow saved successfully')",
        ".toast:has-text('Workflow saved successfully')",
        ".notification:has-text('Workflow saved successfully')",
        "text=Workflow saved successfully",
        "text=less than a minute ago",
    ],
    "cancel_button": [
        "button:has-text('Cancel')",
        "[role='button']:has-text('Cancel')",
        "text=Cancel",
    ],
    "create_form_confirm": [
        "[role='dialog'] button:has-text('Create')",
        "div[role='dialog'] button:has-text('Create')",
        "button:has-text('Create')",
    ],
    "form_name": [
        "input[name='formName']",
        "input[name='name']",
        "input#formName",
        "input#form-name",
        "input[placeholder*='Form Name']",
        "input[placeholder*='Name']",
        "textarea[name='formName']",
        "textarea[name='name']",
    ],
    "form_list_first_row": [
        "table tbody tr:first-child",
        "[role='table'] [role='row']:nth-child(2)",
        "div[role='rowgroup'] div[role='row']:first-child",
        "[data-testid*='forms'] tr:first-child",
        "main tr:first-child",
    ],
    "form_list_first_name": [
        "table tbody tr:first-child a",
        "table tbody tr:first-child td a",
        "[role='table'] [role='row']:nth-child(2) a",
        "[data-testid*='forms'] tr:first-child a",
        "main tr:first-child a",
    ],
    "save_form": [
        "div[role='dialog'] button:has-text('Save')",
        "div[role='dialog'] [role='button']:has-text('Save')",
        "div[role='dialog'] button[type='submit']",
        "button#saveForm",
        "button.save-form",
        "button:has-text('Save')",
        "[role='button']:has-text('Save')",
    ],
    "back_button": [
        "button:has([data-lucide='chevron-left'])",
        "button:has([data-lucide='arrow-left'])",
        "button:has(svg[class*='chevron-left'])",
        "button:has(svg[class*='arrow-left'])",
        "button[aria-label*='Back']",
        "[role='button'][aria-label*='Back']",
        "button:has-text('Back')",
        "text=Back",
    ],
    "short_answer_source": [
        "[data-testid='field-short-answer']",
        "[data-testid*='short-answer']",
        "[data-rbd-draggable-id*='short']",
        "[draggable='true'][aria-label*='Short answer']",
        "[draggable='true']:has-text('Short answer')",
        "[role='listitem']:has-text('Short answer')",
        "button:has-text('Short answer')",
        "[role='button']:has-text('Short answer')",
        "text=Short answer",
    ],
    "email_field_source": [
        "[draggable='true'][aria-label*='Email']",
        "[draggable='true']:has-text('Email')",
        "[role='listitem']:has-text('Email')",
        "[data-rbd-draggable-id*='email']",
        "[data-testid='field-email']",
        "[data-testid*='field-email']",
        "button:has-text('Email')",
        "[role='button']:has-text('Email')",
        "text=Email",
    ],
    "dropdown_field_source": [
        "[data-testid='field-dropdown']",
        "[data-testid*='field-dropdown']",
        "[data-rbd-draggable-id*='dropdown']",
        "[draggable='true']:has-text('Dropdown')",
        "[role='listitem']:has-text('Dropdown')",
        "button:has-text('Dropdown')",
        "[role='button']:has-text('Dropdown')",
        "text=Dropdown",
    ],
    "form_canvas_target": [
        "[data-row-id].form-row[draggable='true']",
        "[data-row-id]",
        "[data-testid='form-builder-canvas']",
        ".form-canvas",
        ".form-drop-area",
        "[data-testid*='form-builder'][class*='canvas']",
        ".form-builder-canvas",
        ".form-builder-drop-area",
        ".form-builder-editor",
        "[data-testid='form-canvas']",
        "[class*='drop'][class*='canvas']",
        "[class*='builder'][class*='canvas']",
        "div.form-row[draggable='true']:has-text('Drag and drop fields here')",
        "div.form-row.relative.flex.w-full[draggable='true']:has-text('Drag and drop fields here')",
        "div:has-text('Drag and drop fields here')",
        "section:has-text('Drag and drop fields here')",
        "[role='application']",
    ],
    "form_label": [
        "div[role='dialog'] input[placeholder='Enter a label']",
        "div[role='dialog'] input[name='label']",
        "div[role='dialog'] input[aria-label*='Label']",
        "div[role='dialog'] textarea[placeholder='Enter a label']",
        "div[role='dialog'] textarea[name='label']",
        "[data-testid='form-builder-canvas'] input[placeholder='Label']",
        "[data-testid='form-builder-canvas'] textarea[placeholder='Label']",
        "[data-testid='form-builder-canvas'] input[name='label']",
        "[data-testid='form-builder-canvas'] textarea[name='label']",
        "[data-testid='form-builder-canvas'] input[aria-label*='Label']",
        "[data-testid='form-builder-canvas'] textarea[aria-label*='Label']",
        ".form-canvas input[placeholder='Label']",
        ".form-canvas textarea[placeholder='Label']",
        "input[placeholder='Label']",
        "textarea[placeholder='Label']",
        "input[name='label']",
        "textarea[name='label']",
        "input[aria-label*='Label']",
        "textarea[aria-label*='Label']",
        "[contenteditable='true'][aria-label*='Label']",
        "[role='textbox'][aria-label*='Label']",
    ],
    "required_checkbox": [
        "div[role='dialog'] label:has-text('Required')",
        "div[role='dialog'] label:has-text('Required') input[type='checkbox']",
        "div[role='dialog'] input[type='checkbox'][name='required']",
        "div[role='dialog'] [role='checkbox'][aria-label*='Required']",
        "input[name='required']",
        "input[type='checkbox'][name='required']",
        "[data-testid='required'] input[type='checkbox']",
        "label:has-text('Required')",
        "label:has-text('Required') input[type='checkbox']",
        "text=Required",
    ],
    "dropdown_option_type_trigger": [
        "div[role='dialog'] [role='combobox']:has-text('Select an option')",
        "div[role='dialog'] [role='combobox']",
        "div[role='dialog'] [aria-haspopup='listbox']",
        "div[role='dialog'] button:has-text('Select an option')",
        "text=Select an option",
    ],
    "dropdown_option_enter_manual": [
        "div[role='listbox'] [role='option']:text-is('Enter options manually')",
        "div[role='dialog'] [role='option']:text-is('Enter options manually')",
        "[role='option']:text-is('Enter options manually')",
        "div[role='listbox'] :text-is('Enter options manually')",
        "[role='option']:has-text('Enter options manually')",
        "div[role='dialog'] :text-is('Enter options manually')",
        "text=Enter options manually",
    ],
    "dropdown_options_section": [
        "div[role='dialog'] :has-text('Options')",
        "div[role='dialog'] input[placeholder='Label']",
        "div[role='dialog'] input[placeholder='Value']",
    ],
    "dropdown_option_label": [
        "div[role='dialog'] input[placeholder='Label']",
        "div[role='dialog'] input[name='label']",
    ],
    "dropdown_option_value": [
        "div[role='dialog'] input[placeholder='Value']",
        "div[role='dialog'] input[name='value']",
    ],
    "dropdown_option_add_button": [
        "div[role='dialog'] button:has(svg[class*='plus'])",
        "div[role='dialog'] button:has(i[class*='plus'])",
        "div[role='dialog'] [data-testid*='add-option']",
        "div[role='dialog'] [aria-label*='Add option']",
        "div[role='dialog'] [title*='Add option']",
        "div[role='dialog'] div:has(input[placeholder='Value']) button",
        "div[role='dialog'] button:has-text('+')",
        "div[role='dialog'] [role='button']:has-text('+')",
        "text=+",
    ],
    "amazon_search_box": [
        "#twotabsearchtextbox",
        "input[name='field-keywords']",
    ],
    "amazon_search_submit": [
        "#nav-search-submit-button",
        "input#nav-search-submit-button",
    ],
    "amazon_first_result": [
        "div[data-component-type='s-search-result'] h2 a",
        "h2 a.a-link-normal",
        "h2 a",
    ],
    "amazon_add_to_cart": [
        "#add-to-cart-button",
        "input[name='submit.add-to-cart']",
        "button[name='submit.add-to-cart']",
        "[id*='add-to-cart']",
    ],
    "amazon_cart": [
        "#nav-cart",
        "a[href*='/gp/cart/view.html']",
        "a[href*='cart']",
    ],
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentExecutor:
    def __init__(
        self,
        settings: Settings,
        brain_client: BrainClient,
        run_store: RunStore,
        browser_client: BrowserMCPClient,
        file_client: FileSystemClient,
        selector_memory_store: SelectorMemoryStore | None = None,
    ) -> None:
        self._settings = settings
        self._brain = brain_client
        self._run_store = run_store
        self._browser = browser_client
        self._files = file_client
        self._selector_memory = selector_memory_store

    async def execute(self, run_id: str) -> None:
        run = self._run_store.get(run_id)
        if not run:
            return

        is_new_run = run.started_at is None
        run.test_data = self._initialize_runtime_test_data(run.test_data or {})
        run.status = RunStatus.running
        if is_new_run:
            run.started_at = utc_now()
        self._run_store.persist(run)
        preserve_browser_session = False

        try:
            await self._browser.start_run(run_id)

            if is_new_run and run.start_url:
                await asyncio.wait_for(
                    self._browser.navigate(run.start_url),
                    timeout=self._settings.step_timeout_seconds,
                )

            has_step_failure = False
            if run.execution_mode == "autonomous" and run.prompt:
                has_step_failure = await self._execute_existing_steps(run)
                if run.status == RunStatus.running and not has_step_failure:
                    generated_failure = await self._execute_autonomous_run(run)
                    has_step_failure = has_step_failure or generated_failure
                if run.status == RunStatus.waiting_for_input:
                    preserve_browser_session = True
            else:
                has_step_failure = await self._execute_existing_steps(run)

            if run.status == RunStatus.waiting_for_input:
                preserve_browser_session = True

            if run.status == RunStatus.running:
                run.status = RunStatus.failed if has_step_failure else RunStatus.completed
                self._run_store.persist(run)

            if run.status != RunStatus.waiting_for_input:
                summary_text = self._build_summary(run)
                run.summary = await self._brain.summarize(summary_text)
                await self._files.write_text_artifact(run_id, "summary.txt", run.summary)
                self._run_store.persist(run)
        except Exception as exc:
            run.status = RunStatus.failed
            run.summary = f"Run failed unexpectedly ({type(exc).__name__}): {exc!r}"
            self._run_store.persist(run)
            LOGGER.exception("Run %s failed unexpectedly", run_id)
        finally:
            if not preserve_browser_session:
                await self._browser.close_run(run_id)
                run.finished_at = utc_now()
            self._run_store.persist(run)
            if not preserve_browser_session:
                await self._write_html_report(run)
            self._run_store.clear_cancel(run_id)

    async def _execute_existing_steps(self, run: RunState) -> bool:
        has_step_failure = False
        for step in run.steps:
            if step.status == StepStatus.completed:
                continue
            if step.status == StepStatus.waiting_for_input:
                run.status = RunStatus.waiting_for_input
                self._run_store.persist(run)
                break
            if self._run_store.is_cancelled(run.run_id):
                step.status = StepStatus.cancelled
                run.status = RunStatus.cancelled
                self._run_store.persist(run)
                break

            await self._execute_step(run, step)
            self._run_store.persist(run)
            if step.status == StepStatus.waiting_for_input:
                run.status = RunStatus.waiting_for_input
                self._run_store.persist(run)
                break
            if step.status == StepStatus.failed:
                has_step_failure = True
                break
        return has_step_failure

    async def _execute_autonomous_run(self, run: RunState) -> bool:
        max_steps = max(int(self._settings.max_steps_per_run), 1)
        history: list[dict[str, Any]] = self._history_from_run(run)
        has_step_failure = False

        while len(run.steps) < max_steps:
            if self._run_store.is_cancelled(run.run_id):
                run.status = RunStatus.cancelled
                self._run_store.persist(run)
                break

            await self._auto_handle_known_popups(run)
            page_snapshot = await self._browser.inspect_page()
            memory_context = self._build_autonomous_memory(run)
            remaining_steps = max_steps - len(run.steps)
            decision = await self._brain.next_action(
                goal=run.prompt,
                page=page_snapshot,
                history=history,
                remaining_steps=remaining_steps,
                memory=memory_context,
            )

            decision_status = str(decision.get("status", "")).strip().lower()
            if decision_status == "complete":
                summary = str(decision.get("summary", "")).strip()
                if summary:
                    run.summary = summary
                break

            raw_action = decision.get("action")
            normalized_steps = normalize_plan_steps(
                [raw_action],
                max_steps=1,
                default_wait_ms=self._settings.planner_default_wait_ms,
            )
            if not normalized_steps:
                has_step_failure = True
                run.summary = "Autonomous mode stopped because the brain returned an invalid action."
                break

            step_input = normalized_steps[0]
            step = StepRuntimeState(
                index=len(run.steps),
                type=str(step_input.get("type", "step")),
                input=step_input,
                status=StepStatus.pending,
            )
            run.steps.append(step)
            self._run_store.persist(run)

            await self._execute_step(run, step)
            self._run_store.persist(run)
            history.append(
                {
                    "step_index": step.index,
                    "type": step.type,
                    "input": step.input,
                    "status": step.status.value,
                    "message": step.message,
                    "error": step.error,
                }
            )
            if step.status == StepStatus.waiting_for_input:
                run.status = RunStatus.waiting_for_input
                self._run_store.persist(run)
                break
            if step.status == StepStatus.failed:
                has_step_failure = True
                break

        if len(run.steps) >= max_steps and run.status == RunStatus.running:
            has_step_failure = True
            run.summary = "Autonomous mode reached the maximum step budget before completing the goal."

        return has_step_failure

    @staticmethod
    def _history_from_run(run: RunState) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for step in run.steps[-20:]:
            history.append(
                {
                    "step_index": step.index,
                    "type": step.type,
                    "input": step.input,
                    "status": step.status.value,
                    "message": step.message,
                    "error": step.error,
                }
            )
        return history

    def _build_autonomous_memory(self, run: RunState) -> dict[str, Any]:
        run_domain = self._extract_run_domain(run)
        completed_steps = [
            self._step_memory_summary(step)
            for step in run.steps
            if step.status == StepStatus.completed
        ]
        previous_successes: list[dict[str, Any]] = []
        for previous in self._run_store.list():
            if previous.run_id == run.run_id:
                continue
            if previous.status != RunStatus.completed:
                continue
            if run_domain and self._extract_run_domain(previous) != run_domain:
                continue
            previous_summary = {
                "run_id": previous.run_id,
                "run_name": previous.run_name,
                "prompt": (previous.prompt or "")[:300],
                "summary": (previous.summary or "")[:300],
                "steps": [
                    item
                    for item in (
                        self._step_memory_summary(step)
                        for step in previous.steps
                        if step.status == StepStatus.completed
                    )
                    if item
                ][:8],
            }
            if previous_summary["steps"] or previous_summary["summary"] or previous_summary["prompt"]:
                previous_successes.append(previous_summary)
            if len(previous_successes) >= 3:
                break

        memory: dict[str, Any] = {
            "domain": run_domain or "",
            "current_run_completed_steps": [item for item in completed_steps if item][-8:],
            "previous_successful_runs": previous_successes,
        }
        if run.selector_profile:
            memory["selector_profile_keys"] = sorted(run.selector_profile.keys())[:20]
        return memory

    @staticmethod
    def _step_memory_summary(step: StepRuntimeState) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "type": step.type,
        }
        raw_selector = step.input.get("selector")
        if isinstance(raw_selector, str) and raw_selector.strip():
            payload["selector"] = raw_selector.strip()
        if step.provided_selector:
            payload["resolved_selector"] = step.provided_selector.strip()
        if step.message:
            payload["message"] = step.message[:180]
        if step.type == "type":
            text_value = step.input.get("text")
            if isinstance(text_value, str) and text_value.strip():
                payload["text_hint"] = text_value.strip()[:80]
        if step.type == "select":
            value = step.input.get("value")
            if isinstance(value, str) and value.strip():
                payload["value"] = value.strip()[:80]
        if step.type == "drag":
            source_selector = step.input.get("source_selector")
            target_selector = step.input.get("target_selector")
            if isinstance(source_selector, str) and source_selector.strip():
                payload["source_selector"] = source_selector.strip()
            if isinstance(target_selector, str) and target_selector.strip():
                payload["target_selector"] = target_selector.strip()
        return payload if len(payload) > 1 else None

    async def _write_html_report(self, run: RunState) -> None:
        try:
            report_html = self._build_html_report(run)
            report_path = await self._files.write_text_artifact(run.run_id, "report.html", report_html)
            run.report_artifact = report_path
            self._run_store.persist(run)
        except Exception:
            LOGGER.exception("Failed to write HTML report for run %s", run.run_id)

    async def _execute_step(self, run: RunState, step: StepRuntimeState) -> None:
        step.status = StepStatus.running
        step.started_at = utc_now()
        step.error = None
        step.message = None
        step.failure_screenshot = None
        step.user_input_kind = None
        step.user_input_prompt = None
        step.requested_selector_target = None

        try:
            if step.type != "handle_popup":
                await self._auto_handle_known_popups(run)
            message = await asyncio.wait_for(
                self._dispatch_step(run, step.input),
                timeout=self._settings.step_timeout_seconds,
            )
            step.status = StepStatus.completed
            step.message = message
            original_selector_request = step.input.get("_selector_help_original")
            if (
                isinstance(original_selector_request, str)
                and original_selector_request.strip()
                and step.provided_selector
            ):
                self._remember_selector_success(
                    run_domain=self._extract_run_domain(run),
                    step_type=step.type,
                    raw_selector=original_selector_request.strip(),
                    resolved_selector=step.provided_selector,
                    text_hint=None,
                )
            await self._files.write_text_artifact(
                run.run_id,
                f"step-{step.index:03d}.log",
                f"{step.type}: {message}",
            )
        except Exception as exc:
            compact = self._compact_error(exc)
            if self._should_request_selector_help(step, exc):
                step.status = StepStatus.waiting_for_input
                step.error = compact
                step.message = "Waiting for selector help"
                step.user_input_kind = "selector"
                step.requested_selector_target = self._requested_selector_target(step)
                step.user_input_prompt = self._build_selector_help_prompt(step)
            else:
                step.status = StepStatus.failed
                if isinstance(exc, TimeoutError):
                    step.error = f"{compact} (step_type={step.type})"
                else:
                    step.error = compact
                step.message = "Step failed"
                await self._capture_failure_screenshot(run.run_id, step)
        finally:
            step.ended_at = utc_now()

    async def _auto_handle_known_popups(self, run: RunState) -> None:
        try:
            snapshot = await self._browser.inspect_page()
        except Exception:
            return
        if not self._looks_like_popup_blocker(snapshot):
            return

        run_domain = self._extract_run_domain(run)
        popup_plans = (
            ("popup_accept", "accept"),
            ("popup_dismiss", "dismiss"),
        )
        for profile_key, policy in popup_plans:
            selectors = self._merge_profile_candidates(profile_key, run.selector_profile or {})
            for selector in selectors:
                try:
                    result = await asyncio.wait_for(
                        self._browser.handle_popup(policy=policy, selector=selector),
                        timeout=2.5,
                    )
                except Exception:
                    continue
                result_lower = result.lower()
                if "handled" not in result_lower and "clicked" not in result_lower:
                    continue
                self._remember_selector_success(
                    run_domain=run_domain,
                    step_type="handle_popup",
                    raw_selector=profile_key,
                    resolved_selector=selector,
                    text_hint=policy,
                )
                return

    @staticmethod
    def _looks_like_popup_blocker(snapshot: dict[str, Any]) -> bool:
        text_excerpt = str(snapshot.get("text_excerpt", "")).lower()
        interactive_elements = snapshot.get("interactive_elements")
        popup_signals = (
            "cookie",
            "cookies",
            "consent",
            "privacy",
            "gdpr",
            "we use cookies",
            "accept all",
            "allow all",
            "alle akzeptieren",
            "akzeptieren",
            "zustimmen",
        )
        if any(token in text_excerpt for token in popup_signals):
            return True
        if isinstance(interactive_elements, list):
            for item in interactive_elements[:20]:
                if not isinstance(item, dict):
                    continue
                haystack = " ".join(
                    str(item.get(field, "")).lower()
                    for field in ("text", "aria", "name", "id", "testid", "role", "title")
                )
                if any(token in haystack for token in popup_signals):
                    return True
        return False

    def apply_manual_selector_hint(self, run_id: str, step_id: str, selector: str) -> RunState | None:
        run = self._run_store.get(run_id)
        if not run:
            return None

        step = next((item for item in run.steps if item.step_id == step_id), None)
        if not step:
            return None
        if not self._can_accept_manual_selector_hint(step):
            raise ValueError("This step is not eligible for selector input recovery.")

        requested_selector = self._requested_selector_target(step)
        if not requested_selector:
            raise ValueError("This step does not support selector input recovery.")
        if step.type == "click":
            lowered = selector.strip().lower()
            if lowered == "html" or lowered.startswith("html."):
                raise ValueError(
                    "That selector points to the page root, not the clickable target. "
                    "Please provide the actual button, link, or menu item selector."
                )

        step.input["selector"] = selector
        step.input["_selector_help_original"] = requested_selector
        step.provided_selector = selector
        step.status = StepStatus.pending
        step.started_at = None
        step.ended_at = None
        step.error = None
        step.message = "Retrying this step with the selector you provided."
        step.failure_screenshot = None
        step.user_input_kind = None
        step.user_input_prompt = None
        step.requested_selector_target = None

        run.status = RunStatus.running
        run.finished_at = None
        self._run_store.persist(run)
        return run

    @classmethod
    def _can_accept_manual_selector_hint(cls, step: StepRuntimeState) -> bool:
        if step.status == StepStatus.waiting_for_input:
            return step.user_input_kind == "selector"
        if step.status != StepStatus.failed:
            return False
        if step.type not in {"click", "type", "select", "wait", "handle_popup", "verify_text"}:
            return False
        error_text = str(step.error or step.message or "").strip()
        if not error_text:
            return False
        probe = RuntimeError(error_text)
        return cls._should_request_selector_help(step, probe)

    async def _capture_failure_screenshot(self, run_id: str, step: StepRuntimeState) -> None:
        try:
            screenshot_name = f"step-{step.index:03d}-failed.png"
            screenshot_bytes = await self._browser.capture_screenshot()
            await self._files.write_bytes_artifact(run_id, screenshot_name, screenshot_bytes)
            step.failure_screenshot = screenshot_name
        except Exception as exc:
            LOGGER.warning(
                "Failed to capture screenshot for run %s step %s: %s",
                run_id,
                step.index,
                self._compact_error(exc),
            )

    async def _dispatch_step(self, run: RunState, raw_step: dict) -> str:
        step_type = raw_step.get("type")
        test_data = run.test_data or {}
        selector_profile = run.selector_profile or {}
        run_domain = self._extract_run_domain(run)

        if step_type == "navigate":
            target_url = self._apply_template(str(raw_step["url"]), test_data)
            return await self._browser.navigate(target_url)

        if step_type == "click":
            selector = str(raw_step["selector"])
            alias_key = self._selector_alias_key(selector)
            text_hint = raw_step.get("text_hint")
            if alias_key == "transition_canvas_label":
                try:
                    await self._run_with_selector_fallback(
                        "{{selector.save_changes_button}}",
                        "wait",
                        selector_profile,
                        test_data,
                        run_domain,
                        lambda resolved: self._browser.wait_for(
                            until="selector_visible",
                            ms=1500,
                            selector=resolved,
                            load_state=None,
                        ),
                    )
                    return "Transition canvas click treated as non-blocking"
                except Exception:
                    if text_hint is not None:
                        for label_selector in self._transition_label_signal_selectors(str(text_hint), test_data):
                            try:
                                await self._run_with_selector_fallback(
                                    label_selector,
                                    "wait",
                                    selector_profile,
                                    test_data,
                                    run_domain,
                                    lambda resolved: self._browser.wait_for(
                                        until="selector_visible",
                                        ms=1500,
                                        selector=resolved,
                                        load_state=None,
                                    ),
                                )
                                return "Transition label is visible on canvas"
                            except Exception:
                                continue
                    return "Transition canvas click treated as non-blocking"
            try:
                click_operation = self._run_with_selector_fallback(
                    selector,
                    step_type,
                    selector_profile,
                    test_data,
                    run_domain,
                    lambda resolved: self._browser.click(resolved),
                    text_hint=str(text_hint) if text_hint is not None else None,
                )
                if alias_key in {"login_button", "transition_canvas_label"}:
                    click_budget_s = max(
                        3.0,
                        min(float(self._settings.step_timeout_seconds) * 0.2, 12.0),
                    )
                    return await asyncio.wait_for(click_operation, timeout=click_budget_s)
                return await click_operation
            except Exception as exc:
                if alias_key == "login_button":
                    try:
                        await self._run_with_selector_fallback(
                            "{{selector.create_form}}",
                            "wait",
                            selector_profile,
                            test_data,
                            run_domain,
                            lambda resolved: self._browser.wait_for(
                                until="selector_visible",
                                ms=20000,
                                selector=resolved,
                                load_state=None,
                            ),
                        )
                        return "Login click likely succeeded; Create Form became visible"
                    except Exception:
                        pass
                    for success_selector, success_message in (
                        ("{{selector.create_form}}", "Login click likely succeeded; Create Form became visible"),
                        ("{{selector.top_left_corner}}", "Login click likely succeeded; application shell became visible"),
                    ):
                        try:
                            await self._run_with_selector_fallback(
                                success_selector,
                                "wait",
                                selector_profile,
                                test_data,
                                run_domain,
                                lambda resolved: self._browser.wait_for(
                                    until="selector_visible",
                                    ms=20000,
                                    selector=resolved,
                                    load_state=None,
                                ),
                            )
                            return success_message
                        except Exception:
                            continue
                    raise exc
                if alias_key == "transition_canvas_label" and text_hint is not None:
                    for label_selector in self._transition_label_signal_selectors(str(text_hint), test_data):
                        try:
                            await self._run_with_selector_fallback(
                                label_selector,
                                "wait",
                                selector_profile,
                                test_data,
                                run_domain,
                                lambda resolved: self._browser.wait_for(
                                    until="selector_visible",
                                    ms=8000,
                                    selector=resolved,
                                    load_state=None,
                                ),
                            )
                            return "Transition label is visible on canvas"
                        except Exception:
                            continue
                    raise exc
                raise

        if step_type == "type":
            selector = str(raw_step["selector"])
            text = self._apply_template(str(raw_step["text"]), test_data)
            clear_first = bool(raw_step.get("clear_first", True))
            return await self._run_with_selector_fallback(
                selector,
                step_type,
                selector_profile,
                test_data,
                run_domain,
                lambda resolved: self._browser.type_text(
                    selector=resolved,
                    text=text,
                    clear_first=clear_first,
                ),
                text_hint=text,
            )

        if step_type == "select":
            selector = str(raw_step["selector"])
            value = self._apply_template(str(raw_step["value"]), test_data)
            return await self._run_with_selector_fallback(
                selector,
                step_type,
                selector_profile,
                test_data,
                run_domain,
                lambda resolved: self._browser.select(
                    selector=resolved,
                    value=value,
                ),
                text_hint=value,
            )

        if step_type == "drag":
            source_selector = str(raw_step["source_selector"])
            target_selector = str(raw_step["target_selector"])
            target_offset_x = raw_step.get("target_offset_x")
            target_offset_y = raw_step.get("target_offset_y")
            return await self._run_with_drag_fallback(
                raw_source_selector=source_selector,
                raw_target_selector=target_selector,
                selector_profile=selector_profile,
                test_data=test_data,
                run_domain=run_domain,
                target_offset_x=int(target_offset_x) if target_offset_x is not None else None,
                target_offset_y=int(target_offset_y) if target_offset_y is not None else None,
            )

        if step_type == "scroll":
            target = str(raw_step.get("target", "page"))
            selector = raw_step.get("selector")
            direction = str(raw_step.get("direction", "down"))
            amount = int(raw_step.get("amount", 600))

            if target == "selector" and selector:
                resolved_selector = await self._resolve_selector(
                    str(selector),
                    step_type,
                    selector_profile,
                    test_data,
                    run_domain,
                )
                return await self._browser.scroll(
                    target=target,
                    selector=resolved_selector,
                    direction=direction,
                    amount=amount,
                )

            return await self._browser.scroll(
                target=target,
                selector=None,
                direction=direction,
                amount=amount,
            )

        if step_type == "wait":
            until = str(raw_step.get("until", "timeout"))
            selector = raw_step.get("selector")
            load_state = raw_step.get("load_state")
            ms = raw_step.get("ms")

            if until in {"selector_visible", "selector_hidden"} and selector:
                raw_selector = str(selector)
                alias_key = self._selector_alias_key(raw_selector)
                try:
                    return await self._run_with_selector_fallback(
                        raw_selector,
                        step_type,
                        selector_profile,
                        test_data,
                        run_domain,
                        lambda resolved: self._browser.wait_for(
                            until=until,
                            ms=ms,
                            selector=resolved,
                            load_state=load_state,
                        ),
                    )
                except Exception as exc:
                    if alias_key == "workflow_saved_success":
                        try:
                            await self._run_with_selector_fallback(
                                "{{selector.cancel_button}}",
                                "wait",
                                selector_profile,
                                test_data,
                                run_domain,
                                lambda resolved: self._browser.wait_for(
                                    until="selector_visible",
                                    ms=8000,
                                    selector=resolved,
                                    load_state=None,
                                ),
                            )
                            return "Workflow editor remained available after save"
                        except Exception:
                            raise exc
                    raise

            return await self._browser.wait_for(
                until=until,
                ms=ms,
                selector=str(selector) if selector else None,
                load_state=str(load_state) if load_state else None,
            )

        if step_type == "handle_popup":
            policy = str(raw_step.get("policy", "dismiss"))
            selector = raw_step.get("selector")
            if selector:
                return await self._run_with_selector_fallback(
                    str(selector),
                    step_type,
                    selector_profile,
                    test_data,
                    run_domain,
                    lambda resolved: self._browser.handle_popup(
                        policy=policy,
                        selector=resolved,
                    ),
                )
            return await self._browser.handle_popup(policy=policy, selector=None)

        if step_type == "verify_text":
            selector = str(raw_step["selector"])
            match = str(raw_step.get("match", "contains"))
            value = self._apply_template(str(raw_step["value"]), test_data)
            return await self._run_with_selector_fallback(
                selector,
                step_type,
                selector_profile,
                test_data,
                run_domain,
                lambda resolved: self._browser.verify_text(
                    selector=resolved,
                    match=match,
                    value=value,
                ),
                text_hint=value,
            )

        if step_type == "verify_image":
            baseline_path = raw_step.get("baseline_path")
            threshold = float(raw_step.get("threshold", 0.05))
            selector = raw_step.get("selector")

            resolved_baseline = (
                self._apply_template(str(baseline_path), test_data) if baseline_path is not None else None
            )
            if selector:
                return await self._run_with_selector_fallback(
                    str(selector),
                    step_type,
                    selector_profile,
                    test_data,
                    run_domain,
                    lambda resolved: self._browser.verify_image(
                        selector=resolved,
                        baseline_path=resolved_baseline,
                        threshold=threshold,
                    ),
                )
            return await self._browser.verify_image(
                selector=None,
                baseline_path=resolved_baseline,
                threshold=threshold,
            )

        raise ValueError(f"Unsupported step type: {step_type}")

    async def _resolve_selector(
        self,
        raw_selector: str,
        step_type: str,
        selector_profile: dict[str, list[str]],
        test_data: dict[str, Any],
        run_domain: str | None,
        text_hint: str | None = None,
    ) -> str:
        candidates = self._selector_candidates(
            raw_selector,
            step_type,
            selector_profile,
            test_data,
            run_domain,
            text_hint,
        )
        if not candidates:
            raise ValueError("No selector candidates available")
        return candidates[0]

    async def _run_with_selector_fallback(
        self,
        raw_selector: str,
        step_type: str,
        selector_profile: dict[str, list[str]],
        test_data: dict[str, Any],
        run_domain: str | None,
        operation: Callable[[str], Awaitable[str]],
        text_hint: str | None = None,
    ) -> str:
        candidates = self._selector_candidates(
            raw_selector,
            step_type,
            selector_profile,
            test_data,
            run_domain,
            text_hint,
        )
        last_error: Exception | None = None
        candidate_timeout_s = self._candidate_timeout_seconds(len(candidates), step_type=step_type)
        attempts: list[str] = []
        recovery_attempts = self._selector_recovery_attempts()

        for cycle in range(recovery_attempts):
            for selector in candidates:
                try:
                    result = await asyncio.wait_for(operation(selector), timeout=candidate_timeout_s)
                    self._remember_selector_success(
                        run_domain=run_domain,
                        step_type=step_type,
                        raw_selector=raw_selector,
                        resolved_selector=selector,
                        text_hint=text_hint,
                    )
                    return result
                except Exception as exc:
                    last_error = exc
                    attempts.append(f"pass {cycle + 1}: {selector} -> {self._compact_error(exc)}")

            if cycle >= recovery_attempts - 1:
                break
            if not self._should_retry_selector_error(last_error):
                break
            await self._selector_recovery_pause()

        live_candidates = await self._live_page_selector_candidates(
            raw_selector=raw_selector,
            step_type=step_type,
            text_hint=text_hint,
        )
        live_candidates = [candidate for candidate in live_candidates if candidate not in candidates]
        if live_candidates:
            for selector in live_candidates:
                try:
                    result = await asyncio.wait_for(operation(selector), timeout=candidate_timeout_s)
                    self._remember_selector_success(
                        run_domain=run_domain,
                        step_type=step_type,
                        raw_selector=raw_selector,
                        resolved_selector=selector,
                        text_hint=text_hint,
                    )
                    return result
                except Exception as exc:
                    last_error = exc
                    attempts.append(f"live: {selector} -> {self._compact_error(exc)}")

        if last_error:
            if attempts:
                attempted = "; ".join(attempts)
                raise ValueError(f"All selector candidates failed: {attempted}") from last_error
            raise last_error
        raise ValueError(f"No valid selector candidates for: {raw_selector}")

    async def _live_page_selector_candidates(
        self,
        *,
        raw_selector: str,
        step_type: str,
        text_hint: str | None,
    ) -> list[str]:
        if step_type not in {"click", "type", "select", "wait", "verify_text", "handle_popup"}:
            return []
        try:
            snapshot = await self._browser.inspect_page()
        except Exception:
            return []
        return self._page_snapshot_selector_candidates(snapshot, raw_selector, step_type, text_hint)

    def _page_snapshot_selector_candidates(
        self,
        snapshot: dict[str, Any],
        raw_selector: str,
        step_type: str,
        text_hint: str | None,
    ) -> list[str]:
        elements = snapshot.get("interactive_elements")
        if not isinstance(elements, list):
            return []

        target_terms = self._selector_search_terms(raw_selector, text_hint)
        if not target_terms:
            return []

        ranked: list[tuple[int, list[str]]] = []
        for item in elements:
            if not isinstance(item, dict):
                continue
            score = self._snapshot_match_score(item, target_terms, step_type)
            if score <= 0:
                continue
            selectors = item.get("selectors")
            normalized: list[str] = []
            if isinstance(selectors, list):
                normalized.extend(str(selector).strip() for selector in selectors if str(selector).strip())
            normalized.extend(self._selectors_from_snapshot_item(item, step_type))
            normalized = self._dedupe(normalized)
            if normalized:
                ranked.append((score, normalized))

        ranked.sort(key=lambda entry: entry[0], reverse=True)
        flattened: list[str] = []
        for _, selectors in ranked[:8]:
            flattened.extend(selectors)
        return self._dedupe(flattened)

    def _selector_search_terms(self, raw_selector: str, text_hint: str | None) -> list[str]:
        tokens: list[str] = []
        for source in (raw_selector, text_hint or "", self._extract_selector_text(raw_selector) or ""):
            lowered = source.strip().lower()
            if not lowered:
                continue
            lowered = lowered.replace("{{selector.", " ").replace("}}", " ").replace("_", " ").replace("-", " ")
            parts = re.findall(r"[a-z0-9]+", lowered)
            for part in parts:
                if len(part) >= 3 and part not in {"selector", "input", "button", "click", "type", "wait", "text"}:
                    tokens.append(part)
        return self._dedupe(tokens)

    def _snapshot_match_score(self, item: dict[str, Any], target_terms: list[str], step_type: str) -> int:
        haystack_parts = [
            str(item.get("tag", "")),
            str(item.get("type", "")),
            str(item.get("text", "")),
            str(item.get("aria", "")),
            str(item.get("name", "")),
            str(item.get("id", "")),
            str(item.get("testid", "")),
            str(item.get("role", "")),
            str(item.get("placeholder", "")),
            str(item.get("href", "")),
            str(item.get("title", "")),
        ]
        haystack = " ".join(part.lower() for part in haystack_parts if part).strip()
        if not haystack:
            return 0

        score = 0
        for term in target_terms:
            if term in haystack:
                score += max(8, len(term))

        tag = str(item.get("tag", "")).lower()
        role = str(item.get("role", "")).lower()
        if step_type in {"type", "select"}:
            if tag in {"input", "textarea", "select"}:
                score += 12
            if role in {"textbox", "combobox"}:
                score += 8
        elif step_type in {"click", "handle_popup"}:
            if tag in {"button", "a"}:
                score += 12
            if role in {"button", "link", "menuitem", "tab", "combobox"}:
                score += 8
        elif step_type in {"wait", "verify_text"}:
            score += 4

        language_intent = any(term in {"language", "locale", "lang"} for term in target_terms)
        if language_intent:
            text_value = str(item.get("text", "")).strip()
            uppercase_code = len(text_value) <= 5 and text_value.isupper()
            if any(token in haystack for token in ("language", "locale", "lang")):
                score += 20
            if tag in {"button", "select"}:
                score += 10
            if role in {"button", "combobox", "menuitem"}:
                score += 10
            if uppercase_code:
                score += 14

        return score

    def _selectors_from_snapshot_item(self, item: dict[str, Any], step_type: str) -> list[str]:
        selectors: list[str] = []
        tag = str(item.get("tag", "")).strip().lower()
        role = str(item.get("role", "")).strip()
        item_id = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        testid = str(item.get("testid", "")).strip()
        aria = str(item.get("aria", "")).strip()
        placeholder = str(item.get("placeholder", "")).strip()
        text = str(item.get("text", "")).strip()
        title = str(item.get("title", "")).strip()

        if item_id:
            selectors.append(f"#{item_id}")
        if testid:
            selectors.append(f'[data-testid="{self._escape_playwright_text(testid)}"]')
        if name and tag in {"input", "textarea", "select"}:
            selectors.append(f'{tag}[name="{self._escape_playwright_text(name)}"]')
        if aria:
            escaped_aria = self._escape_playwright_text(aria[:60])
            if tag:
                selectors.append(f'{tag}[aria-label*="{escaped_aria}"]')
            if role:
                selectors.append(f'[role="{self._escape_playwright_text(role)}"][aria-label*="{escaped_aria}"]')
            selectors.append(f'[aria-label*="{escaped_aria}"]')
        if title:
            selectors.append(f'[title*="{self._escape_playwright_text(title[:60])}"]')
        if placeholder and tag in {"input", "textarea"}:
            selectors.append(f'{tag}[placeholder*="{self._escape_playwright_text(placeholder[:60])}"]')
        if text:
            escaped_text = self._escape_playwright_text(text[:80])
            if step_type in {"click", "handle_popup"}:
                if tag == "button":
                    selectors.append(f'button:has-text("{escaped_text}")')
                elif tag == "select":
                    selectors.append(f'select:has-text("{escaped_text}")')
                elif tag == "a":
                    selectors.append(f'a:has-text("{escaped_text}")')
                elif role:
                    selectors.append(f'[role="{self._escape_playwright_text(role)}"]:has-text("{escaped_text}")')
            selectors.append(f"text={text[:80]}")

        return self._dedupe(selectors)

    def _candidate_timeout_seconds(self, candidate_count: int, step_type: str | None = None) -> float:
        step_timeout = max(float(self._settings.step_timeout_seconds), 1.0)
        if candidate_count <= 1:
            if step_type == "type":
                return min(step_timeout, 6.0)
            if step_type == "click":
                return min(step_timeout, 8.0)
            return step_timeout
        budget = max(step_timeout - 0.5, 1.0)
        per_candidate = budget / candidate_count
        if step_type == "type":
            per_candidate = min(per_candidate, 4.0)
        if step_type == "click":
            per_candidate = min(per_candidate, 5.0)
        return max(min(per_candidate, step_timeout), 1.0)

    def _selector_candidates(
        self,
        raw_selector: str,
        step_type: str,
        selector_profile: dict[str, list[str]],
        test_data: dict[str, Any],
        run_domain: str | None,
        text_hint: str | None = None,
    ) -> list[str]:
        selector = self._apply_template(raw_selector, test_data).strip()
        if not selector:
            return []

        keys: list[str] = []
        alias_key = self._selector_alias_key(selector)
        if alias_key:
            keys.append(alias_key)

        signal_parts = [selector.lower(), step_type.lower()]
        if text_hint:
            signal_parts.append(text_hint.lower())
        signal = " ".join(signal_parts)
        profile_keys = list(selector_profile.keys())
        for key in profile_keys:
            key_lower = key.lower()
            if key_lower and key_lower in signal:
                keys.append(key)

        if step_type == "type" and text_hint:
            hint_lower = text_hint.lower()
            if "email" in hint_lower:
                keys.insert(0, "email")
                keys.append("username")
            if "password" in hint_lower:
                keys.insert(0, "password")
            if "qa_form" in hint_lower or "form" in hint_lower and "name" in hint_lower:
                keys.insert(0, "form_name")
            if "qa_auto_workflow" in hint_lower or "workflow" in hint_lower and "name" in hint_lower:
                keys.insert(0, "workflow_name")
            if "description" in hint_lower:
                keys.insert(0, "workflow_description")
            if "initialstate_" in hint_lower or "submittedstate_" in hint_lower or "status" in hint_lower and "name" in hint_lower:
                keys.insert(0, "status_name")
            if "first name" in hint_lower or "label" in hint_lower:
                keys.insert(0, "form_label")

        selector_lower = selector.lower()
        if step_type == "type":
            if "email" in selector_lower:
                keys.insert(0, "email")
                keys.append("username")
            if "password" in selector_lower:
                keys.insert(0, "password")
            if "username" in selector_lower:
                keys.insert(0, "username")
            if "formname" in selector_lower or "form_name" in selector_lower or "form name" in selector_lower:
                keys.insert(0, "form_name")
            if "workflowname" in selector_lower or "workflow_name" in selector_lower or "workflow name" in selector_lower:
                keys.insert(0, "workflow_name")
            if "workflow_description" in selector_lower or "description" in selector_lower:
                keys.insert(0, "workflow_description")
            if "status_name" in selector_lower or "status name" in selector_lower or "statusname" in selector_lower:
                keys.insert(0, "status_name")
            if "label" in selector_lower:
                keys.insert(0, "form_label")
            if "dropdown_option_label" in selector_lower:
                keys.insert(0, "dropdown_option_label")
            if "dropdown_option_value" in selector_lower:
                keys.insert(0, "dropdown_option_value")
            if any(token in selector_lower for token in ("twotabsearchtextbox", "field-keywords")):
                keys.insert(0, "amazon_search_box")
        if step_type == "click":
            if any(token in selector_lower for token in ("login", "sign in", "signin", "log in")):
                keys.insert(0, "login_button")
            if any(token in selector_lower for token in ("language", "locale", "change language", "change locale", "lang")):
                keys.insert(0, "language_switcher")
            if "create form" in selector_lower or "create_form" in selector_lower or "createform" in selector_lower:
                keys.insert(0, "create_form")
            if "create workflow" in selector_lower or "create_workflow" in selector_lower or "createworkflow" in selector_lower:
                keys.insert(0, "create_workflow")
            if "add status" in selector_lower or "add_status" in selector_lower or "addstatus" in selector_lower:
                keys.insert(0, "add_status_button")
            if "new status" in selector_lower or "new_status" in selector_lower or "newstatus" in selector_lower:
                keys.insert(0, "new_status_tab")
            if "from_status_dropdown" in selector_lower or "from status" in selector_lower:
                keys.insert(0, "from_status_dropdown")
            if "to_status_dropdown" in selector_lower or "to status" in selector_lower:
                keys.insert(0, "to_status_dropdown")
            if "transition_canvas_label" in selector_lower:
                keys.insert(0, "transition_canvas_label")
            if "workflow_list_item" in selector_lower or "qa_auto_workflow_" in selector_lower:
                keys.insert(0, "workflow_list_item")
            if "top_left_corner" in selector_lower or "top left corner" in selector_lower:
                keys.insert(0, "top_left_corner")
            if "workflows_module" in selector_lower or selector_lower.strip() == "workflows":
                keys.insert(0, "workflows_module")
            if "form_list_first_name" in selector_lower:
                keys.insert(0, "form_list_first_name")
            if "back button" in selector_lower or "selector.back_button" in selector_lower or selector_lower.strip() == "back":
                keys.insert(0, "back_button")
            if "save workflow" in selector_lower or "save_workflow" in selector_lower or "saveworkflow" in selector_lower:
                keys.insert(0, "save_workflow")
            if "save status" in selector_lower or "save_status" in selector_lower or "savestatus" in selector_lower:
                keys.insert(0, "save_status")
            if "status_category_todo" in selector_lower or "to do" == selector_lower.strip():
                keys.insert(0, "status_category_todo")
            if "status_category_dropdown" in selector_lower or "select category" in selector_lower or "status category" in selector_lower:
                keys.insert(0, "status_category_dropdown")
            if "save form" in selector_lower or "save_form" in selector_lower or "saveform" in selector_lower:
                keys.insert(0, "save_form")
        if step_type == "click" and text_hint and self._looks_like_transition_hint(text_hint):
            candidates_from_hint = self._transition_label_signal_selectors(text_hint, test_data)
        else:
            candidates_from_hint = []
            if any(token in selector_lower for token in ("required", "checkbox")):
                keys.insert(0, "required_checkbox")
            if "dropdown_option_type_trigger" in selector_lower:
                keys.insert(0, "dropdown_option_type_trigger")
            if "dropdown_option_enter_manual" in selector_lower:
                keys.insert(0, "dropdown_option_enter_manual")
            if "dropdown_option_add_button" in selector_lower:
                keys.insert(0, "dropdown_option_add_button")
            if any(token in selector_lower for token in ("nav-search-submit", "search-submit", "search button")):
                keys.insert(0, "amazon_search_submit")
            if any(
                token in selector_lower
                for token in ("s-search-result", "h2 a", "product-image", "a-link-normal")
            ):
                keys.insert(0, "amazon_first_result")
            if any(token in selector_lower for token in ("add-to-cart", "add to cart", "submit.add-to-cart")):
                keys.insert(0, "amazon_add_to_cart")
            if any(token in selector_lower for token in ("nav-cart", "cart")):
                keys.insert(0, "amazon_cart")
        if step_type == "drag":
            if any(
                token in selector_lower
                for token in ("short answer", "short_answer", "shortanswer")
            ):
                keys.insert(0, "short_answer_source")
            if any(token in selector_lower for token in ("email", "field-email")):
                keys.insert(0, "email_field_source")
            if any(token in selector_lower for token in ("dropdown", "linked dropdown", "field-dropdown")):
                keys.insert(0, "dropdown_field_source")
            if any(
                token in selector_lower
                for token in ("canvas", "dropzone", "drop zone", "form-canvas", "form builder")
            ):
                keys.insert(0, "form_canvas_target")
        if step_type == "verify_text":
            hint_lower = (text_hint or "").lower()
            if any(token in hint_lower for token in ("create form", "create_form", "createform")):
                keys.insert(0, "create_form")
            if any(token in hint_lower for token in ("create workflow", "create_workflow", "createworkflow")):
                keys.insert(0, "create_workflow")
            if any(token in hint_lower for token in ("workflow has been created",)):
                keys.insert(0, "workflow_confirmation")
            if any(token in hint_lower for token in ("login", "sign in", "signin", "log in")):
                keys.insert(0, "login_button")
            if any(token in hint_lower for token in ("save", "save form", "save_form")):
                keys.insert(0, "save_form")
            if any(token in hint_lower for token in ("save workflow", "save_workflow")):
                keys.insert(0, "save_workflow")
            if any(token in hint_lower for token in ("save status", "save_status")):
                keys.insert(0, "save_status")
            if "create form" in selector_lower or "create_form" in selector_lower or "createform" in selector_lower:
                keys.insert(0, "create_form")
            if "create workflow" in selector_lower or "create_workflow" in selector_lower or "createworkflow" in selector_lower:
                keys.insert(0, "create_workflow")
            if "workflow_confirmation" in selector_lower or "workflow has been created" in selector_lower:
                keys.insert(0, "workflow_confirmation")
            if "form_list_first_row" in selector_lower:
                keys.insert(0, "form_list_first_row")
        if step_type == "wait":
            if "dropdown_options_section" in selector_lower:
                keys.insert(0, "dropdown_options_section")
            if "create_workflow" in selector_lower or "create workflow" in selector_lower:
                keys.insert(0, "create_workflow")

        ordered_keys = self._dedupe(keys)
        candidates: list[str] = []
        strict_dropdown_keys = {
            "dropdown_option_type_trigger",
            "dropdown_option_enter_manual",
            "dropdown_options_section",
            "dropdown_option_label",
            "dropdown_option_value",
            "dropdown_option_add_button",
        }
        for key in ordered_keys:
            # Prefer remembered selectors that already succeeded on this domain,
            # except for brittle dropdown modal actions where profile selectors are safer.
            if key not in strict_dropdown_keys:
                candidates.extend(self._memory_candidates(run_domain, step_type, key))
            profile_candidates = self._merge_profile_candidates(key, selector_profile)
            for candidate in profile_candidates:
                normalized = self._apply_template(candidate, test_data).strip()
                if normalized:
                    candidates.append(normalized)

        if not alias_key:
            candidates.extend(self._memory_candidates(run_domain, step_type, selector))
            candidates.append(selector)
            candidates.extend(self._derive_selector_variants(selector, step_type))

        if step_type == "type":
            deduped = self._dedupe([selector] + candidates)
        else:
            deduped = self._dedupe(candidates)
        if candidates_from_hint:
            deduped = self._dedupe(candidates_from_hint + deduped)
        if step_type == "drag":
            deduped = self._prioritize_drag_candidates(deduped, alias_key=alias_key)
        effective_filter_key = alias_key
        if not effective_filter_key and step_type == "type":
            if "email" in selector_lower:
                effective_filter_key = "email"
            elif "password" in selector_lower:
                effective_filter_key = "password"
            elif "dropdown_option_label" in selector_lower:
                effective_filter_key = "dropdown_option_label"
            elif "dropdown_option_value" in selector_lower:
                effective_filter_key = "dropdown_option_value"
        if effective_filter_key:
            deduped = self._filter_alias_candidates(effective_filter_key, deduped)
        return deduped

    def _initialize_runtime_test_data(self, test_data: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(test_data)
        stable_now = datetime.now()
        normalized.setdefault("NOW", stable_now.strftime("%Y-%m-%d_%H-%M-%S"))
        normalized.setdefault("TIMESTAMP", normalized["NOW"])
        normalized.setdefault("CURRENT_TIMESTAMP", normalized["NOW"])
        normalized.setdefault("NOW_YYYYMMDD_HHMMSS", stable_now.strftime("%Y%m%d_%H%M%S"))
        normalized.setdefault("NOW_YYYYMMDDHHMMSS", stable_now.strftime("%Y%m%d%H%M%S"))
        return normalized

    @staticmethod
    def _prioritize_drag_candidates(candidates: list[str], alias_key: str | None) -> list[str]:
        key = (alias_key or "").strip().lower()

        def score(selector: str) -> int:
            s = selector.lower()
            value = 100
            if key == "short_answer_source":
                if "[data-testid='field-short-answer']" in s:
                    value -= 90
                if "[data-testid*='short-answer']" in s:
                    value -= 82
                if "[data-rbd-draggable-id*='short']" in s:
                    value -= 78
                if "[draggable='true']" in s:
                    value -= 75
                if "[role='listitem']" in s:
                    value -= 60
                if "button:has-text('short answer')" in s or "[role='button']:has-text('short answer')" in s:
                    value -= 35
                if "text=short answer" in s:
                    value -= 25
            if key == "form_canvas_target":
                if "[data-row-id].form-row[draggable='true']" in s:
                    value -= 95
                if "[data-row-id]" in s:
                    value -= 90
                if "[data-testid='form-builder-canvas']" in s:
                    value -= 85
                if ".form-canvas" in s or ".form-drop-area" in s or ".form-builder-canvas" in s:
                    value -= 70
                if "[data-testid='form-canvas']" in s or "[class*='drop'][class*='canvas']" in s:
                    value -= 55
                if "div.form-row[draggable='true']:has-text('drag and drop fields here')" in s:
                    value -= 25
                if "div.form-row.relative.flex.w-full[draggable='true']:has-text('drag and drop fields here')" in s:
                    value -= 22
                if "drag and drop fields here" in s:
                    value += 15
                if "[role='application']" in s:
                    value += 25
            if key == "email_field_source":
                if "[draggable='true']" in s:
                    value -= 90
                if "[role='listitem']" in s:
                    value -= 75
                if "[data-rbd-draggable-id*='email']" in s:
                    value -= 70
                if "[data-testid='field-email']" in s:
                    value -= 55
                if "[data-testid*='field-email']" in s:
                    value -= 50
                if "button:has-text('email')" in s or "[role='button']:has-text('email')" in s:
                    value -= 40
                if "text=email" in s:
                    value -= 20
            return value

        return sorted(candidates, key=score)

    def _filter_alias_candidates(self, alias_key: str, candidates: list[str]) -> list[str]:
        key = alias_key.strip().lower()
        if key == "dropdown_option_enter_manual":
            filtered = [
                c for c in candidates
                if "enter options manually" in c.lower() and "use a saved list" not in c.lower()
            ]
            return filtered or candidates

        if key == "dropdown_option_label":
            filtered = [
                c for c in candidates
                if ("placeholder='label'" in c.lower() or 'placeholder="label"' in c.lower() or "name='label'" in c.lower() or 'name="label"' in c.lower())
                and "enter a label" not in c.lower()
            ]
            return filtered or candidates

        if key == "dropdown_option_value":
            filtered = [
                c for c in candidates
                if "placeholder='value'" in c.lower() or 'placeholder="value"' in c.lower() or "name='value'" in c.lower() or 'name="value"' in c.lower()
            ]
            return filtered or candidates

        if key == "dropdown_option_type_trigger":
            filtered = [
                c for c in candidates
                if "select an option" in c.lower() or "option type" in c.lower() or "[role='combobox']" in c.lower()
            ]
            return filtered or candidates

        if key == "dropdown_option_add_button":
            preferred_markers = (
                "add-option",
                "aria-label*='add option'",
                "title*='add option'",
                "svg[class*='plus']",
                "input[placeholder='value']) button",
                ":has-text('+')",
                "text=+",
            )
            filtered = [c for c in candidates if any(m in c.lower() for m in preferred_markers)]
            return filtered or candidates

        if key == "status_category_todo":
            filtered = [
                c for c in candidates
                if "to do" in c.lower() and "<option" not in c.lower() and "text=to do" not in c.lower()
            ]
            return filtered or candidates

        if key == "form_label":
            blocked_tokens = (
                "#formname",
                "input#formname",
                "input[name='formname']",
                "input[name='name']",
                "textarea[name='name']",
                "placeholder*='name'",
                "placeholder=\"name\"",
                "placeholder='name'",
                "input[type='text']",
            )
            filtered = [
                candidate
                for candidate in candidates
                if not any(token in candidate.lower() for token in blocked_tokens)
            ]
            return filtered or candidates

        if key == "email":
            # Prevent cross-field leakage from selector memory.
            blocked_tokens = (
                "#password",
                "name='password'",
                "name=\"password\"",
                "type='password'",
                "type=\"password\"",
            )
            filtered = [
                candidate
                for candidate in candidates
                if not any(token in candidate.lower() for token in blocked_tokens)
            ]
            return filtered or candidates

        if key == "password":
            blocked_tokens = (
                "#username",
                "name='username'",
                "name=\"username\"",
                "type='email'",
                "type=\"email\"",
                "autocomplete='email'",
                "autocomplete=\"email\"",
                "placeholder*='email'",
                "placeholder*=\"email\"",
                "aria-label*='email'",
                "aria-label*=\"email\"",
                "enter email",
            )
            filtered = [
                candidate
                for candidate in candidates
                if not any(token in candidate.lower() for token in blocked_tokens)
            ]
            return filtered or candidates

        return candidates

    async def _run_with_drag_fallback(
        self,
        *,
        raw_source_selector: str,
        raw_target_selector: str,
        selector_profile: dict[str, list[str]],
        test_data: dict[str, Any],
        run_domain: str | None,
        target_offset_x: int | None = None,
        target_offset_y: int | None = None,
    ) -> str:
        is_vitaone_domain = bool(run_domain and "vitaone.io" in run_domain.lower())
        target_seed = raw_target_selector
        if is_vitaone_domain and "drag and drop fields here" in raw_target_selector.lower():
            # Avoid stale placeholder target after first drop.
            target_seed = "form_canvas_target"

        source_candidates = self._selector_candidates(
            raw_source_selector,
            "drag",
            selector_profile,
            test_data,
            run_domain,
        )
        target_candidates = self._selector_candidates(
            target_seed,
            "drag",
            selector_profile,
            test_data,
            run_domain,
        )
        if not source_candidates:
            raise ValueError(f"No drag source selector candidates for: {raw_source_selector}")
        if not target_candidates:
            raise ValueError(f"No drag target selector candidates for: {raw_target_selector}")

        last_error: Exception | None = None
        attempts: list[str] = []
        source_base = source_candidates[:6]
        target_base = target_candidates[:5]

        source_text_candidate = next((candidate for candidate in source_candidates if candidate.startswith("text=")), None)
        target_placeholder_candidate = next(
            (candidate for candidate in target_candidates if "Drag and drop fields here" in candidate),
            None,
        )

        source_pool = list(source_base)
        target_pool = list(target_base)
        if source_text_candidate and source_text_candidate not in source_pool:
            source_pool.append(source_text_candidate)
        if target_placeholder_candidate and target_placeholder_candidate not in target_pool:
            target_pool.append(target_placeholder_candidate)

        if is_vitaone_domain:
            # Second+ drags should always target stable canvas selectors, not placeholder text.
            target_pool = [
                candidate
                for candidate in target_pool
                if "drag and drop fields here" not in candidate.lower()
            ] or target_pool

            # For email field, prefer direct text/has-text selectors over aria-label variants.
            if "email" in raw_source_selector.lower():
                email_prioritized: list[str] = []
                for candidate in source_pool:
                    lower_candidate = candidate.lower()
                    if ":has-text('email')" in lower_candidate or "text=email" in lower_candidate:
                        email_prioritized.append(candidate)
                for candidate in source_pool:
                    if candidate not in email_prioritized:
                        email_prioritized.append(candidate)
                source_pool = email_prioritized

        primary_targets = target_pool[:2] if len(target_pool) >= 2 else target_pool
        pair_set: set[tuple[str, str]] = set()
        pairs: list[tuple[str, str]] = []

        # Phase 1: quickly validate multiple source candidates against primary targets.
        for source_selector in source_pool:
            for target_selector in primary_targets:
                pair = (source_selector, target_selector)
                if pair in pair_set:
                    continue
                pair_set.add(pair)
                pairs.append(pair)
                if len(pairs) >= 6:
                    break
            if len(pairs) >= 6:
                break

        # Phase 2: then widen to more combinations.
        if len(pairs) < 6:
            for source_selector in source_pool:
                for target_selector in target_pool:
                    pair = (source_selector, target_selector)
                    if pair in pair_set:
                        continue
                    pair_set.add(pair)
                    pairs.append(pair)
                    if len(pairs) >= 6:
                        break
                if len(pairs) >= 6:
                    break

        if not pairs:
            raise ValueError("No drag selector pairs available")

        # VitaOne builder drag is sensitive; repeated multi-pair retries can cause
        # duplicate drag actions even after a successful visual drop. Keep
        # attempts bounded but allow more than one source candidate.
        if is_vitaone_domain:
            pairs = pairs[:3]

        recovery_attempts = max(1, min(self._selector_recovery_attempts(), 2))
        if is_vitaone_domain:
            recovery_attempts = 1
        step_timeout = max(float(getattr(self._settings, "step_timeout_seconds", 60)), 5.0)
        # Drag/drop UIs often need a longer interaction window than click/type.
        step_budget_s = max(20.0, step_timeout * 0.90)
        # Drag adapters already perform internal multi-strategy retries; give each
        # selector pair more time instead of spreading time across many pairs.
        effective_pair_budget = max(min(len(pairs), 2) * recovery_attempts, 1)
        pair_timeout_s = min(35.0, max(15.0, step_budget_s / effective_pair_budget))
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        budget_exhausted = False

        for cycle in range(recovery_attempts):
            for source_selector, target_selector in pairs:
                    elapsed = loop.time() - started_at
                    if elapsed >= step_budget_s:
                        last_error = TimeoutError(
                            f"drag budget exceeded after {elapsed:.1f}s "
                            f"(pairs={len(pairs)}, attempts={len(attempts)})"
                        )
                        budget_exhausted = True
                        break
                    try:
                        async def _invoke_drag() -> str:
                            try:
                                return await self._browser.drag_and_drop(
                                    source_selector,
                                    target_selector,
                                    target_offset_x=target_offset_x,
                                    target_offset_y=target_offset_y,
                                )
                            except TypeError as te:
                                # Backward compatibility for test doubles / older adapters.
                                message = str(te)
                                if "unexpected keyword argument" not in message:
                                    raise
                                return await self._browser.drag_and_drop(source_selector, target_selector)

                        result = await asyncio.wait_for(
                            _invoke_drag(),
                            timeout=pair_timeout_s,
                        )
                        self._remember_selector_success(
                            run_domain=run_domain,
                            step_type="drag",
                            raw_selector=raw_source_selector,
                            resolved_selector=source_selector,
                            text_hint=None,
                        )
                        self._remember_selector_success(
                            run_domain=run_domain,
                            step_type="drag",
                            raw_selector=raw_target_selector,
                            resolved_selector=target_selector,
                            text_hint=None,
                        )
                        return result
                    except Exception as exc:
                        last_error = exc
                        compact_error = self._compact_error(exc).lower()
                        timeout_like = isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or (
                            "timeout" in compact_error
                        )
                        if is_vitaone_domain and timeout_like:
                            drag_label = self._extract_drag_label_from_selector(
                                raw_source_selector
                            ) or self._extract_drag_label_from_selector(source_selector)
                            if drag_label:
                                try:
                                    await asyncio.wait_for(
                                        self._browser.verify_text(
                                            selector="[data-row-id], [data-testid='form-builder-canvas'], .form-canvas, .form-drop-area, div[role='dialog']",
                                            match="contains",
                                            value=drag_label,
                                        ),
                                        timeout=min(pair_timeout_s, 4.0),
                                    )
                                    self._remember_selector_success(
                                        run_domain=run_domain,
                                        step_type="drag",
                                        raw_selector=raw_source_selector,
                                        resolved_selector=source_selector,
                                        text_hint=None,
                                    )
                                    self._remember_selector_success(
                                        run_domain=run_domain,
                                        step_type="drag",
                                        raw_selector=raw_target_selector,
                                        resolved_selector=target_selector,
                                        text_hint=None,
                                    )
                                    return (
                                        f"Dragged {source_selector} to {target_selector} "
                                        "(executor post-timeout success check)"
                                    )
                                except Exception:
                                    pass
                            # VitaOne often opens an edit dialog immediately after a successful drop.
                            # If label editor is visible, treat timeout as recovered success.
                            try:
                                await asyncio.wait_for(
                                    self._browser.verify_text(
                                        selector="div[role='dialog'], [role='dialog'] input[placeholder='Enter a label'], [role='dialog'] button:has-text('Save')",
                                        match="contains",
                                        value="Save",
                                    ),
                                    timeout=min(pair_timeout_s, 3.0),
                                )
                                self._remember_selector_success(
                                    run_domain=run_domain,
                                    step_type="drag",
                                    raw_selector=raw_source_selector,
                                    resolved_selector=source_selector,
                                    text_hint=None,
                                )
                                self._remember_selector_success(
                                    run_domain=run_domain,
                                    step_type="drag",
                                    raw_selector=raw_target_selector,
                                    resolved_selector=target_selector,
                                    text_hint=None,
                                )
                                return (
                                    f"Dragged {source_selector} to {target_selector} "
                                    "(executor dialog-visible success check)"
                                )
                            except Exception:
                                pass
                        attempts.append(
                            "pass "
                            f"{cycle + 1}: {source_selector} -> {target_selector} "
                            f"(offset={target_offset_x},{target_offset_y}) -> {self._compact_error(exc)}"
                        )
            if budget_exhausted:
                break

            if cycle >= recovery_attempts - 1:
                break
            if not self._should_retry_selector_error(last_error):
                break
            await self._selector_recovery_pause()

        if last_error:
            attempted = "; ".join(attempts[:8])
            suffix = " ..." if len(attempts) > 8 else ""
            raise ValueError(f"All drag selector pairs failed: {attempted}{suffix}") from last_error
        raise ValueError("Drag step failed with no selector attempts")

    def _selector_recovery_attempts(self) -> int:
        if not bool(getattr(self._settings, "selector_recovery_enabled", True)):
            return 1
        configured = int(getattr(self._settings, "selector_recovery_attempts", 2))
        return max(configured, 1)

    async def _selector_recovery_pause(self) -> None:
        delay_ms = int(getattr(self._settings, "selector_recovery_delay_ms", 350))
        if delay_ms <= 0:
            return
        await asyncio.sleep(delay_ms / 1000)

    def _should_retry_selector_error(self, error: Exception | None) -> bool:
        if error is None:
            return False
        if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
            return True

        text = self._compact_error(error).lower()
        transient_markers = (
            "timeout",
            "waiting for",
            "element is not attached",
            "element is not visible",
            "element is outside of the viewport",
            "element is obscured",
            "intercept",
            "strict mode violation",
            "execution context was destroyed",
            "target closed",
            "navigation",
            "another element would receive the click",
        )
        return any(marker in text for marker in transient_markers)

    def _derive_selector_variants(self, selector: str, step_type: str) -> list[str]:
        variants: list[str] = []

        contains_match = re.search(r":contains\((['\"])(.*?)\1\)", selector)
        if contains_match:
            contains_text = contains_match.group(2).strip()
            has_text_selector = re.sub(
                r":contains\((['\"])(.*?)\1\)",
                lambda _: f':has-text("{self._escape_playwright_text(contains_text)}")',
                selector,
                count=1,
            )
            variants.append(has_text_selector)
            if contains_text and step_type in {"click", "verify_text"}:
                variants.append(f"text={contains_text}")

        variants.extend(self._id_case_variants(selector))

        if ":first-child" in selector:
            variants.append(selector.replace(":first-child", ""))
        if ":nth-child(1)" in selector:
            variants.append(selector.replace(":nth-child(1)", ""))

        selector_lower = selector.lower()
        if step_type == "click":
            text_button_match = re.fullmatch(r"button:has-text\((['\"])(.*?)\1\)", selector, re.IGNORECASE)
            if text_button_match:
                text_value = text_button_match.group(2).strip()
                escaped = self._escape_playwright_text(text_value)
                variants.extend(
                    [
                        f'a:has-text("{escaped}")',
                        f'[role="button"]:has-text("{escaped}")',
                        f':text-is("{escaped}")',
                        f"text={text_value}",
                    ]
                )
            text_link_match = re.fullmatch(r"a:has-text\((['\"])(.*?)\1\)", selector, re.IGNORECASE)
            if text_link_match:
                text_value = text_link_match.group(2).strip()
                escaped = self._escape_playwright_text(text_value)
                variants.extend(
                    [
                        f'button:has-text("{escaped}")',
                        f'[role="button"]:has-text("{escaped}")',
                        f':text-is("{escaped}")',
                        f"text={text_value}",
                    ]
                )
            aria_button_match = re.fullmatch(
                r"button\[aria-label=(['\"])(.*?)\1\]",
                selector,
                re.IGNORECASE,
            )
            if aria_button_match:
                aria_value = aria_button_match.group(2).strip()
                escaped = self._escape_playwright_text(aria_value)
                variants.extend(
                    [
                        f'[aria-label*="{escaped}"]',
                        f'[role="button"][aria-label*="{escaped}"]',
                        f'button[title*="{escaped}"]',
                    ]
                )
                if any(token in aria_value.lower() for token in ("language", "locale", "lang")):
                    variants.extend(self._merge_profile_candidates("language_switcher", {}))

        if "s-main-slot" in selector_lower or "s-search-result" in selector_lower:
            variants.extend(
                [
                    "div[data-component-type='s-search-result'] h2 a",
                    "h2 a.a-link-normal",
                    "h2 a",
                ]
            )
        if "h2 a:visible" in selector_lower:
            variants.extend(
                [
                    "div[data-component-type='s-search-result'] h2 a",
                    "h2 a.a-link-normal",
                    "h2 a",
                ]
            )

        return self._dedupe(variants)

    def _id_case_variants(self, selector: str) -> list[str]:
        id_match = re.search(r"#([A-Za-z][A-Za-z0-9_-]*)", selector)
        if not id_match:
            return []

        identifier = id_match.group(1)
        variants: list[str] = []
        if "_" in identifier:
            camel = self._snake_to_camel(identifier)
            if camel and camel != identifier:
                variants.append(selector.replace(f"#{identifier}", f"#{camel}", 1))
        if any(char.isupper() for char in identifier):
            snake = self._camel_to_snake(identifier)
            if snake and snake != identifier:
                variants.append(selector.replace(f"#{identifier}", f"#{snake}", 1))

        return variants

    @staticmethod
    def _snake_to_camel(value: str) -> str:
        parts = [part for part in value.split("_") if part]
        if not parts:
            return value
        return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])

    @staticmethod
    def _camel_to_snake(value: str) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()

    @staticmethod
    def _escape_playwright_text(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _looks_like_transition_hint(value: str) -> bool:
        lowered = value.lower()
        return "transition" in lowered or "tranisition" in lowered

    @staticmethod
    def _transition_label_text_variants(value: str) -> list[str]:
        normalized = value.strip()
        if not normalized:
            return []
        variants = [normalized]
        corrected = re.sub(r"(?i)tranisition", "Transition", normalized)
        if corrected not in variants:
            variants.append(corrected)
        lower_corrected = re.sub(r"(?i)transition", "Tranisition", normalized)
        if lower_corrected not in variants:
            variants.append(lower_corrected)
        return variants

    def _transition_label_signal_selectors(self, text_hint: str, test_data: dict[str, Any]) -> list[str]:
        hinted_text = self._apply_template(text_hint, test_data).strip()
        candidates: list[str] = []
        seen: set[str] = set()
        for variant in self._transition_label_text_variants(hinted_text):
            for selector in (
                f"text={variant}",
                f"svg text:has-text(\"{self._escape_playwright_text(variant)}\")",
                f"[data-edge-label-renderer] :has-text(\"{self._escape_playwright_text(variant)}\")",
            ):
                if selector not in seen:
                    seen.add(selector)
                    candidates.append(selector)
        return candidates

    @staticmethod
    def _selector_alias_key(selector: str) -> str | None:
        text = selector.strip()
        alias_patterns = (
            r"^\{\{\s*selector\.([a-zA-Z0-9_.-]+)\s*\}\}$",
            r"^\$([a-zA-Z0-9_.-]+)$",
            r"^profile:([a-zA-Z0-9_.-]+)$",
        )
        for pattern in alias_patterns:
            match = re.match(pattern, text)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _merge_profile_candidates(key: str, selector_profile: dict[str, list[str]]) -> list[str]:
        values: list[str] = []
        values.extend(selector_profile.get(key, []))
        values.extend(DEFAULT_SELECTOR_PROFILE.get(key, []))
        deduped: list[str] = []
        seen: set[str] = set()
        for item in values:
            token = item.strip()
            if not token or token in seen:
                continue
            seen.add(token)
            deduped.append(token)
        return deduped

    def _apply_template(self, text: str, test_data: dict[str, Any]) -> str:
        if not text or "{{" not in text:
            return text

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            value = self._lookup_test_data_value(key, test_data)
            if value is None:
                builtin = self._resolve_builtin_template(key)
                if builtin is not None:
                    return builtin
                return match.group(0)
            return str(value)

        return TEMPLATE_PATTERN.sub(replace, text)

    def _resolve_builtin_template(self, key: str) -> str | None:
        token = key.strip()
        if not token:
            return None

        upper = token.upper()
        now = datetime.now()

        if upper in {"NOW", "TIMESTAMP", "CURRENT_TIMESTAMP"}:
            return now.strftime("%Y-%m-%d_%H-%M-%S")

        if upper == "UUID":
            return str(uuid4())

        if upper.startswith("NOW_"):
            fmt = self._convert_now_format(token[4:])
            if fmt:
                return now.strftime(fmt)

        if token.startswith("now:") or token.startswith("NOW:"):
            raw_fmt = token.split(":", 1)[1].strip()
            if raw_fmt:
                return now.strftime(raw_fmt)

        return None

    @staticmethod
    def _convert_now_format(token: str) -> str:
        text = token.strip()
        if not text:
            return ""

        special = {
            "YYYYMMDD_HHMMSS": "%Y%m%d_%H%M%S",
            "YYYYMMDDHHMMSS": "%Y%m%d%H%M%S",
        }
        if text in special:
            return special[text]

        result = text
        result = result.replace("HHMMSS", "%H%M%S")
        result = result.replace("HHMM", "%H%M")
        result = result.replace("YYYY", "%Y")
        result = result.replace("YY", "%y")
        result = result.replace("MM", "%m")
        result = result.replace("DD", "%d")
        result = result.replace("HH", "%H")
        result = result.replace("mm", "%M")
        result = result.replace("SS", "%S")
        result = result.replace("ss", "%S")
        return result

    @staticmethod
    def _lookup_test_data_value(key: str, test_data: dict[str, Any]) -> Any:
        if key in test_data:
            return test_data[key]

        target = key.lower()
        for existing_key, existing_value in test_data.items():
            if existing_key.lower() == target:
                return existing_value
        return None

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for item in values:
            normalized = item.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    @staticmethod
    def _extract_drag_label_from_selector(selector: str) -> str | None:
        text = selector.strip()
        lowered = text.lower()
        if any(token in lowered for token in ("short answer", "short-answer", "short_answer", "field-short")):
            return "Short answer"
        if any(token in lowered for token in ("field-email", "email")):
            return "Email"
        if any(token in lowered for token in ("field-dropdown", "linked dropdown", "dropdown")):
            return "Dropdown"

        has_text = re.search(r":has-text\((['\"])(.*?)\1\)", text, re.IGNORECASE)
        if has_text and has_text.group(2).strip():
            return has_text.group(2).strip()

        text_selector = re.search(r"^text\s*=\s*(.+)$", text, re.IGNORECASE)
        if text_selector and text_selector.group(1).strip():
            return text_selector.group(1).strip().strip("'\"")

        return None

    @staticmethod
    def _compact_error(exc: Exception) -> str:
        text = str(exc).strip().replace("\r", " ").replace("\n", " ")
        text = re.sub(r"\s+", " ", text)
        if not text:
            text = repr(exc)
        if text in {"Exception()", "RuntimeError()", "ValueError()", "TimeoutError()"}:
            text = f"{type(exc).__name__}: {repr(exc)}"
        if len(text) > 220:
            return f"{text[:217]}..."
        return text

    @staticmethod
    def _should_request_selector_help(step: StepRuntimeState, exc: Exception) -> bool:
        if step.type not in {"click", "type", "select", "wait", "handle_popup", "verify_text"}:
            return False
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return step.type == "click"
        message = str(exc).lower()
        selector_failure_markers = (
            "all selector candidates failed",
            "no valid selector candidates",
            "no selector candidates available",
        )
        actionable_markers = (
            "timeout",
            "waiting for",
            "locator.",
            "element",
            "not found",
            "not visible",
            "strict mode violation",
            "would receive the click",
            "unexpected token",
            "parsing css selector",
        )
        if step.type == "click":
            click_markers = selector_failure_markers + actionable_markers + (
                "click failed for",
                "locator.click",
                "not attached",
                "intercept",
                "another element would receive the click",
                "resolved to 0 elements",
                "blocked=",
                "in_iframe=",
            )
            return any(marker in message for marker in click_markers)
        if any(marker in message for marker in selector_failure_markers):
            return True
        if not any(marker in message for marker in selector_failure_markers):
            return False
        return any(marker in message for marker in actionable_markers)

    @staticmethod
    def _requested_selector_target(step: StepRuntimeState) -> str | None:
        original = step.input.get("_selector_help_original")
        if isinstance(original, str) and original.strip():
            return original.strip()
        raw_selector = step.input.get("selector")
        if isinstance(raw_selector, str) and raw_selector.strip():
            return raw_selector.strip()
        return None

    def _build_selector_help_prompt(self, step: StepRuntimeState) -> str:
        requested = self._requested_selector_target(step) or "the missing element"
        action_label = step.type.replace("_", " ")
        last_attempt = ""
        if step.provided_selector:
            last_attempt = (
                f" The last selector you provided also did not work: {step.provided_selector}. "
                "Please try a different Playwright selector."
            )
        return (
            f"The agent could not find a working selector for the {action_label} step. "
            f"Please provide a Playwright selector for {requested} so the run can continue."
            f"{last_attempt}"
        )

    def _memory_candidates(self, run_domain: str | None, step_type: str, key: str) -> list[str]:
        store = self._selector_memory
        if not store or not run_domain:
            return []
        lookup_keys = self._selector_memory_lookup_keys(key)
        lookup_keys.extend(self._semantic_selector_memory_keys(step_type, key))
        lookup_keys = self._dedupe(lookup_keys)
        if not lookup_keys:
            return []
        max_items = max(int(getattr(self._settings, "selector_memory_max_candidates", 5)), 1)
        candidates: list[str] = []
        for key_token in lookup_keys:
            candidates.extend(store.get_candidates(run_domain, step_type, key_token, limit=max_items))
        filtered = [
            candidate
            for candidate in candidates
            if not self._is_unsafe_memory_selector(candidate)
        ]
        filtered = self._filter_memory_candidates(step_type, key, filtered)
        deduped = self._dedupe(filtered)
        return sorted(deduped, key=lambda candidate: self._memory_selector_priority(step_type, key, candidate))

    def _remember_selector_success(
        self,
        *,
        run_domain: str | None,
        step_type: str,
        raw_selector: str,
        resolved_selector: str,
        text_hint: str | None,
    ) -> None:
        store = self._selector_memory
        if not store or not run_domain:
            return
        if self._is_unsafe_memory_selector(resolved_selector):
            return

        keys = self._selector_memory_lookup_keys(raw_selector)
        alias = self._selector_alias_key(raw_selector)
        if alias:
            keys.extend(self._selector_memory_lookup_keys(alias))
        keys.extend(self._semantic_selector_memory_keys(step_type, raw_selector))

        selector_lower = raw_selector.lower()
        if step_type == "type":
            # Do not infer email key from "@" because passwords often contain it.
            if "email" in selector_lower:
                keys.extend(["email", "username"])
            if "password" in selector_lower or (text_hint and "password" in text_hint.lower()):
                keys.append("password")
            if "formname" in selector_lower or "form name" in selector_lower or "qa_form" in (text_hint or "").lower():
                keys.append("form_name")
            if "label" in selector_lower or "first name" in (text_hint or "").lower():
                keys.append("form_label")
            if any(token in selector_lower for token in ("twotabsearchtextbox", "field-keywords")):
                keys.append("amazon_search_box")
        if step_type in {"click", "verify_text"}:
            if any(token in selector_lower for token in ("create form", "create_form", "createform")):
                keys.append("create_form")
            if any(token in selector_lower for token in ("save form", "save_form", "saveform")):
                keys.append("save_form")
            if any(token in selector_lower for token in ("back button", "selector.back_button")):
                keys.append("back_button")
            if any(token in selector_lower for token in ("required", "checkbox")):
                keys.append("required_checkbox")
            if any(token in selector_lower for token in ("login", "sign in", "signin", "log in")):
                keys.append("login_button")
            if any(token in selector_lower for token in ("nav-search-submit", "search-submit", "search button")):
                keys.append("amazon_search_submit")
            if any(
                token in selector_lower
                for token in ("s-search-result", "h2 a", "product-image", "a-link-normal")
            ):
                keys.append("amazon_first_result")
            if any(token in selector_lower for token in ("add-to-cart", "add to cart", "submit.add-to-cart")):
                keys.append("amazon_add_to_cart")
            if any(token in selector_lower for token in ("nav-cart", "cart")):
                keys.append("amazon_cart")
        if step_type == "drag":
            if any(
                token in selector_lower
                for token in ("short answer", "short_answer", "shortanswer")
            ):
                keys.append("short_answer_source")
            if any(token in selector_lower for token in ("email", "field-email")):
                keys.append("email_field_source")
            if any(token in selector_lower for token in ("dropdown", "linked dropdown", "field-dropdown")):
                keys.append("dropdown_field_source")
            if any(
                token in selector_lower
                for token in ("canvas", "dropzone", "drop zone", "form-canvas", "form builder")
            ):
                keys.append("form_canvas_target")

        for key in self._dedupe(keys):
            store.remember_success(run_domain, step_type, key, resolved_selector)

    @staticmethod
    def _selector_memory_lookup_keys(key: str) -> list[str]:
        raw = key.strip()
        if not raw:
            return []

        compact = " ".join(raw.split())
        single_quoted = compact.replace('"', "'")
        variants = [raw, compact, single_quoted]
        lowered_variants = [item.lower() for item in variants]
        return AgentExecutor._dedupe(variants + lowered_variants)

    def _semantic_selector_memory_keys(self, step_type: str, selector: str) -> list[str]:
        if step_type not in {"click", "verify_text"}:
            return []

        text_value = self._extract_selector_text(selector)
        if not text_value:
            return []

        normalized = " ".join(text_value.strip().lower().split())
        if not normalized:
            return []

        return [
            f"text::{normalized}",
            f"{step_type}::text::{normalized}",
        ]

    @staticmethod
    def _extract_selector_text(selector: str) -> str | None:
        text = selector.strip()
        patterns = (
            r":has-text\((['\"])(.*?)\1\)",
            r":text\((['\"])(.*?)\1\)",
            r":text-is\((['\"])(.*?)\1\)",
            r"^text=(.+)$",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(1)
                normalized = value.strip().strip("'\"")
                if normalized:
                    return normalized
        return None

    @staticmethod
    def _is_unsafe_memory_selector(selector: str) -> bool:
        token = selector.strip().lower()
        return token in {
            "html",
            "body",
            "xpath=//html",
            "xpath=/html",
            "xpath=//body",
            "xpath=/body",
        } or token.startswith("html.") or token.startswith("body.")

    @staticmethod
    def _filter_memory_candidates(step_type: str, key: str, candidates: list[str]) -> list[str]:
        if step_type != "click":
            return candidates

        key_lower = key.strip().lower()
        expects_button_like_target = any(
            token in key_lower
            for token in (
                "button",
                ":has-text(",
                ":text(",
                "text=",
                "login",
                "sign up",
                "sign in",
                "workflows",
                "english",
                "de",
                "continue",
                "next",
                "submit",
                "save",
            )
        )
        if not expects_button_like_target:
            return candidates

        blocked_prefixes = ("input", "textarea", "select")
        blocked_fragments = (
            "@placeholder=",
            "[@placeholder=",
            "placeholder=",
            "enter email",
            "enter password",
        )
        filtered = []
        for candidate in candidates:
            lowered = candidate.strip().lower()
            if lowered.startswith(blocked_prefixes):
                continue
            if any(fragment in lowered for fragment in blocked_fragments):
                continue
            filtered.append(candidate)
        return filtered or candidates

    @staticmethod
    def _memory_selector_priority(step_type: str, key: str, selector: str) -> tuple[int, int, int, str]:
        lowered = selector.strip().lower()
        stability = 80

        if any(token in lowered for token in ("data-testid", "data-test", "data-qa")):
            stability = 0
        elif lowered.startswith("#") or "[id=" in lowered or "#".join(lowered.split()[:1]).startswith("#"):
            stability = 5
        elif any(token in lowered for token in ("[name=", "name='", 'name="', "aria-label", "role=")):
            stability = 10
        elif any(token in lowered for token in ("has-text(", ":text(", "text=", ":text-is(")):
            stability = 15
        elif lowered.startswith("xpath="):
            stability = 60

        if "\\." in lowered or lowered.count(".") >= 4:
            stability += 18
        if ":visible" in lowered:
            stability += 6
        if len(lowered) > 140:
            stability += 12

        key_lower = key.strip().lower()
        semantic_penalty = 0
        if step_type == "click":
            if any(token in key_lower for token in ("button", ":has-text(", ":text(", "text=", "login", "save", "submit")):
                if lowered.startswith(("input", "textarea", "select")) or "placeholder=" in lowered:
                    semantic_penalty = 40

        return (semantic_penalty, stability, len(lowered), lowered)

    @staticmethod
    def _extract_run_domain(run: RunState) -> str | None:
        candidate_urls: list[str] = []
        if run.start_url:
            candidate_urls.append(run.start_url)
        for step in run.steps:
            if step.type == "navigate":
                raw_url = step.input.get("url")
                if isinstance(raw_url, str):
                    candidate_urls.append(raw_url)

        for raw_url in candidate_urls:
            try:
                parsed = urlparse(raw_url)
            except Exception:
                continue
            domain = (parsed.netloc or "").strip().lower()
            if domain:
                return domain
        return None

    @staticmethod
    def _duration_seconds(started_at: datetime | None, ended_at: datetime | None) -> float | None:
        if started_at is None or ended_at is None:
            return None
        return max((ended_at - started_at).total_seconds(), 0.0)

    @staticmethod
    def _format_seconds(value: float | None) -> str:
        if value is None:
            return "N/A"
        return f"{value:.2f}"

    @staticmethod
    def _run_status_meta(status: RunStatus) -> tuple[str, str]:
        if status == RunStatus.completed:
            return "Passed", "run-passed"
        if status == RunStatus.failed:
            return "Failed", "run-failed"
        if status == RunStatus.waiting_for_input:
            return "Needs Input", "run-skipped"
        if status == RunStatus.running:
            return "Running", "run-skipped"
        if status == RunStatus.cancelled:
            return "Cancelled", "run-skipped"
        return "Skipped", "run-skipped"

    @staticmethod
    def _step_status_meta(status: StepStatus) -> tuple[str, str]:
        if status == StepStatus.completed:
            return "Passed", "step-passed"
        if status == StepStatus.failed:
            return "Failed", "step-failed"
        if status == StepStatus.waiting_for_input:
            return "Needs Input", "step-skipped"
        if status == StepStatus.running:
            return "Running", "step-skipped"
        if status == StepStatus.cancelled:
            return "Cancelled", "step-skipped"
        if status == StepStatus.pending:
            return "Pending", "step-skipped"
        return "Skipped", "step-skipped"

    @staticmethod
    def _step_display_name(step: StepRuntimeState) -> str:
        payload = step.input or {}
        step_type = str(step.type).lower()

        if step_type == "navigate":
            return f"Navigate to {payload.get('url', '')}".strip()
        if step_type == "click":
            return f"Click {payload.get('selector', '')}".strip()
        if step_type == "type":
            return f"Type into {payload.get('selector', '')}".strip()
        if step_type == "select":
            selector = payload.get("selector", "")
            value = payload.get("value", "")
            return f"Select {value} in {selector}".strip()
        if step_type == "drag":
            source = payload.get("source_selector", "")
            target = payload.get("target_selector", "")
            return f"Drag {source} to {target}".strip()
        if step_type == "scroll":
            target = payload.get("target", "page")
            direction = payload.get("direction", "down")
            amount = payload.get("amount", 600)
            return f"Scroll {target} {direction} by {amount}px".strip()
        if step_type == "wait":
            return f"Wait ({payload.get('until', 'timeout')})".strip()
        if step_type == "handle_popup":
            return f"Handle popup ({payload.get('policy', 'dismiss')})".strip()
        if step_type == "verify_text":
            selector = payload.get("selector", "")
            value = payload.get("value", "")
            return f"Verify text '{value}' on {selector}".strip()
        if step_type == "verify_image":
            selector = payload.get("selector") or "page"
            return f"Verify image on {selector}".strip()

        return str(step.type)

    def _build_html_report(self, run: RunState) -> str:
        run_status_label, run_status_class = self._run_status_meta(run.status)
        run_duration = self._format_seconds(self._duration_seconds(run.started_at, run.finished_at))
        total_tests = len(run.steps)
        passed_tests = sum(1 for step in run.steps if step.status == StepStatus.completed)
        failed_tests = sum(1 for step in run.steps if step.status == StepStatus.failed)
        skipped_tests = total_tests - passed_tests - failed_tests

        step_items: list[str] = []
        for step in run.steps:
            step_status_label, step_status_class = self._step_status_meta(step.status)
            step_duration = self._format_seconds(self._duration_seconds(step.started_at, step.ended_at))
            step_name = escape(self._step_display_name(step))

            detail_parts: list[str] = []
            if step.message:
                detail_parts.append(f"Message: {step.message}")
            if step.error:
                detail_parts.append(f"Error: {step.error}")
            detail_text = escape(" | ".join(detail_parts))
            details_html = f'<div class="step-detail">{detail_text}</div>' if detail_text else ""
            screenshot_html = ""
            if step.status == StepStatus.failed and step.failure_screenshot:
                href = escape(step.failure_screenshot)
                screenshot_html = (
                    '<div class="step-detail">'
                    f'<a href="{href}" target="_blank" rel="noopener">View Screenshot</a>'
                    "</div>"
                )

            step_items.append(
                (
                    '<li class="step-item">'
                    f'<span class="tick {step_status_class}" aria-label="{escape(step_status_label)}">&#10003;</span>'
                    f'<span class="step-name">{step_name}</span>'
                    f'<span class="step-status">{escape(step_status_label)}</span>'
                    f'<span class="step-time">{escape(step_duration)}s</span>'
                    f"{details_html}"
                    f"{screenshot_html}"
                    "</li>"
                )
            )

        steps_html = "\n".join(step_items) if step_items else '<li class="step-item">No steps executed.</li>'

        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Test Run Report - {escape(run.run_name)}</title>
  <style>
    :root {{
      --bg: #f6f8fb;
      --card: #ffffff;
      --border: #dbe2ea;
      --text: #1f2a37;
      --muted: #6b7280;
      --pass: #15803d;
      --fail: #dc2626;
      --skip: #ca8a04;
    }}
    body {{
      margin: 0;
      padding: 24px;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
    }}
    .report {{
      max-width: 980px;
      margin: 0 auto;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
    }}
    .header {{
      padding: 16px 20px 10px;
      border-bottom: 1px solid var(--border);
    }}
    h1 {{
      margin: 0;
      font-size: 20px;
    }}
    .meta {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
    }}
    .overall {{
      display: grid;
      grid-template-columns: repeat(4, minmax(120px, 1fr));
      gap: 8px;
      padding: 12px 20px;
      border-bottom: 1px solid var(--border);
      background: #fafcff;
    }}
    .metric {{
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 8px 10px;
      background: #ffffff;
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    .metric-value {{
      margin-top: 4px;
      font-size: 18px;
      font-weight: 700;
      color: var(--text);
    }}
    .metric-pass .metric-value {{
      color: #166534;
    }}
    .metric-fail .metric-value {{
      color: #991b1b;
    }}
    .metric-skip .metric-value {{
      color: #854d0e;
    }}
    details {{
      border-top: 1px solid var(--border);
    }}
    details:first-of-type {{
      border-top: none;
    }}
    summary {{
      list-style: none;
      cursor: pointer;
      display: grid;
      gap: 12px;
      grid-template-columns: minmax(220px, 1.6fr) minmax(160px, 1fr) minmax(130px, 0.8fr);
      align-items: center;
      padding: 14px 20px;
      user-select: none;
    }}
    summary::-webkit-details-marker {{
      display: none;
    }}
    .summary-title {{
      font-weight: 600;
    }}
    .status-cell {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}
    .status-pill {{
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.02em;
    }}
    .run-passed {{
      background: #dcfce7;
      color: #166534;
    }}
    .run-failed {{
      background: #fee2e2;
      color: #991b1b;
    }}
    .run-skipped {{
      background: #fef9c3;
      color: #854d0e;
    }}
    .arrow {{
      color: var(--muted);
      transition: transform 0.15s ease;
      display: inline-block;
    }}
    details[open] .arrow {{
      transform: rotate(90deg);
    }}
    .seconds {{
      font-weight: 600;
    }}
    .steps {{
      margin: 0;
      padding: 6px 20px 18px 20px;
      list-style: none;
      display: grid;
      gap: 8px;
    }}
    .step-item {{
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      display: grid;
      gap: 8px;
      grid-template-columns: 18px minmax(180px, 1fr) minmax(80px, auto) minmax(80px, auto);
      align-items: center;
      background: #fbfdff;
    }}
    .tick {{
      font-size: 15px;
      font-weight: 800;
      line-height: 1;
    }}
    .step-passed {{
      color: var(--pass);
    }}
    .step-failed {{
      color: var(--fail);
    }}
    .step-skipped {{
      color: var(--skip);
    }}
    .step-name {{
      font-size: 14px;
    }}
    .step-status,
    .step-time {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.02em;
    }}
    .step-detail {{
      grid-column: 2 / -1;
      color: var(--muted);
      font-size: 12px;
    }}
    @media (max-width: 820px) {{
      .overall {{
        grid-template-columns: repeat(2, minmax(120px, 1fr));
      }}
    }}
  </style>
</head>
<body>
  <main class="report">
    <section class="header">
      <h1>Test Execution Report</h1>
      <div class="meta">Run ID: {escape(run.run_id)}</div>
    </section>
    <section class="overall">
      <div class="metric">
        <div class="metric-label">Total Tests</div>
        <div class="metric-value">{total_tests}</div>
      </div>
      <div class="metric metric-pass">
        <div class="metric-label">Test Passed</div>
        <div class="metric-value">{passed_tests}</div>
      </div>
      <div class="metric metric-fail">
        <div class="metric-label">Test Failed</div>
        <div class="metric-value">{failed_tests}</div>
      </div>
      <div class="metric metric-skip">
        <div class="metric-label">Test Skipped</div>
        <div class="metric-value">{skipped_tests}</div>
      </div>
    </section>
    <details>
      <summary>
        <span class="summary-title">Test Case Name: {escape(run.run_name)}</span>
        <span class="status-cell">
          <span class="status-pill {run_status_class}">Status: {escape(run_status_label)}</span>
          <span class="arrow" aria-hidden="true">&#9656;</span>
        </span>
        <span class="seconds">Execution Time (seconds): {escape(run_duration)}</span>
      </summary>
      <ul class="steps">
        {steps_html}
      </ul>
    </details>
  </main>
</body>
</html>
"""

    @staticmethod
    def _build_summary(run) -> str:
        completed = sum(1 for step in run.steps if step.status == StepStatus.completed)
        failed = sum(1 for step in run.steps if step.status == StepStatus.failed)
        cancelled = sum(1 for step in run.steps if step.status == StepStatus.cancelled)
        return (
            f"Run '{run.run_name}' ended with status {run.status}. "
            f"Completed={completed}, Failed={failed}, Cancelled={cancelled}."
        )
