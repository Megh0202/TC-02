from __future__ import annotations

import asyncio
import base64
import json
import io
import re
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.config import Settings

try:
    from PIL import Image, ImageChops
except ImportError:  # pragma: no cover - optional dependency in mock mode
    Image = None
    ImageChops = None

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - optional dependency in mock mode
    async_playwright = None

try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except ImportError:  # pragma: no cover - optional dependency in non-MCP mode
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None


def image_delta_ratio(baseline_bytes: bytes, current_bytes: bytes) -> float:
    if Image is None or ImageChops is None:
        raise RuntimeError("Pillow is required for image verification. Install with `pip install pillow`.")

    baseline_image = Image.open(io.BytesIO(baseline_bytes)).convert("RGB")
    current_image = Image.open(io.BytesIO(current_bytes)).convert("RGB")

    if baseline_image.size != current_image.size:
        raise ValueError(
            f"Image sizes differ. Baseline={baseline_image.size}, Current={current_image.size}."
        )

    diff = ImageChops.difference(baseline_image, current_image)
    changed_pixels = 0
    for pixel in diff.getdata():
        if isinstance(pixel, tuple):
            if any(channel != 0 for channel in pixel):
                changed_pixels += 1
        elif pixel != 0:
            changed_pixels += 1

    total_pixels = baseline_image.width * baseline_image.height
    if total_pixels == 0:
        return 0.0
    return changed_pixels / total_pixels


class BrowserMCPClient:
    """
    Mock browser adapter used as safe default for local development.
    """

    async def start_run(self, run_id: str) -> None:
        return

    async def close_run(self, run_id: str) -> None:
        return

    async def navigate(self, url: str) -> str:
        await asyncio.sleep(0.1)
        return f"Navigated to {url}"

    async def click(self, selector: str) -> str:
        await asyncio.sleep(0.1)
        return f"Clicked {selector}"

    async def type_text(self, selector: str, text: str, clear_first: bool = True) -> str:
        await asyncio.sleep(0.1)
        mode = "after clear" if clear_first else "append"
        return f"Typed into {selector} ({mode})"

    async def select(self, selector: str, value: str) -> str:
        await asyncio.sleep(0.1)
        return f"Selected {value} in {selector}"

    async def drag_and_drop(self, source_selector: str, target_selector: str) -> str:
        await asyncio.sleep(0.1)
        return f"Dragged {source_selector} to {target_selector}"

    async def scroll(self, target: str, selector: str | None, direction: str, amount: int) -> str:
        await asyncio.sleep(0.1)
        if target == "selector" and selector:
            return f"Scrolled {direction} {amount}px in {selector}"
        return f"Scrolled page {direction} {amount}px"

    async def wait_for(
        self,
        until: str,
        ms: int | None = None,
        selector: str | None = None,
        load_state: str | None = None,
    ) -> str:
        sleep_ms = ms if ms is not None else 700
        await asyncio.sleep(max(sleep_ms, 0) / 1000)

        if until == "selector_visible":
            return f"Waited for selector visible: {selector}"
        if until == "selector_hidden":
            return f"Waited for selector hidden: {selector}"
        if until == "load_state":
            return f"Waited for load state: {load_state}"
        return f"Waited {sleep_ms}ms"

    async def handle_popup(self, policy: str, selector: str | None = None) -> str:
        await asyncio.sleep(0.1)
        if selector:
            return f"Popup {selector} handled with policy {policy}"
        return f"Popup handled with policy {policy}"

    async def verify_text(self, selector: str, match: str, value: str) -> str:
        await asyncio.sleep(0.1)
        if match == "regex":
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"Invalid regex pattern: {exc}") from exc
        return f"Text verification passed ({match}) on {selector}"

    async def verify_image(
        self,
        selector: str | None = None,
        baseline_path: str | None = None,
        threshold: float = 0.05,
    ) -> str:
        await asyncio.sleep(0.1)
        target = selector or "page"
        baseline = baseline_path or "none"
        return f"Image verification passed on {target} (baseline={baseline}, threshold={threshold})"


@dataclass
class _PlaywrightRunContext:
    playwright: Any
    browser: Any
    context: Any
    page: Any
    dialog_policy: str = "dismiss"
    last_dialog_message: str | None = None


class PlaywrightBrowserMCPClient(BrowserMCPClient):
    """
    Real browser adapter powered by Playwright.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._runs: dict[str, _PlaywrightRunContext] = {}
        self._lock = asyncio.Lock()
        self._current_run_id: ContextVar[str | None] = ContextVar("browser_run_id", default=None)

    async def start_run(self, run_id: str) -> None:
        async with self._lock:
            existing = self._runs.get(run_id)
            if existing:
                self._current_run_id.set(run_id)
                return

            if async_playwright is None:
                raise RuntimeError(
                    "Playwright is not installed. Install with `pip install playwright` and "
                    "run `python -m playwright install chromium`."
                )

            playwright = await async_playwright().start()
            browser_type = getattr(playwright, self._settings.playwright_browser)
            browser = await browser_type.launch(
                headless=self._settings.playwright_headless,
                slow_mo=max(self._settings.playwright_slow_mo_ms, 0),
            )
            context = await browser.new_context()
            page = await context.new_page()
            page.set_default_timeout(self._settings.playwright_default_timeout_ms)

            run_context = _PlaywrightRunContext(
                playwright=playwright,
                browser=browser,
                context=context,
                page=page,
            )
            page.on("dialog", lambda dialog: asyncio.create_task(self._on_dialog(run_id, dialog)))
            self._runs[run_id] = run_context
            self._current_run_id.set(run_id)

    async def close_run(self, run_id: str) -> None:
        async with self._lock:
            context = self._runs.pop(run_id, None)

        if not context:
            return

        try:
            await context.context.close()
        except Exception:
            pass

        try:
            await context.browser.close()
        except Exception:
            pass

        try:
            await context.playwright.stop()
        except Exception:
            pass

        if self._current_run_id.get() == run_id:
            self._current_run_id.set(None)

    async def navigate(self, url: str) -> str:
        context = self._active_context()
        await context.page.goto(url, wait_until="domcontentloaded")
        return f"Navigated to {url}"

    async def click(self, selector: str) -> str:
        context = self._active_context()
        await context.page.locator(selector).first.click()
        return f"Clicked {selector}"

    async def type_text(self, selector: str, text: str, clear_first: bool = True) -> str:
        context = self._active_context()
        locator = context.page.locator(selector).first
        if clear_first:
            await locator.fill(text)
            mode = "after clear"
        else:
            await locator.click()
            await locator.type(text)
            mode = "append"
        return f"Typed into {selector} ({mode})"

    async def select(self, selector: str, value: str) -> str:
        context = self._active_context()
        selected_values = await context.page.locator(selector).first.select_option(value=value)
        if not selected_values:
            raise ValueError(f"No option with value '{value}' found in {selector}")
        return f"Selected {value} in {selector}"

    async def drag_and_drop(self, source_selector: str, target_selector: str) -> str:
        context = self._active_context()
        source = context.page.locator(source_selector).first
        target = context.page.locator(target_selector).first
        await source.drag_to(target)
        return f"Dragged {source_selector} to {target_selector}"

    async def scroll(self, target: str, selector: str | None, direction: str, amount: int) -> str:
        context = self._active_context()
        distance = abs(amount)
        signed = distance if direction == "down" else -distance

        if target == "selector":
            if not selector:
                raise ValueError("selector is required when target=selector")
            locator = context.page.locator(selector).first
            await locator.evaluate("(el, delta) => el.scrollBy(0, delta)", signed)
            return f"Scrolled {direction} {distance}px in {selector}"

        await context.page.mouse.wheel(0, signed)
        return f"Scrolled page {direction} {distance}px"

    async def wait_for(
        self,
        until: str,
        ms: int | None = None,
        selector: str | None = None,
        load_state: str | None = None,
    ) -> str:
        context = self._active_context()
        page = context.page

        if until == "timeout":
            wait_ms = max(ms if ms is not None else 700, 0)
            await page.wait_for_timeout(wait_ms)
            return f"Waited {wait_ms}ms"

        timeout_ms = max(ms if ms is not None else self._settings.playwright_default_timeout_ms, 0)

        if until == "selector_visible":
            if not selector:
                raise ValueError("selector is required when until=selector_visible")
            await page.wait_for_selector(selector, state="visible", timeout=timeout_ms)
            return f"Waited for selector visible: {selector}"

        if until == "selector_hidden":
            if not selector:
                raise ValueError("selector is required when until=selector_hidden")
            await page.wait_for_selector(selector, state="hidden", timeout=timeout_ms)
            return f"Waited for selector hidden: {selector}"

        if until == "load_state":
            state = load_state or "load"
            await page.wait_for_load_state(state=state, timeout=timeout_ms)
            return f"Waited for load state: {state}"

        raise ValueError(f"Unsupported wait condition: {until}")

    async def handle_popup(self, policy: str, selector: str | None = None) -> str:
        context = self._active_context()
        context.dialog_policy = policy

        if selector:
            try:
                await context.page.locator(selector).first.click(timeout=1200)
                return f"Popup {selector} handled with policy {policy}"
            except Exception as exc:
                error_text = str(exc).lower()
                if any(
                    marker in error_text
                    for marker in (
                        "timeout",
                        "waiting for",
                        "not visible",
                        "not attached",
                        "strict mode violation",
                        "resolved to 0 elements",
                        "locator.click",
                    )
                ):
                    return f"No popup matched {selector}; continued"
                raise

        return f"Popup policy set to {policy}"

    async def verify_text(self, selector: str, match: str, value: str) -> str:
        context = self._active_context()
        text = await context.page.locator(selector).first.text_content()
        actual = (text or "").strip()

        if match == "exact":
            is_match = actual == value
        elif match == "contains":
            is_match = value.lower() in actual.lower()
        elif match == "regex":
            try:
                is_match = bool(re.search(value, actual))
            except re.error as exc:
                raise ValueError(f"Invalid regex pattern: {exc}") from exc
        else:
            raise ValueError(f"Unsupported text match type: {match}")

        if not is_match:
            raise ValueError(f"Text verification failed on {selector}. Actual='{actual}', Expected({match})='{value}'")

        return f"Text verification passed ({match}) on {selector}"

    async def verify_image(
        self,
        selector: str | None = None,
        baseline_path: str | None = None,
        threshold: float = 0.05,
    ) -> str:
        context = self._active_context()
        if selector:
            image_bytes = await context.page.locator(selector).first.screenshot()
            target = selector
        else:
            image_bytes = await context.page.screenshot(full_page=True)
            target = "page"

        if not baseline_path:
            return f"Image captured for {target}; no baseline provided"

        baseline = Path(baseline_path)
        if not baseline.exists():
            baseline.parent.mkdir(parents=True, exist_ok=True)
            baseline.write_bytes(image_bytes)
            return f"Baseline created at {baseline}"

        delta = self._image_delta_ratio(baseline.read_bytes(), image_bytes)
        if delta > threshold:
            raise ValueError(
                f"Image verification failed on {target}. Difference ratio {delta:.4f} exceeds threshold {threshold:.4f}"
            )
        return (
            f"Image verification passed on {target} "
            f"(baseline={baseline}, threshold={threshold}, difference={delta:.4f})"
        )

    async def _on_dialog(self, run_id: str, dialog: Any) -> None:
        context = self._runs.get(run_id)
        if not context:
            try:
                await dialog.dismiss()
            except Exception:
                pass
            return

        context.last_dialog_message = dialog.message
        policy = context.dialog_policy

        try:
            if policy == "accept":
                await dialog.accept()
            elif policy in ("dismiss", "close", "ignore"):
                await dialog.dismiss()
            else:
                await dialog.dismiss()
        except Exception:
            pass

    def _active_context(self) -> _PlaywrightRunContext:
        run_id = self._current_run_id.get()
        if not run_id:
            raise RuntimeError("Browser run not initialized. Call start_run(run_id) before executing steps.")

        context = self._runs.get(run_id)
        if not context:
            raise RuntimeError(f"No browser session exists for run_id={run_id}")
        return context

    @staticmethod
    def _image_delta_ratio(baseline_bytes: bytes, current_bytes: bytes) -> float:
        return image_delta_ratio(baseline_bytes, current_bytes)


@dataclass
class _MCPPlaywrightRunContext:
    stdio_context: Any
    session_context: Any
    session: Any
    tool_names: set[str]
    dialog_policy: str = "dismiss"


class MCPPlaywrightBrowserMCPClient(BrowserMCPClient):
    """
    Browser adapter backed by Playwright MCP server (@playwright/mcp).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._runs: dict[str, _MCPPlaywrightRunContext] = {}
        self._lock = asyncio.Lock()
        self._current_run_id: ContextVar[str | None] = ContextVar("mcp_browser_run_id", default=None)

    async def start_run(self, run_id: str) -> None:
        async with self._lock:
            existing = self._runs.get(run_id)
            if existing:
                self._current_run_id.set(run_id)
                return

            if ClientSession is None or StdioServerParameters is None or stdio_client is None:
                raise RuntimeError(
                    "MCP SDK is not installed. Install backend dependencies including `mcp`."
                )

            server_args = [self._settings.browser_mcp_package]
            if self._settings.browser_mcp_command.lower().startswith("npx") and self._settings.browser_mcp_npx_yes:
                server_args.insert(0, "-y")

            parameters = StdioServerParameters(
                command=self._settings.browser_mcp_command,
                args=server_args,
            )

            stdio_context: Any | None = None
            session_context: Any | None = None
            try:
                stdio_context = stdio_client(parameters)
                read_stream, write_stream = await stdio_context.__aenter__()

                session_context = ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=max(self._settings.browser_mcp_read_timeout_seconds, 1)),
                )
                session = await session_context.__aenter__()
                await session.initialize()

                tools = await session.list_tools()
                context = _MCPPlaywrightRunContext(
                    stdio_context=stdio_context,
                    session_context=session_context,
                    session=session,
                    tool_names={tool.name for tool in tools.tools},
                )
                self._runs[run_id] = context
                self._current_run_id.set(run_id)
            except Exception:
                try:
                    if session_context is not None:
                        await session_context.__aexit__(None, None, None)
                except Exception:
                    pass
                try:
                    if stdio_context is not None:
                        await stdio_context.__aexit__(None, None, None)
                except Exception:
                    pass
                raise

    async def close_run(self, run_id: str) -> None:
        async with self._lock:
            context = self._runs.pop(run_id, None)

        if not context:
            return

        try:
            if "browser_close" in context.tool_names:
                await self._call_tool(context, "browser_close", {})
        except Exception:
            pass

        await self._close_context(context)

        if self._current_run_id.get() == run_id:
            self._current_run_id.set(None)

    async def navigate(self, url: str) -> str:
        context = self._active_context()
        await self._call_tool(context, "browser_navigate", {"url": url})
        return f"Navigated to {url}"

    async def click(self, selector: str) -> str:
        message = f"Clicked {selector}"
        code = (
            "async (page) => {"
            f"  await page.locator({json.dumps(selector)}).first().click();"
            f"  return {json.dumps(message)};"
            "}"
        )
        await self._run_code(code)
        return message

    async def type_text(self, selector: str, text: str, clear_first: bool = True) -> str:
        mode = "after clear" if clear_first else "append"
        message = f"Typed into {selector} ({mode})"
        if clear_first:
            code = (
                "async (page) => {"
                f"  await page.locator({json.dumps(selector)}).first().fill({json.dumps(text)});"
                f"  return {json.dumps(message)};"
                "}"
            )
        else:
            code = (
                "async (page) => {"
                f"  const locator = page.locator({json.dumps(selector)}).first();"
                "  await locator.click();"
                f"  await locator.type({json.dumps(text)});"
                f"  return {json.dumps(message)};"
                "}"
            )
        await self._run_code(code)
        return message

    async def select(self, selector: str, value: str) -> str:
        message = f"Selected {value} in {selector}"
        no_option_message = f"No option with value '{value}' found in {selector}"
        code = (
            "async (page) => {"
            f"  const selected = await page.locator({json.dumps(selector)}).first().selectOption({{ value: {json.dumps(value)} }});"
            "  if (!selected || selected.length === 0) {"
            f"    throw new Error({json.dumps(no_option_message)});"
            "  }"
            f"  return {json.dumps(message)};"
            "}"
        )
        await self._run_code(code)
        return message

    async def drag_and_drop(self, source_selector: str, target_selector: str) -> str:
        message = f"Dragged {source_selector} to {target_selector}"
        code = (
            "async (page) => {"
            f"  const source = page.locator({json.dumps(source_selector)}).first();"
            f"  const target = page.locator({json.dumps(target_selector)}).first();"
            "  await source.dragTo(target);"
            f"  return {json.dumps(message)};"
            "}"
        )
        await self._run_code(code)
        return message

    async def scroll(self, target: str, selector: str | None, direction: str, amount: int) -> str:
        distance = abs(amount)
        signed = distance if direction == "down" else -distance

        if target == "selector":
            if not selector:
                raise ValueError("selector is required when target=selector")

            message = f"Scrolled {direction} {distance}px in {selector}"
            code = (
                "async (page) => {"
                f"  const locator = page.locator({json.dumps(selector)}).first();"
                f"  await locator.evaluate((el, delta) => el.scrollBy(0, delta), {signed});"
                f"  return {json.dumps(message)};"
                "}"
            )
            await self._run_code(code)
            return message

        message = f"Scrolled page {direction} {distance}px"
        code = (
            "async (page) => {"
            f"  await page.mouse.wheel(0, {signed});"
            f"  return {json.dumps(message)};"
            "}"
        )
        await self._run_code(code)
        return message

    async def wait_for(
        self,
        until: str,
        ms: int | None = None,
        selector: str | None = None,
        load_state: str | None = None,
    ) -> str:
        context = self._active_context()

        if until == "timeout":
            wait_ms = max(ms if ms is not None else 700, 0)
            await self._call_tool(context, "browser_wait_for", {"time": wait_ms / 1000})
            return f"Waited {wait_ms}ms"

        timeout_ms = max(ms if ms is not None else self._settings.playwright_default_timeout_ms, 0)

        if until == "selector_visible":
            if not selector:
                raise ValueError("selector is required when until=selector_visible")
            code = (
                "async (page) => {"
                f"  await page.locator({json.dumps(selector)}).first().waitFor({{ state: 'visible', timeout: {timeout_ms} }});"
                f"  return {json.dumps(f'Waited for selector visible: {selector}')};"
                "}"
            )
            await self._run_code(code)
            return f"Waited for selector visible: {selector}"

        if until == "selector_hidden":
            if not selector:
                raise ValueError("selector is required when until=selector_hidden")
            code = (
                "async (page) => {"
                f"  await page.locator({json.dumps(selector)}).first().waitFor({{ state: 'hidden', timeout: {timeout_ms} }});"
                f"  return {json.dumps(f'Waited for selector hidden: {selector}')};"
                "}"
            )
            await self._run_code(code)
            return f"Waited for selector hidden: {selector}"

        if until == "load_state":
            state = load_state or "load"
            code = (
                "async (page) => {"
                f"  await page.waitForLoadState({json.dumps(state)}, {{ timeout: {timeout_ms} }});"
                f"  return {json.dumps(f'Waited for load state: {state}')};"
                "}"
            )
            await self._run_code(code)
            return f"Waited for load state: {state}"

        raise ValueError(f"Unsupported wait condition: {until}")

    async def handle_popup(self, policy: str, selector: str | None = None) -> str:
        context = self._active_context()
        context.dialog_policy = policy

        if selector:
            no_popup_message = f"No popup matched {selector}; continued"
            handled_message = f"Popup {selector} handled with policy {policy}"
            code = (
                "async (page) => {"
                f"  const selector = {json.dumps(selector)};"
                "  const count = await page.locator(selector).count();"
                "  if (!count) {"
                f"    return {json.dumps(no_popup_message)};"
                "  }"
                "  try {"
                "    await page.locator(selector).first().click({ timeout: 1200 });"
                f"    return {json.dumps(handled_message)};"
                "  } catch (error) {"
                f"    return {json.dumps(no_popup_message)};"
                "  }"
                "}"
            )
            return await self._run_code(code)

        if policy == "ignore":
            return "Popup policy set to ignore"

        accept = policy == "accept"
        try:
            await self._call_tool(context, "browser_handle_dialog", {"accept": accept})
            return f"Popup handled with policy {policy}"
        except Exception:
            return f"Popup policy set to {policy}"

    async def verify_text(self, selector: str, match: str, value: str) -> str:
        code = (
            "async (page) => {"
            f"  const selector = {json.dumps(selector)};"
            f"  const matchType = {json.dumps(match)};"
            f"  const expected = {json.dumps(value)};"
            "  const actual = ((await page.locator(selector).first().textContent()) || '').trim();"
            "  let isMatch = false;"
            "  if (matchType === 'exact') {"
            "    isMatch = actual === expected;"
            "  } else if (matchType === 'contains') {"
            "    isMatch = actual.includes(expected);"
            "  } else if (matchType === 'regex') {"
            "    let pattern;"
            "    try { pattern = new RegExp(expected); }"
            "    catch (error) { throw new Error(`Invalid regex pattern: ${error.message}`); }"
            "    isMatch = pattern.test(actual);"
            "  } else {"
            "    throw new Error(`Unsupported text match type: ${matchType}`);"
            "  }"
            "  if (!isMatch) {"
            "    throw new Error(`Text verification failed on ${selector}. Actual='${actual}', Expected(${matchType})='${expected}'`);"
            "  }"
            "  return `Text verification passed (${matchType}) on ${selector}`;"
            "}"
        )
        return await self._run_code(code)

    async def verify_image(
        self,
        selector: str | None = None,
        baseline_path: str | None = None,
        threshold: float = 0.05,
    ) -> str:
        if selector:
            target = selector
            code = (
                "async (page) => {"
                f"  const bytes = await page.locator({json.dumps(selector)}).first().screenshot();"
                "  return bytes.toString('base64');"
                "}"
            )
        else:
            target = "page"
            code = (
                "async (page) => {"
                "  const bytes = await page.screenshot({ fullPage: true });"
                "  return bytes.toString('base64');"
                "}"
            )

        encoded = await self._run_code(code)
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError("Unable to decode image data returned from Browser MCP") from exc

        if not baseline_path:
            return f"Image captured for {target}; no baseline provided"

        baseline = Path(baseline_path)
        if not baseline.exists():
            baseline.parent.mkdir(parents=True, exist_ok=True)
            baseline.write_bytes(image_bytes)
            return f"Baseline created at {baseline}"

        delta = image_delta_ratio(baseline.read_bytes(), image_bytes)
        if delta > threshold:
            raise ValueError(
                f"Image verification failed on {target}. Difference ratio {delta:.4f} exceeds threshold {threshold:.4f}"
            )
        return (
            f"Image verification passed on {target} "
            f"(baseline={baseline}, threshold={threshold}, difference={delta:.4f})"
        )

    def _active_context(self) -> _MCPPlaywrightRunContext:
        run_id = self._current_run_id.get()
        if not run_id:
            raise RuntimeError("Browser run not initialized. Call start_run(run_id) before executing steps.")

        context = self._runs.get(run_id)
        if not context:
            raise RuntimeError(f"No browser MCP session exists for run_id={run_id}")
        return context

    async def _run_code(self, code: str) -> str:
        context = self._active_context()
        result = await self._call_tool(context, "browser_run_code", {"code": code})
        text = self._result_text(result)
        if not text:
            return ""

        result_block = self._extract_result_block(text)
        if not result_block:
            return text

        try:
            parsed = json.loads(result_block)
        except Exception:
            return result_block

        if isinstance(parsed, str):
            return parsed
        if isinstance(parsed, bool):
            return "true" if parsed else "false"
        return str(parsed)

    async def _call_tool(self, context: _MCPPlaywrightRunContext, tool_name: str, arguments: dict[str, Any]) -> Any:
        if tool_name not in context.tool_names:
            raise RuntimeError(f"Browser MCP server does not expose tool '{tool_name}'")

        result = await context.session.call_tool(tool_name, arguments)
        if getattr(result, "isError", False):
            message = self._result_text(result).strip() or f"Unknown Browser MCP error in {tool_name}"
            raise ValueError(message)
        return result

    async def _close_context(self, context: _MCPPlaywrightRunContext) -> None:
        try:
            await context.session_context.__aexit__(None, None, None)
        except Exception:
            pass

        try:
            await context.stdio_context.__aexit__(None, None, None)
        except Exception:
            pass

    @staticmethod
    def _result_text(result: Any) -> str:
        chunks: list[str] = []
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                chunks.append(text)
                continue
            if isinstance(item, dict):
                text_value = item.get("text")
                if isinstance(text_value, str):
                    chunks.append(text_value)
        return "\n".join(chunks).strip()

    @staticmethod
    def _extract_result_block(text: str) -> str:
        match = re.search(r"### Result\s*(.*?)(?:\n### |\Z)", text, flags=re.DOTALL)
        if not match:
            return text.strip()
        return match.group(1).strip()


def build_browser_client(settings: Settings) -> BrowserMCPClient:
    if settings.browser_mode == "mcp":
        return MCPPlaywrightBrowserMCPClient(settings)
    if settings.browser_mode == "playwright":
        return PlaywrightBrowserMCPClient(settings)
    return BrowserMCPClient()
