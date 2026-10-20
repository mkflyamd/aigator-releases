import asyncio

import shared
from skills.browser import tools as browser_tools


def _with_dispatch(monkeypatch, entries):
    monkeypatch.setattr(shared, "TOOL_DISPATCH", dict(entries))


def test_desktop_mcp_with_click_only_is_not_a_browser(monkeypatch):
    _with_dispatch(monkeypatch, {"mcp-open-computer-use__click": lambda **kw: {"result": "ok"}})
    assert browser_tools._find_mcp_browser_tools() == {}


def test_mcp_with_navigate_page_is_a_browser(monkeypatch):
    _with_dispatch(
        monkeypatch,
        {
            "mcp-cdp__navigate_page": lambda **kw: {"result": "navigated"},
            "mcp-cdp__take_snapshot": lambda **kw: {"result": "page text"},
        },
    )
    assert len(browser_tools._find_mcp_browser_tools()) == 2


def test_run_via_mcp_returns_page_content(monkeypatch):
    tools = {
        "mcp-cdp__navigate_page": lambda url: {"result": "navigated"},
        "mcp-cdp__take_snapshot": lambda: {"result": "page text"},
    }
    out = asyncio.run(browser_tools._run_via_mcp(tools, "task", start_url="https://example.com"))
    assert out == {"result": "navigated\npage text"}


def test_run_via_mcp_surfaces_errors_instead_of_echoing_the_task():
    tools = {
        "mcp-cdp__navigate_page": lambda url: {"error": "MCP call failed: boom"},
        "mcp-cdp__take_snapshot": lambda: {"error": "no page"},
    }
    out = asyncio.run(browser_tools._run_via_mcp(tools, "Navigate to X", start_url="https://example.com"))
    assert "result" not in out
    assert "boom" in out["error"]
    assert "Navigate to X" not in out["error"]


def test_safe_reset_session_does_not_kill_chrome_when_told_not_to(monkeypatch):
    import browser_agent

    killed = []
    monkeypatch.setattr(browser_agent, "_kill_orphaned_chrome", lambda: killed.append(1))

    class Broken:
        async def reset(self):
            raise RuntimeError("socket closed")

    asyncio.run(browser_agent._safe_reset_session(Broken(), "stale", kill_on_failure=False))
    assert killed == []
    asyncio.run(browser_agent._safe_reset_session(Broken(), "other"))
    assert killed == [1]
