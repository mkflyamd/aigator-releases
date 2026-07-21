"""Browser skill — web search, page navigation, and multi-step site interaction."""

SKILL_ID = "browser"
ALWAYS_ON = False

# No DIRECT_INTENTS — browser is explicit opt-in only (/browse).
# Prevents false triggers from broad keywords like "website", "flight", etc.

TOOL_DEFS = [
    {
        "name": "browser_search",
        "description": "Search the web via Google and return top results with titles, URLs, and summaries. Use for general information lookup, recent news, or when no specific URL is provided. Also use as a fallback when fetch_webpage fails with 'suggest_search' (bot-block or 403). Do NOT use when you already have a specific URL — use fetch_webpage or browser_navigate instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "browser_navigate",
        "description": "Navigate to a specific URL and extract the page content. Use ONLY for public websites with no dedicated tool. NEVER use for systems that have their own API tools: Jira (use jira_* tools), Teams (use teams_* tools), Email (use email_* tools), Slack (use slack_* tools), Confluence (use confluence_* tools). If an API tool exists for the domain, always use it instead of the browser.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL to navigate to (e.g., https://www.priceline.com)"},
                "extract_content": {"type": "string", "description": "What to extract from the page (e.g., 'main article text', 'product prices', 'all links')", "default": "main text content"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_task",
        "description": "Perform a complex multi-step task in the browser requiring navigation, clicks, form filling, or data extraction across multiple pages. Use for public websites with no dedicated API tool — e.g. booking flights, filling forms, comparing prices. NEVER use for systems with dedicated tools: Jira, Teams, Email, Slack, Confluence. Prefer browser_navigate for simple single-page reads; use browser_task only when multiple interactions are required.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Detailed natural language description of what to do in the browser. Be specific about the site, what to search for, what data to extract."},
                "start_url": {"type": "string", "description": "Starting URL (optional — agent can navigate on its own)", "default": ""},
            },
            "required": ["task"],
        },
    },
]

TOOL_STATUS = {
    "browser_search": "\U0001F310 Searching the web...",
    "browser_navigate": "\U0001F310 Opening page...",
    "browser_task": "\U0001F310 Working in browser...",
}

# Tool names (unnamespaced) that indicate a registered MCP connection has
# browser capabilities. Generic by design — matches chrome-devtools-mcp,
# playwright-mcp, puppeteer-mcp, or any future browser MCP server.
_BROWSER_CAPABILITY_TOOLS = {
    "navigate_page",
    "take_screenshot",
    "click",
    "fill",
    "evaluate_script",
    "take_snapshot",
}


def _find_mcp_browser_tools() -> dict:
    """Return {namespaced_tool_name: handler} for any MCP browser tools in TOOL_DISPATCH.

    Scans shared.TOOL_DISPATCH for entries whose unnamespaced name (the part
    after '__') matches a known browser capability. Returns empty dict when no
    browser-capable MCP is registered — callers fall back to browser_agent.py.
    """
    import shared
    result = {}
    for namespaced, handler in shared.TOOL_DISPATCH.items():
        # MCP tools are namespaced as "<connection-id>__<tool-name>"
        if "__" not in namespaced:
            continue
        _, tool_name = namespaced.split("__", 1)
        if tool_name in _BROWSER_CAPABILITY_TOOLS:
            result[namespaced] = handler
    return result


async def _run_via_mcp(mcp_tools: dict, task: str, start_url: str = "") -> dict:
    """Execute a browser task using registered MCP browser tools.

    Finds navigate_page and take_snapshot/take_screenshot in mcp_tools and
    calls them to accomplish the task, returning extracted content.
    """
    import asyncio

    # Prefer navigate_page for navigation, take_snapshot for content extraction
    navigate_handler = next(
        (h for name, h in mcp_tools.items() if name.endswith("__navigate_page")), None
    )
    snapshot_handler = next(
        (h for name, h in mcp_tools.items()
         if name.endswith("__take_snapshot") or name.endswith("__take_screenshot")),
        None
    )

    results = []

    if start_url and navigate_handler:
        nav_result = navigate_handler(url=start_url)
        if asyncio.iscoroutine(nav_result):
            nav_result = await nav_result
        if isinstance(nav_result, dict) and nav_result.get("result"):
            results.append(str(nav_result["result"]))

    if snapshot_handler:
        snap_result = snapshot_handler()
        if asyncio.iscoroutine(snap_result):
            snap_result = await snap_result
        if isinstance(snap_result, dict) and snap_result.get("result"):
            results.append(str(snap_result["result"]))

    content = "\n".join(results) if results else f"Task: {task}"
    return {"result": content}


async def _tool_browser_search(query: str) -> dict:
    mcp_tools = _find_mcp_browser_tools()
    if mcp_tools:
        return await _run_via_mcp(
            mcp_tools,
            task=f'Search for "{query}" and return the top results with titles, URLs, and summaries.',
        )
    from browser_agent import run_browser_task
    return await run_browser_task(
        task=f'Search Google for "{query}". Return the top 5 results with their titles, URLs, and a one-sentence summary of each.',
    )


async def _tool_browser_navigate(url: str, extract_content: str = "main text content") -> dict:
    mcp_tools = _find_mcp_browser_tools()
    if mcp_tools:
        return await _run_via_mcp(
            mcp_tools,
            task=f"Navigate to {url} and extract: {extract_content}",
            start_url=url,
        )
    from browser_agent import run_browser_task
    return await run_browser_task(
        task=f"Navigate to {url} and extract: {extract_content}",
        start_url=url,
    )


async def _tool_browser_task(task: str, start_url: str = "") -> dict:
    mcp_tools = _find_mcp_browser_tools()
    if mcp_tools:
        return await _run_via_mcp(mcp_tools, task=task, start_url=start_url)
    from browser_agent import run_browser_task
    return await run_browser_task(task=task, start_url=start_url)


TOOL_HANDLERS = {
    "browser_search": _tool_browser_search,
    "browser_navigate": _tool_browser_navigate,
    "browser_task": _tool_browser_task,
}
