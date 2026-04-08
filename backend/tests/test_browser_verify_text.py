from __future__ import annotations

import asyncio

from app.mcp.browser_client import PlaywrightBrowserMCPClient


class _FakeLocator:
    def __init__(self, details: dict[str, str]) -> None:
        self._details = details

    @property
    def first(self) -> "_FakeLocator":
        return self

    async def text_content(self) -> str:
        return self._details.get("text", "")

    async def inner_text(self) -> str:
        return self._details.get("inner", "")

    async def count(self) -> int:
        return 1

    def locator(self, selector: str) -> "_FakeLocator":
        return _FakeLocator({})

    async def evaluate(self, _script: str) -> dict[str, str]:
        return self._details


class _FakePage:
    def __init__(self, details: dict[str, str]) -> None:
        self._details = details

    def locator(self, _selector: str) -> _FakeLocator:
        return _FakeLocator(self._details)


class _FakeContext:
    def __init__(self, details: dict[str, str]) -> None:
        self.page = _FakePage(details)


def test_verify_text_reads_field_values() -> None:
    client = PlaywrightBrowserMCPClient.__new__(PlaywrightBrowserMCPClient)
    client._active_context = lambda: _FakeContext(  # type: ignore[attr-defined]
        {
            "fieldValue": "9876543210",
            "text": "",
            "inner": "",
            "aria": "",
            "name": "",
            "placeholder": "",
        }
    )

    result = asyncio.run(
        client.verify_text("input[name='phone']", "contains", "9876543210")
    )

    assert result == "Text verification passed (contains) on input[name='phone']"


def test_verify_text_reads_label_associated_control_value() -> None:
    client = PlaywrightBrowserMCPClient.__new__(PlaywrightBrowserMCPClient)
    client._active_context = lambda: _FakeContext(  # type: ignore[attr-defined]
        {
            "fieldValue": "Test User",
            "text": "Phone number",
            "inner": "Phone number",
            "aria": "",
            "name": "",
            "placeholder": "",
        }
    )

    result = asyncio.run(
        client.verify_text("label:has-text('Phone number')", "contains", "Test User")
    )

    assert result == "Text verification passed (contains) on label:has-text('Phone number')"
