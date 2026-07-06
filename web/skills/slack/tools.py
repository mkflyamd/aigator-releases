"""Slack skill — backed by direct Slack Web API calls.

All reads go through the same _slack_web_api helper used by the Slack routes.
Write operations go through the draft approval flow (human-in-the-loop).
"""

import json

from .mcp_client import is_slack_authenticated

SKILL_ID = "slack"
ALWAYS_ON = False

_ERROR_NOT_AUTHED = {"error": "not_authed", "result": "Slack is not authenticated. Please connect your Slack account in Settings."}


def _api(endpoint: str, params: dict = None, method: str = "GET") -> dict:
    """Call _slack_web_api from routes.slack (same process, no HTTP round-trip)."""
    try:
        from routes.slack import _slack_web_api
        return _slack_web_api(endpoint, params or {}, method)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOL_DEFS = [
    {
        "name": "slack_search_channels",
        "description": "Search for Slack channels by name or keyword. Returns channel IDs needed for other tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Channel name or keyword to search for"},
                "channel_types": {"type": "string", "description": "Comma-separated types: public_channel,private_channel (default: both)"},
                "limit": {"type": "integer", "description": "Max results (default 100)"},
            },
            "required": [],
        },
    },
    {
        "name": "slack_read_channel",
        "description": "Read recent messages from a Slack channel. Use oldest/latest (Unix timestamps) to filter by time range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "Slack channel ID (e.g. C01234ABCD)"},
                "limit": {"type": "integer", "description": "Number of messages to fetch (default 50, max 200)"},
                "oldest": {"type": "string", "description": "Only messages after this Unix timestamp"},
                "latest": {"type": "string", "description": "Only messages before this Unix timestamp"},
            },
            "required": ["channel_id"],
        },
    },
    {
        "name": "slack_read_thread",
        "description": "Read all replies in a Slack thread. Requires both channel_id and the parent message timestamp.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "Slack channel ID"},
                "message_ts": {"type": "string", "description": "Timestamp of the parent message (e.g. 1700000000.123456)"},
                "limit": {"type": "integer", "description": "Number of replies to fetch (default 50)"},
            },
            "required": ["channel_id", "message_ts"],
        },
    },
    {
        "name": "slack_search_public_and_private",
        "description": "Search messages across all Slack channels (public and private). Use Slack search syntax: from:@user, in:#channel, before:/after: dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Slack search query (e.g. 'from:@alice in:#general')"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
                "sort": {"type": "string", "description": "Sort order: timestamp or score"},
                "sort_dir": {"type": "string", "description": "Direction: asc or desc"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "slack_search_users",
        "description": "Search for Slack users by name or email. Returns user IDs needed to send DMs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name, display name, or email to search for"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "slack_read_user_profile",
        "description": "Get detailed profile information for a Slack user by their user ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "Slack user ID (e.g. U01234ABCD)"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "slack_send_message",
        "description": "Send a message to a Slack channel or DM. Creates a DRAFT for user approval — never auto-sends.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "Channel ID or user ID for DMs"},
                "message": {"type": "string", "description": "Message text (Slack mrkdwn formatting supported)"},
                "thread_ts": {"type": "string", "description": "Parent message timestamp to reply in a thread"},
            },
            "required": ["channel_id", "message"],
        },
    },
]

TOOL_STATUS = {
    "slack_search_channels":           "Searching Slack channels…",
    "slack_read_channel":              "Reading channel messages…",
    "slack_read_thread":               "Reading thread replies…",
    "slack_search_public_and_private": "Searching Slack messages…",
    "slack_search_users":              "Looking up Slack user…",
    "slack_read_user_profile":         "Loading user profile…",
    "slack_send_message":              "Drafting Slack message…",
}


# ── Handlers ──────────────────────────────────────────────────────────────────

def _handle_slack_search_channels(query: str = "", channel_types: str = "public_channel,private_channel", limit: int = 100, **kw) -> dict:
    if not is_slack_authenticated():
        return _ERROR_NOT_AUTHED
    from skills.slack.mcp_client import _load_token
    stored = _load_token()
    team_id = stored.get("team_id", "")

    channels = []
    for ch_type in channel_types.replace(" ", "").split(","):
        params = {"types": ch_type, "limit": min(limit, 200), "exclude_archived": "true"}
        if team_id:
            params["team_id"] = team_id
        data = _api("conversations.list", params)
        if not data.get("ok"):
            continue
        for ch in data.get("channels", []):
            name = ch.get("name", "")
            if query and query.lower() not in name.lower():
                continue
            channels.append({
                "channel_id": ch.get("id", ""),
                "channel_name": name,
                "type": ch_type,
                "purpose": ch.get("purpose", {}).get("value", "") if isinstance(ch.get("purpose"), dict) else "",
                "topic": ch.get("topic", {}).get("value", "") if isinstance(ch.get("topic"), dict) else "",
            })

    return {"result": json.dumps(channels[:limit]) if channels else "[]", "channels": channels}


def _handle_slack_read_channel(channel_id: str, limit: int = 50, oldest: str = None, latest: str = None, **kw) -> dict:
    if not is_slack_authenticated():
        return _ERROR_NOT_AUTHED
    from skills.slack.mcp_client import _load_token
    stored = _load_token()
    team_id = stored.get("team_id", "")

    params = {"channel": channel_id, "limit": min(limit, 200)}
    if team_id:
        params["team_id"] = team_id
    if oldest:
        params["oldest"] = oldest
    if latest:
        params["latest"] = latest

    data = _api("conversations.history", params)
    if not data.get("ok"):
        return {"error": data.get("error", "unknown"), "result": f"Could not read channel: {data.get('error')}"}

    messages = data.get("messages", [])
    # Format messages for AI readability
    formatted = []
    for msg in reversed(messages):  # oldest first
        if msg.get("subtype") in ("channel_join", "channel_leave"):
            continue
        formatted.append({
            "ts": msg.get("ts", ""),
            "user": msg.get("user", msg.get("bot_id", "unknown")),
            "text": msg.get("text", ""),
            "reply_count": msg.get("reply_count", 0),
            "thread_ts": msg.get("thread_ts", ""),
            "latest_reply": msg.get("latest_reply", ""),
        })

    return {
        "result": json.dumps(formatted),
        "messages": formatted,
        "has_more": data.get("has_more", False),
    }


def _handle_slack_read_thread(channel_id: str, message_ts: str, limit: int = 50, **kw) -> dict:
    if not is_slack_authenticated():
        return _ERROR_NOT_AUTHED
    from skills.slack.mcp_client import _load_token
    stored = _load_token()
    team_id = stored.get("team_id", "")

    params = {"channel": channel_id, "ts": message_ts, "limit": min(limit, 200)}
    if team_id:
        params["team_id"] = team_id

    data = _api("conversations.replies", params)
    if not data.get("ok"):
        return {"error": data.get("error", "unknown"), "result": f"Could not read thread: {data.get('error')}"}

    messages = data.get("messages", [])
    formatted = []
    for msg in messages:
        formatted.append({
            "ts": msg.get("ts", ""),
            "user": msg.get("user", msg.get("bot_id", "unknown")),
            "text": msg.get("text", ""),
            "is_parent": msg.get("ts") == message_ts,
        })

    return {"result": json.dumps(formatted), "messages": formatted}


def _handle_slack_search_public_and_private(query: str, limit: int = 20, sort: str = "timestamp", sort_dir: str = "desc", **kw) -> dict:
    if not is_slack_authenticated():
        return _ERROR_NOT_AUTHED
    if not query:
        return {"result": "[]", "messages": []}

    params = {"query": query, "count": min(limit, 100)}
    data = _api("search.messages", params)

    if not data.get("ok"):
        err = data.get("error", "unknown")
        if "missing_scope" in err:
            return {"result": "Search requires the search:read scope. Try reading specific channels instead using slack_read_channel.", "messages": []}
        return {"error": err, "result": f"Search failed: {err}"}

    matches = data.get("messages", {}).get("matches", [])
    formatted = []
    for m in matches:
        ch = m.get("channel", {})
        formatted.append({
            "ts": m.get("ts", ""),
            "channel_id": ch.get("id", ""),
            "channel_name": ch.get("name", ""),
            "user": m.get("username", m.get("user", "unknown")),
            "text": m.get("text", ""),
            "thread_ts": m.get("thread_ts", ""),
            "permalink": m.get("permalink", ""),
        })

    return {"result": json.dumps(formatted), "messages": formatted}


def _handle_slack_search_users(query: str, **kw) -> dict:
    if not is_slack_authenticated():
        return _ERROR_NOT_AUTHED

    from skills.slack.mcp_client import _load_token
    team_id = _load_token().get("team_id", "")
    ql = query.lower()
    matches = []
    cursor = None
    for _ in range(10):  # paginate up to 10 pages
        params = {"limit": 200}
        if team_id:
            params["team_id"] = team_id
        if cursor:
            params["cursor"] = cursor
        data = _api("users.list", params)
        if not data.get("ok"):
            return {"error": data.get("error"), "result": f"Could not search users: {data.get('error')}"}
        for member in data.get("members", []):
            if member.get("deleted") or member.get("is_bot"):
                continue
            profile = member.get("profile", {})
            display = (profile.get("display_name") or profile.get("real_name") or "").lower()
            email = (profile.get("email") or "").lower()
            name_handle = (member.get("name") or "").lower()
            if ql in display or ql in email or ql in name_handle or ql == member.get("id", "").lower():
                matches.append({
                    "user_id": member["id"],
                    "display_name": profile.get("real_name") or profile.get("display_name", ""),
                    "real_name": profile.get("real_name", ""),
                    "email": profile.get("email", ""),
                    "title": profile.get("title", ""),
                })
            if len(matches) >= 10:
                break
        if len(matches) >= 10:
            break
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    return {"result": json.dumps(matches[:10]), "users": matches[:10]}


def _handle_slack_read_user_profile(user_id: str, **kw) -> dict:
    if not is_slack_authenticated():
        return _ERROR_NOT_AUTHED

    data = _api("users.info", {"user": user_id})
    if not data.get("ok"):
        return {"error": data.get("error"), "result": f"Could not load profile: {data.get('error')}"}

    user = data.get("user", {})
    profile = user.get("profile", {})
    result = {
        "user_id": user.get("id", user_id),
        "display_name": profile.get("display_name") or profile.get("real_name", ""),
        "real_name": profile.get("real_name", ""),
        "email": profile.get("email", ""),
        "title": profile.get("title", ""),
        "status_text": profile.get("status_text", ""),
        "is_admin": user.get("is_admin", False),
        "timezone": user.get("tz_label", ""),
    }
    return {"result": json.dumps(result), **result}


def _handle_slack_send_message(channel_id: str, message: str, thread_ts: str | None = None, **kw) -> dict:
    """Send message — goes through draft approval (human-in-the-loop). Never auto-sends."""
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


# ── Handler dispatch table ────────────────────────────────────────────────────

TOOL_HANDLERS = {
    "slack_search_channels":           _handle_slack_search_channels,
    "slack_read_channel":              _handle_slack_read_channel,
    "slack_read_thread":               _handle_slack_read_thread,
    "slack_search_public_and_private": _handle_slack_search_public_and_private,
    "slack_search_users":              _handle_slack_search_users,
    "slack_read_user_profile":         _handle_slack_read_user_profile,
    "slack_send_message":              _handle_slack_send_message,
}
