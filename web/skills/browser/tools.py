"""Browser skill — web search, page navigation, and multi-step site interaction."""

SKILL_ID = "browser"
ALWAYS_ON = False

# No DIRECT_INTENTS — browser is explicit opt-in only (/browse).
# Prevents false triggers from broad keywords like "website", "flight", etc.

TOOL_DEFS = [
    {
        "name": "browser_search",
        "description": "Search the web via Google and return top results. Use for general information lookup when no specific website is mentioned.",
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
        "description": "Perform a complex multi-step task in the browser. NEVER use for systems that have dedicated API tools: Jira (use jira_* tools), Teams (use teams_* tools), Email (use email_* tools), Slack (use slack_* tools), Confluence (use confluence_* tools). Use ONLY for public websites with no dedicated tool — e.g. booking flights, filling forms, comparing prices, extracting data from arbitrary web pages.",
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


async def _tool_browser_search(query: str) -> dict:
    from browser_agent import run_browser_task
    return await run_browser_task(
        task=f'Search Google for "{query}". Return the top 5 results with their titles, URLs, and a one-sentence summary of each.',
    )


async def _tool_browser_navigate(url: str, extract_content: str = "main text content") -> dict:
    from browser_agent import run_browser_task
    return await run_browser_task(
        task=f"Navigate to {url} and extract: {extract_content}",
        start_url=url,
    )


async def _tool_browser_task(task: str, start_url: str = "") -> dict:
    from browser_agent import run_browser_task
    return await run_browser_task(task=task, start_url=start_url)


TOOL_HANDLERS = {
    "browser_search": _tool_browser_search,
    "browser_navigate": _tool_browser_navigate,
    "browser_task": _tool_browser_task,
}
