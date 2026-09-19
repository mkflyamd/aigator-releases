"""Slack skill — backed by direct Slack Web API calls.

All reads go through the same _slack_web_api helper used by the Slack routes.
Write operations go through the draft approval flow (human-in-the-loop).
"""

import json
import re

from .mcp_client import is_slack_authenticated

SKILL_ID = "slack"
ALWAYS_ON = False

_ERROR_NOT_AUTHED = {
    "error": "not_authed",
    "result": "Slack is not authenticated. Please connect your Slack account in Settings.",
}

# Cache: user_id -> display name. Avoids repeated users.info API calls.
_user_cache: dict = {}


def _api(endpoint: str, params: dict = None, method: str = "GET") -> dict:
    """Call _slack_web_api from routes.slack (same process, no HTTP round-trip)."""
    try:
        from routes.slack import _slack_web_api

        return _slack_web_api(endpoint, params or {}, method)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _resolve_user(user_id: str) -> str:
    """Resolve a Slack user ID to a display name. Cached."""
    if not user_id or user_id == "unknown":
        return "unknown"
    # Bot IDs start with B
    if user_id.startswith("B"):
        return "bot"
    if user_id in _user_cache:
        return _user_cache[user_id]
    try:
        data = _api("users.info", {"user": user_id})
        if data.get("ok"):
            user = data.get("user", {})
            profile = user.get("profile", {})
            name = (
                profile.get("real_name")
                or profile.get("display_name")
                or user.get("name", user_id)
            )
            _user_cache[user_id] = name
            return name
    except Exception:
        pass
    _user_cache[user_id] = user_id  # cache the miss too
    return user_id


import re as _re

# Slack encodes in-body user mentions as <@U0123ABCD> (optionally <@U0123ABCD|name>).
_MENTION_RE = _re.compile(r"<@([A-Z0-9]+)(?:\|[^>]*)?>")


def _resolve_mentions_in_text(text: str) -> str:
    """Replace <@UID> user mentions in message body text with @DisplayName."""
    if not text or "<@" not in text:
        return text

    def _sub(m: "_re.Match") -> str:
        uid = m.group(1)
        if uid.startswith("USLACKBOT"):
            return "@Slackbot"
        return "@" + _resolve_user(uid)

    return _MENTION_RE.sub(_sub, text)


def _resolve_users_in_messages(messages: list) -> list:
    """Resolve user IDs to display names — both the sender AND any <@UID>
    mentions inside the message body text."""
    for msg in messages:
        uid = msg.get("user", "")
        if uid and not uid.startswith("USLACKBOT"):
            msg["user_id"] = uid
            msg["user"] = _resolve_user(uid)
        if msg.get("text"):
            msg["text"] = _resolve_mentions_in_text(msg["text"])
    return messages


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOL_DEFS = [
    {
        "name": "slack_search_channels",
        "description": "Search for Slack channels by name or keyword. Returns channel IDs needed for other tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Channel name or keyword to search for",
                },
                "channel_types": {
                    "type": "string",
                    "description": "Comma-separated types: public_channel,private_channel (default: both)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 100)",
                },
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
                "channel_id": {
                    "type": "string",
                    "description": "Slack channel ID (e.g. C01234ABCD)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of messages to fetch (default 50, max 200)",
                },
                "oldest": {
                    "type": "string",
                    "description": "Only messages after this Unix timestamp",
                },
                "latest": {
                    "type": "string",
                    "description": "Only messages before this Unix timestamp",
                },
            },
            "required": ["channel_id"],
        },
    },
    {
        "name": "slack_read_thread",
        "description": "Read replies in a Slack thread. Requires both channel_id and the parent message timestamp. Use response_format='concise' when answering a focused question about who said what; it avoids oversized thread payloads.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "Slack channel ID"},
                "message_ts": {
                    "type": "string",
                    "description": "Timestamp of the parent message (e.g. 1700000000.123456)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of replies to fetch (default 50)",
                },
                "response_format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "description": "concise is the safe default for focused questions and summaries; detailed is only for explicit full-detail or exact-wording requests.",
                    "default": "concise",
                },
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
                "query": {
                    "type": "string",
                    "description": "Slack search query (e.g. 'from:@alice in:#general')",
                },
                "limit": {"type": "integer", "description": "Max results (default 20)"},
                "sort": {
                    "type": "string",
                    "description": "Sort order: timestamp or score",
                },
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
                "query": {
                    "type": "string",
                    "description": "Name, display name, or email to search for",
                },
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
                "user_id": {
                    "type": "string",
                    "description": "Slack user ID (e.g. U01234ABCD)",
                },
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "slack_send_message",
        "description": "Stage a Slack channel post, thread reply, or DM for user approval. Never auto-sends. For a channel use channel_id; for a DM use user_id. Always carry the active workspace team_id returned by the selected Slack chip.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Slack channel ID (for example C01234ABCD). Do not pass a user ID here.",
                },
                "user_id": {
                    "type": "string",
                    "description": "Slack user ID for a direct message (for example U01234ABCD). Do not open the DM until user approval.",
                },
                "team_id": {
                    "type": "string",
                    "description": "Workspace ID from the selected Slack destination. Required for UI-selected destinations.",
                },
                "message": {
                    "type": "string",
                    "description": "Message text (Slack mrkdwn formatting supported)",
                },
                "thread_ts": {
                    "type": "string",
                    "description": "Parent message timestamp to reply in a thread",
                },
                "mentions": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Selected Slack people as {user_id, name}. Matching @Name tokens in the message are compiled to real Slack mentions.",
                },
            },
            "required": ["message"],
        },
    },
]

TOOL_STATUS = {
    "slack_search_channels": "Searching Slack channels…",
    "slack_read_channel": "Reading channel messages…",
    "slack_read_thread": "Reading thread replies…",
    "slack_search_public_and_private": "Searching Slack messages…",
    "slack_search_users": "Looking up Slack user…",
    "slack_read_user_profile": "Loading user profile…",
    "slack_send_message": "Drafting Slack message…",
}


# ── Handlers ──────────────────────────────────────────────────────────────────


def _handle_slack_search_channels(
    query: str = "",
    channel_types: str = "public_channel,private_channel",
    limit: int = 100,
    **kw,
) -> dict:
    if not is_slack_authenticated():
        return _ERROR_NOT_AUTHED
    from skills.slack.mcp_client import _load_token

    stored = _load_token()
    team_id = stored.get("team_id", "")
    workspace_name = stored.get("team", "Slack")

    channels = []
    for ch_type in channel_types.replace(" ", "").split(","):
        params = {
            "types": ch_type,
            "limit": min(limit, 200),
            "exclude_archived": "true",
        }
        if team_id:
            params["team_id"] = team_id
        data = _api("conversations.list", params)
        if not data.get("ok"):
            continue
        for ch in data.get("channels", []):
            name = ch.get("name", "")
            if query and query.lower() not in name.lower():
                continue
            channels.append(
                {
                    "channel_id": ch.get("id", ""),
                    "channel_name": name,
                    "team_id": team_id,
                    "workspace_name": workspace_name,
                    "type": ch_type,
                    "purpose": ch.get("purpose", {}).get("value", "")
                    if isinstance(ch.get("purpose"), dict)
                    else "",
                    "topic": ch.get("topic", {}).get("value", "")
                    if isinstance(ch.get("topic"), dict)
                    else "",
                }
            )

    # Record discovered channels in the persistent cache
    if channels:
        try:
            from routes.slack import _record_channel
            for ch in channels:
                _record_channel(ch["channel_id"], ch["channel_name"], ch.get("team_id", team_id), ch.get("type", ""))
        except Exception:
            pass

    # Fallback: if conversations.list is admin-restricted and returned nothing,
    # search the persistent cache of previously-seen channels
    if not channels and query:
        try:
            from routes.slack import _lookup_channel_by_name
            cached = _lookup_channel_by_name(query)
            if cached:
                channels = [{
                    "channel_id": c["channel_id"],
                    "channel_name": c["name"],
                    "team_id": c.get("team_id", team_id),
                    "workspace_name": workspace_name,
                    "type": c.get("type", ""),
                    "purpose": "",
                    "topic": "",
                    "_from_cache": True,
                    "_accessible": c.get("accessible", True),
                } for c in cached]
        except Exception:
            pass

    return {
        "result": json.dumps(channels[:limit]) if channels else "[]",
        "channels": channels,
    }


def _handle_slack_read_channel(
    channel_id: str, limit: int = 50, oldest: str = None, latest: str = None, **kw
) -> dict:
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
        return {
            "error": data.get("error", "unknown"),
            "result": f"Could not read channel: {data.get('error')}",
        }

    messages = data.get("messages", [])
    # Format messages for AI readability
    formatted = []
    for msg in reversed(messages):  # oldest first
        if msg.get("subtype") in ("channel_join", "channel_leave"):
            continue
        formatted.append(
            {
                "ts": msg.get("ts", ""),
                "user": msg.get("user", msg.get("bot_id", "unknown")),
                "text": msg.get("text", ""),
                "reply_count": msg.get("reply_count", 0),
                "thread_ts": msg.get("thread_ts", ""),
                "latest_reply": msg.get("latest_reply", ""),
            }
        )

    _resolve_users_in_messages(formatted)
    return {
        "result": json.dumps(formatted),
        "messages": formatted,
        "has_more": data.get("has_more", False),
    }


def _handle_slack_read_thread(
    channel_id: str,
    message_ts: str,
    limit: int = 50,
    response_format: str = "concise",
    **kw,
) -> dict:
    if not is_slack_authenticated():
        return _ERROR_NOT_AUTHED
    # A thread reply set is addressable only within its channel. An empty
    # channel_id (e.g. from a malformed pin that lost its channel) must fail
    # loudly, not query Slack with a blank channel.
    if not (channel_id or "").strip():
        return {
            "error": (
                "Cannot read a Slack thread without a channel_id. The message_ts "
                "identifies a message only within its channel. Provide the "
                "channel_id, or use slack_list_channels / slack_read_channel to "
                "locate the conversation first."
            ),
        }
    from skills.slack.mcp_client import _load_token

    stored = _load_token()
    team_id = stored.get("team_id", "")

    params = {"channel": channel_id, "ts": message_ts, "limit": min(limit, 200)}
    if team_id:
        params["team_id"] = team_id

    data = _api("conversations.replies", params)
    if not data.get("ok"):
        return {
            "error": data.get("error", "unknown"),
            "result": f"Could not read thread: {data.get('error')}",
        }

    messages = data.get("messages", [])
    # Invalid direct callers must not silently become unbounded detailed reads.
    response_format = "detailed" if response_format == "detailed" else "concise"
    concise = response_format == "concise"
    formatted = []
    truncated_messages = 0
    for msg in messages:
        text = msg.get("text", "")
        if concise and len(text) > 600:
            text = text[:597].rstrip() + "…"
            truncated_messages += 1
        formatted.append(
            {
                "ts": msg.get("ts", ""),
                "user": msg.get("user", msg.get("bot_id", "unknown")),
                "text": text,
                "is_parent": msg.get("ts") == message_ts,
            }
        )

    _resolve_users_in_messages(formatted)
    # Keep a compact textual summary plus one structured representation. The
    # old result=json.dumps(messages) duplicated the entire thread and caused
    # tool-output truncation, which in turn pushed the model into brittle
    # run_python parsing attempts.
    return {
        "result": f"Slack thread: {len(formatted)} message(s), format={response_format}.",
        "messages": formatted,
        "message_count": len(formatted),
        "response_format": response_format,
        "truncated_messages": truncated_messages,
    }


def _handle_slack_search_public_and_private(
    query: str, limit: int = 20, sort: str = "timestamp", sort_dir: str = "desc", **kw
) -> dict:
    if not is_slack_authenticated():
        return _ERROR_NOT_AUTHED
    if not query:
        return {"result": "[]", "messages": []}

    params = {"query": query, "count": min(limit, 100)}
    data = _api("search.messages", params)

    if not data.get("ok"):
        err = data.get("error", "unknown")
        if "missing_scope" in err:
            return {
                "result": "Search requires the search:read scope. Try reading specific channels instead using slack_read_channel.",
                "messages": [],
            }
        return {"error": err, "result": f"Search failed: {err}"}

    matches = data.get("messages", {}).get("matches", [])
    formatted = []
    for m in matches:
        ch = m.get("channel", {})
        formatted.append(
            {
                "ts": m.get("ts", ""),
                "channel_id": ch.get("id", ""),
                "channel_name": ch.get("name", ""),
                "user": m.get("username", m.get("user", "unknown")),
                "text": m.get("text", ""),
                "thread_ts": m.get("thread_ts", ""),
                "permalink": m.get("permalink", ""),
            }
        )

    _resolve_users_in_messages(formatted)
    return {"result": json.dumps(formatted), "messages": formatted}


def _handle_slack_search_users(query: str, **kw) -> dict:
    if not is_slack_authenticated():
        return _ERROR_NOT_AUTHED

    from skills.slack.mcp_client import _load_token

    team_id = _load_token().get("team_id", "")
    workspace_name = _load_token().get("team", "Slack")
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
            return {
                "error": data.get("error"),
                "result": f"Could not search users: {data.get('error')}",
            }
        for member in data.get("members", []):
            if member.get("deleted") or member.get("is_bot"):
                continue
            profile = member.get("profile", {})
            display = (
                profile.get("display_name") or profile.get("real_name") or ""
            ).lower()
            email = (profile.get("email") or "").lower()
            name_handle = (member.get("name") or "").lower()
            if (
                ql in display
                or ql in email
                or ql in name_handle
                or ql == member.get("id", "").lower()
            ):
                matches.append(
                    {
                        "user_id": member["id"],
                        "display_name": profile.get("real_name")
                        or profile.get("display_name", ""),
                        "real_name": profile.get("real_name", ""),
                        "email": profile.get("email", ""),
                        "team_id": team_id,
                        "workspace_name": workspace_name,
                        "title": profile.get("title", ""),
                    }
                )
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
        return {
            "error": data.get("error"),
            "result": f"Could not load profile: {data.get('error')}",
        }

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


def _handle_slack_send_message(
    channel_id: str = "",
    user_id: str = "",
    team_id: str = "",
    message: str = "",
    thread_ts: str | None = None,
    mentions: list[dict] | None = None,
    **kw,
) -> dict:
    """Send message — goes through draft approval (human-in-the-loop). Never auto-sends."""
    from .._drafts import create_draft
    from skills.slack.mcp_client import _load_token

    if not message:
        return {"error": "A Slack draft needs a message."}
    if bool(channel_id) == bool(user_id):
        return {
            "error": "Choose exactly one Slack destination: channel_id for a channel or user_id for a DM."
        }

    active_workspace = _load_token()
    active_team_id = active_workspace.get("team_id", "")
    if not active_team_id:
        return {"error": "Slack workspace identity is unavailable. Reconnect Slack before creating a draft."}
    if not team_id:
        return {"error": "Slack draft is missing a workspace ID. Reselect the person or channel from the Slack picker."}
    if team_id != active_team_id:
        return {
            "error": "The selected Slack destination belongs to a different workspace. Switch workspace and reselect it."
        }

    for mention in sorted(mentions or [], key=lambda item: len(str(item.get("name", ""))), reverse=True):
        user_id_for_mention = str(mention.get("user_id", ""))
        name = str(mention.get("name", "")).lstrip("@")
        if not user_id_for_mention or not name:
            continue
        # Only replace an explicit standalone @Name token. Ordinary prose and
        # email addresses remain untouched.
        pattern = re.compile(r"(?<![\w@])@" + re.escape(name) + r"(?![\w])", re.IGNORECASE)
        message = pattern.sub(f"<@{user_id_for_mention}>", message)

    params = {
        "channel_id": channel_id,
        "user_id": user_id,
        "team_id": team_id or active_team_id,
        "workspace_name": active_workspace.get("team", "Slack"),
        "message": message,
    }
    if thread_ts:
        params["thread_ts"] = thread_ts
    draft_type = "slack-dm" if user_id else "slack-post"
    draft_id = create_draft(
        draft_type=draft_type,
        params=params,
        preview={
            "channel": channel_id,
            "recipient": _resolve_user(user_id) if user_id else "",
            "team_id": params["team_id"],
            "message_snippet": message[:200],
        },
    )
    if user_id:
        recipient = _resolve_user(user_id)
        return {
            "_draft": "slack-dm",
            "data": {
                "draft_id": draft_id,
                "recipient": recipient,
                "user_id": user_id,
                "team_id": params["team_id"],
                "workspace_name": params["workspace_name"],
                "message": message,
                "message_snippet": message[:200],
            },
            "_user_message": "Slack DM draft ready for your approval. The DM is opened only after you send.",
        }

    # Resolve channel name for display
    channel_name = channel_id
    try:
        ch_data = _api("conversations.info", {"channel": channel_id})
        if ch_data.get("ok"):
            ch = ch_data.get("channel", {})
            channel_name = ch.get("name", channel_id)
            if ch.get("is_im"):
                # DM: resolve the user name
                user_id = ch.get("user", "")
                if user_id:
                    channel_name = _resolve_user(user_id)
    except Exception:
        pass

    return {
        "_draft": "slack-post",
        "data": {
            "draft_id": draft_id,
            "channel": channel_name,
            "channel_id": channel_id,
            "team_id": params["team_id"],
            "workspace_name": params["workspace_name"],
            "thread_ts": thread_ts or "",
            "message": message,
            "message_snippet": message[:200],
        },
        "_user_message": "Slack draft ready for your approval. Review it in AI Gator, then click Post.",
    }


# ── Handler dispatch table ────────────────────────────────────────────────────

TOOL_HANDLERS = {
    "slack_search_channels": _handle_slack_search_channels,
    "slack_read_channel": _handle_slack_read_channel,
    "slack_read_thread": _handle_slack_read_thread,
    "slack_search_public_and_private": _handle_slack_search_public_and_private,
    "slack_search_users": _handle_slack_search_users,
    "slack_read_user_profile": _handle_slack_read_user_profile,
    "slack_send_message": _handle_slack_send_message,
}
