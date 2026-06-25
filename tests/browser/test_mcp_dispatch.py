"""Tests for MCP-based browser dispatch (issue #113).

Architecture: browser tools should route through any active MCP connection that
exposes browser capabilities, falling back to browser_agent.py only when no
such MCP is registered. This mirrors how Claude Code handles MCP tools — one
unified dispatch table, MCP tools are first-class, no hardcoded native path.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helper: build a fake shared.TOOL_DISPATCH with MCP browser tools ──────────

def _make_dispatch_with_mcp_browser(tool_names):
    """Return a TOOL_DISPATCH dict simulating registered MCP browser tools."""
    dispatch = {}
    for name in tool_names:
        dispatch[name] = AsyncMock(return_value={"result": f"mcp:{name}"})
    return dispatch


# ── 1. Capability detection ────────────────────────────────────────────────────

class TestBrowserCapabilityDetection:
    """_find_mcp_browser_tools() inspects shared.TOOL_DISPATCH for browser-capable tools."""

    def test_returns_empty_when_no_mcp_registered(self):
        """With no MCP connections, capability check returns empty dict."""
        from skills.browser.tools import _find_mcp_browser_tools
        import shared
        original = dict(shared.TOOL_DISPATCH)
        try:
            shared.TOOL_DISPATCH.clear()
            result = _find_mcp_browser_tools()
            assert result == {}
        finally:
            shared.TOOL_DISPATCH.update(original)

    def test_detects_navigate_page_as_browser_capable(self):
        """navigate_page is a canonical chrome-devtools-mcp browser tool."""
        from skills.browser.tools import _find_mcp_browser_tools
        import shared
        original = dict(shared.TOOL_DISPATCH)
        try:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH.update(
                _make_dispatch_with_mcp_browser(["mcp-chrome-devtools__navigate_page"])
            )
            result = _find_mcp_browser_tools()
            assert len(result) > 0
        finally:
            shared.TOOL_DISPATCH.update(original)
            for k in list(shared.TOOL_DISPATCH):
                if k not in original:
                    del shared.TOOL_DISPATCH[k]

    def test_detects_take_screenshot_as_browser_capable(self):
        """take_screenshot is a canonical chrome-devtools-mcp browser tool."""
        from skills.browser.tools import _find_mcp_browser_tools
        import shared
        original = dict(shared.TOOL_DISPATCH)
        try:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH.update(
                _make_dispatch_with_mcp_browser(["mcp-chrome-devtools__take_screenshot"])
            )
            result = _find_mcp_browser_tools()
            assert len(result) > 0
        finally:
            shared.TOOL_DISPATCH.update(original)
            for k in list(shared.TOOL_DISPATCH):
                if k not in original:
                    del shared.TOOL_DISPATCH[k]

    def test_detects_any_mcp_with_navigate_or_screenshot(self):
        """Any MCP server (not just chrome-devtools) providing browser tools is detected."""
        from skills.browser.tools import _find_mcp_browser_tools
        import shared
        original = dict(shared.TOOL_DISPATCH)
        try:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH.update(
                _make_dispatch_with_mcp_browser([
                    "mcp-playwright__navigate_page",
                    "mcp-playwright__take_screenshot",
                ])
            )
            result = _find_mcp_browser_tools()
            assert len(result) > 0
        finally:
            shared.TOOL_DISPATCH.update(original)
            for k in list(shared.TOOL_DISPATCH):
                if k not in original:
                    del shared.TOOL_DISPATCH[k]

    def test_ignores_non_browser_mcp_tools(self):
        """Jira/Teams MCP tools do not count as browser capability."""
        from skills.browser.tools import _find_mcp_browser_tools
        import shared
        original = dict(shared.TOOL_DISPATCH)
        try:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH.update(
                _make_dispatch_with_mcp_browser([
                    "mcp-jira__search_issues",
                    "mcp-teams__send_message",
                ])
            )
            result = _find_mcp_browser_tools()
            assert result == {}
        finally:
            shared.TOOL_DISPATCH.update(original)
            for k in list(shared.TOOL_DISPATCH):
                if k not in original:
                    del shared.TOOL_DISPATCH[k]


# ── 2. browser_search routes through MCP when available ───────────────────────

class TestBrowserSearchMCPDispatch:
    """_tool_browser_search routes through MCP when browser tools are registered."""

    @pytest.mark.asyncio
    async def test_routes_through_mcp_when_available(self):
        """When an MCP provides navigate/screenshot tools, browser_search uses MCP — not browser_agent."""
        from skills.browser.tools import _tool_browser_search
        import shared

        mcp_handler = AsyncMock(return_value={"result": "mcp search result"})
        original = dict(shared.TOOL_DISPATCH)
        try:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH["mcp-chrome-devtools__navigate_page"] = mcp_handler
            shared.TOOL_DISPATCH["mcp-chrome-devtools__take_screenshot"] = AsyncMock(
                return_value={"result": "screenshot"}
            )

            with patch("browser_agent.run_browser_task") as mock_native:
                result = await _tool_browser_search("test query")
                mock_native.assert_not_called()
        finally:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH.update(original)

    @pytest.mark.asyncio
    async def test_falls_back_to_browser_agent_when_no_mcp(self):
        """With no MCP browser tools, browser_search falls back to browser_agent."""
        from skills.browser.tools import _tool_browser_search
        import shared

        original = dict(shared.TOOL_DISPATCH)
        try:
            shared.TOOL_DISPATCH.clear()
            # Only non-browser MCP tools present
            shared.TOOL_DISPATCH["mcp-jira__search_issues"] = AsyncMock()

            with patch("browser_agent.run_browser_task", new_callable=AsyncMock) as mock_native:
                mock_native.return_value = {"result": "native result"}
                result = await _tool_browser_search("test query")
                mock_native.assert_called_once()
        finally:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH.update(original)


# ── 3. browser_navigate routes through MCP when available ─────────────────────

class TestBrowserNavigateMCPDispatch:
    """_tool_browser_navigate routes through MCP when browser tools are registered."""

    @pytest.mark.asyncio
    async def test_routes_through_mcp_when_available(self):
        """When an MCP provides browser tools, browser_navigate uses MCP."""
        from skills.browser.tools import _tool_browser_navigate
        import shared

        original = dict(shared.TOOL_DISPATCH)
        try:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH["mcp-chrome-devtools__navigate_page"] = AsyncMock(
                return_value={"result": "navigated"}
            )
            shared.TOOL_DISPATCH["mcp-chrome-devtools__take_screenshot"] = AsyncMock(
                return_value={"result": "screenshot"}
            )

            with patch("browser_agent.run_browser_task") as mock_native:
                result = await _tool_browser_navigate("https://example.com")
                mock_native.assert_not_called()
        finally:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH.update(original)

    @pytest.mark.asyncio
    async def test_falls_back_to_browser_agent_when_no_mcp(self):
        """With no MCP browser tools, browser_navigate falls back to browser_agent."""
        from skills.browser.tools import _tool_browser_navigate
        import shared

        original = dict(shared.TOOL_DISPATCH)
        try:
            shared.TOOL_DISPATCH.clear()

            with patch("browser_agent.run_browser_task", new_callable=AsyncMock) as mock_native:
                mock_native.return_value = {"result": "native"}
                await _tool_browser_navigate("https://example.com")
                mock_native.assert_called_once()
        finally:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH.update(original)


# ── 4. browser_task routes through MCP when available ─────────────────────────

class TestBrowserTaskMCPDispatch:
    """_tool_browser_task routes through MCP when browser tools are registered."""

    @pytest.mark.asyncio
    async def test_routes_through_mcp_when_available(self):
        """When an MCP provides browser tools, browser_task uses MCP."""
        from skills.browser.tools import _tool_browser_task
        import shared

        original = dict(shared.TOOL_DISPATCH)
        try:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH["mcp-chrome-devtools__navigate_page"] = AsyncMock(
                return_value={"result": "navigated"}
            )
            shared.TOOL_DISPATCH["mcp-chrome-devtools__take_screenshot"] = AsyncMock(
                return_value={"result": "screenshot"}
            )

            with patch("browser_agent.run_browser_task") as mock_native:
                await _tool_browser_task("do something on the web")
                mock_native.assert_not_called()
        finally:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH.update(original)

    @pytest.mark.asyncio
    async def test_falls_back_to_browser_agent_when_no_mcp(self):
        """With no MCP browser tools, browser_task falls back to browser_agent."""
        from skills.browser.tools import _tool_browser_task
        import shared

        original = dict(shared.TOOL_DISPATCH)
        try:
            shared.TOOL_DISPATCH.clear()

            with patch("browser_agent.run_browser_task", new_callable=AsyncMock) as mock_native:
                mock_native.return_value = {"result": "native"}
                await _tool_browser_task("do something")
                mock_native.assert_called_once()
        finally:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH.update(original)


# ── 5. Generic: any MCP server with browser-like tools works ──────────────────

class TestGenericMCPBrowserServer:
    """The dispatch is generic — not hardcoded to chrome-devtools-mcp."""

    @pytest.mark.asyncio
    async def test_playwright_mcp_also_routed(self):
        """A hypothetical mcp-playwright server providing navigate_page is also used."""
        from skills.browser.tools import _tool_browser_task
        import shared

        original = dict(shared.TOOL_DISPATCH)
        try:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH["mcp-playwright__navigate_page"] = AsyncMock(
                return_value={"result": "playwright-navigated"}
            )
            shared.TOOL_DISPATCH["mcp-playwright__take_screenshot"] = AsyncMock(
                return_value={"result": "playwright-screenshot"}
            )

            with patch("browser_agent.run_browser_task") as mock_native:
                await _tool_browser_task("some browser task")
                mock_native.assert_not_called()
        finally:
            shared.TOOL_DISPATCH.clear()
            shared.TOOL_DISPATCH.update(original)
