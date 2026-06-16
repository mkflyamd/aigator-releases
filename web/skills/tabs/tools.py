"""Tabs skill — expose pinned-item queries by tab name or current-tab context."""
from __future__ import annotations

from skills.context.state import get_pins
from skills.context import tabs as _tabs_registry

SKILL_ID = "tabs"
ALWAYS_ON = True  # cheap metadata lookup; always available to the LLM


TOOL_DEFS = [
    {
        "name": "get_tab_pins",
        "description": (
            "Return the pinned items (Confluence pages, Teams chats, OneDrive files, emails, "
            "Jira tickets, OneNote pages, etc.) for a tab. Defaults to the current tab — "
            "only pass tab_name or tab_context_id for cross-tab queries. Returns metadata "
            "only (no content fetch); follow up with the appropriate read tool if you need "
            "the body of a pinned item."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tab_name": {
                    "type": "string",
                    "description": "Display name of the tab to query (e.g. \"Fireworks\"). Case-insensitive exact match. Use this for cross-tab queries.",
                },
                "tab_context_id": {
                    "type": "string",
                    "description": "Stable context_id of the tab. Prefer this when known — names can be renamed.",
                },
                "type": {
                    "type": "string",
                    "description": "Optional filter by pin source (e.g. \"teams_chat\", \"confluence_page\", \"onedrive_file\", \"email\", \"jira\", \"onenote_page\", \"slack_thread\"). Omit to return all pins.",
                },
            },
            "required": [],
        },
    },
]


TOOL_STATUS = {
    "get_tab_pins": "📌 Looking up pinned items...",
}


def _tool_get_tab_pins(
    tab_name: str | None = None,
    tab_context_id: str | None = None,
    type: str | None = None,
    _context_id: str | None = None,
) -> dict:
    # Resolve which tab to query. Priority: explicit id > name > current tab.
    resolved_id: str | None = None
    resolved_name: str | None = None

    if tab_context_id:
        resolved_id = tab_context_id
        resolved_name = _tabs_registry.get_name(tab_context_id)
    elif tab_name:
        resolved_id = _tabs_registry.resolve_name(tab_name)
        if resolved_id is None:
            available = [t["name"] for t in _tabs_registry.list_tabs() if t["name"]]
            return {
                "error": f"Tab \"{tab_name}\" not found.",
                "available_tabs": available,
                "_user_message": f"No tab named \"{tab_name}\". Available: {', '.join(available) if available else '(none)'}.",
            }
        resolved_name = tab_name
    else:
        # Default to current tab
        resolved_id = _context_id or "default"
        resolved_name = _tabs_registry.get_name(resolved_id)

    pins = get_pins(resolved_id)

    # Optional type filter (matches pin source field)
    if type:
        target = type.strip().lower()
        pins = [p for p in pins if str(p.get("source", "")).lower() == target]

    # Shape response with status field (resource verification deferred; default "ok")
    out_pins = []
    for p in pins:
        out_pins.append({
            "type": p.get("source"),
            "id": p.get("id"),
            "label": p.get("label"),
            "meta": p.get("meta", {}),
            "status": "ok",
        })

    return {
        "tab_context_id": resolved_id,
        "tab_name": resolved_name,
        "pin_count": len(out_pins),
        "pins": out_pins,
        "_user_message": (
            f"{len(out_pins)} pin{'s' if len(out_pins) != 1 else ''} in "
            f"\"{resolved_name or resolved_id}\""
            + (f" (filtered to type={type})" if type else "")
        ),
    }


TOOL_HANDLERS = {
    "get_tab_pins": _tool_get_tab_pins,
}
