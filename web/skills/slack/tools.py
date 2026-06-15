"""Slack skill — backed by the official Slack MCP server (https://mcp.slack.com/mcp).

Tool schemas are pulled directly from the MCP server to avoid type mismatches.
Write operations go through the draft approval flow (human-in-the-loop).
"""

import json
from pathlib import Path
from .mcp_client import get_slack_mcp, _UNREACHABLE_MSG, is_slack_authenticated


def _mcp_call(fn, *args, **kwargs) -> dict:
    """Wrap every MCP tool call so network errors return the friendly unreachable message."""
    try:
        result = fn(*args, **kwargs)
        r = result.get("result", "") if isinstance(result, dict) else ""
        if isinstance(r, str):
            r_lower = r.lower()
            if any(kw in r_lower for kw in ("invalid_auth", "token_expired", "not_authed", "invalid_token")):
                return {"result": _UNREACHABLE_MSG}
        return result
    except Exception as e:
        print(f"[SLACK MCP] Error: {e}")
        return {"result": _UNREACHABLE_MSG}


SKILL_ID = "slack"
ALWAYS_ON = False

# Tools that send messages — must go through draft approval (human-in-the-loop)
_WRITE_TOOLS = {"slack_send_message", "slack_schedule_message"}

# ── Tool definitions — pulled from official Slack MCP, cached to disk ─────────

_SCHEMA_CACHE = Path.home() / ".config" / "slack-mcp" / "tool_schemas.json"


def _fetch_and_cache_schemas() -> list[dict]:
    """Pull tool schemas from MCP server, cache to disk."""
    try:
        mcp = get_slack_mcp()
        mcp_tools = mcp.list_tools()
        defs = []
        for t in mcp_tools:
            defs.append({
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("inputSchema", {"type": "object", "properties": {}}),
            })
        # Cache to disk
        _SCHEMA_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _SCHEMA_CACHE.write_text(json.dumps(defs, indent=2))
        print(f"[SLACK MCP] Loaded {len(defs)} tool schemas from MCP server")
        return defs
    except Exception as e:
        print(f"[SLACK MCP] Could not fetch schemas from MCP: {e}")
        return []


def _load_cached_schemas() -> list[dict]:
    """Load schemas from disk cache."""
    if _SCHEMA_CACHE.exists():
        try:
            return json.loads(_SCHEMA_CACHE.read_text())
        except Exception:
            pass
    return []


def _get_tool_defs() -> list[dict]:
    """Get tool definitions — live from MCP if authenticated, else from cache."""
    if is_slack_authenticated():
        defs = _fetch_and_cache_schemas()
        if defs:
            return defs
    # Fall back to cached schemas
    cached = _load_cached_schemas()
    if cached:
        print(f"[SLACK MCP] Using {len(cached)} cached tool schemas")
        return cached
    print("[SLACK MCP] No schemas available — Slack not authenticated and no cache")
    return []


# Load at import time
TOOL_DEFS = _get_tool_defs()

TOOL_STATUS = {
    "slack_send_message":              "Drafting Slack message...",
    "slack_schedule_message":          "Drafting scheduled message...",
    "slack_search_public_and_private": "Searching Slack...",
    "slack_search_public":             "Searching public channels...",
    "slack_search_channels":           "Searching channels...",
    "slack_search_users":              "Searching users...",
    "slack_read_channel":              "Reading channel...",
    "slack_read_thread":               "Reading thread...",
    "slack_read_user_profile":         "Loading user profile...",
    "slack_create_canvas":             "Creating canvas...",
    "slack_update_canvas":             "Updating canvas...",
    "slack_read_canvas":               "Reading canvas...",
    "slack_send_message_draft":        "Creating Slack draft...",
}


# ── Handlers ──────────────────────────────────────────────────────────────────

def _generic_mcp_handler(tool_name: str, **kwargs) -> dict:
    """Generic handler — passes tool call directly to official Slack MCP."""
    # Strip None values
    args = {k: v for k, v in kwargs.items() if v is not None}
    return _mcp_call(lambda: {"result": get_slack_mcp().call(tool_name, args)})


def _handle_slack_send_message(channel_id: str, message: str, thread_ts: str | None = None, **kw) -> dict:
    """Send message — goes through draft approval (human-in-the-loop)."""
    from .._drafts import create_draft
    params = {"channel_id": channel_id, "message": message}
    if thread_ts:
        params["thread_ts"] = thread_ts
    draft_id = create_draft(
        draft_type="slack-post",
        params=params,
        preview={"channel": channel_id, "message_snippet": message[:200]},
    )
    return {
        "_draft": "slack-post",
        "data": {
            "draft_id": draft_id,
            "channel": channel_id,
            "message": message,
            "message_snippet": message[:200],
        },
        "_user_message": "Draft message ready for your approval. Click 'I approve to send'.",
    }


def _handle_slack_schedule_message(channel_id: str, message: str, post_at: int, thread_ts: str | None = None, **kw) -> dict:
    """Schedule message — goes through draft approval."""
    from .._drafts import create_draft
    params = {"channel_id": channel_id, "message": message, "post_at": post_at}
    if thread_ts:
        params["thread_ts"] = thread_ts
    draft_id = create_draft(
        draft_type="slack-schedule",
        params=params,
        preview={"channel": channel_id, "message_snippet": message[:200], "post_at": str(post_at)},
    )
    return {
        "_draft": "slack-schedule",
        "data": {
            "draft_id": draft_id,
            "channel": channel_id,
            "message": message,
            "message_snippet": message[:200],
            "post_at": str(post_at),
        },
        "_user_message": "Draft scheduled message ready for your approval. Click 'I approve to send'.",
    }


# Build handler dict — write tools get draft wrappers, everything else passes through
TOOL_HANDLERS = {}
for _td in TOOL_DEFS:
    _name = _td["name"]
    if _name == "slack_send_message":
        TOOL_HANDLERS[_name] = _handle_slack_send_message
    elif _name == "slack_schedule_message":
        TOOL_HANDLERS[_name] = _handle_slack_schedule_message
    else:
        def _make_handler(tn):
            def _handler(**kwargs):
                return _generic_mcp_handler(tn, **kwargs)
            return _handler
        TOOL_HANDLERS[_name] = _make_handler(_name)
