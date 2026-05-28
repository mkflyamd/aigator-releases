"""Teams skill -- 4 tools."""
from pathlib import Path
from datetime import datetime, timedelta, timezone

from hooks.executor import fire_all_skill_hooks

SKILL_ID = "teams"
ALWAYS_ON = False

DIRECT_INTENTS = [
    {
        "patterns": ["teams messages", "check teams", "my teams", "teams chats",
                     "unread teams", "teams notifications"],
        "tool": "read_teams_chats",
        "args": {"hours": 24},
    },
]

TEAMS_SKILLS_DIR = Path(__file__).parent.parent / "m365-teams" / "scripts"

# ── Transcript module loader (dynamic, sys.modules-registered for dataclass support) ──
import importlib.util as _txi
import sys as _txsys

_TX_SCRIPTS = Path(__file__).parent.parent / "m365-teams" / "scripts"

def _tx_load(name: str):
    mod = _txsys.modules.get(f"_tx_{name}")
    if mod is not None:
        return mod
    spec = _txi.spec_from_file_location(f"_tx_{name}", str(_TX_SCRIPTS / f"{name}.py"))
    mod = _txi.module_from_spec(spec)
    # Register before exec so dataclasses resolve cls.__module__ correctly (Py 3.12+)
    _txsys.modules[f"_tx_{name}"] = mod
    # Also put scripts dir on sys.path so transcript_cache's `from transcript_config import ...` resolves
    if str(_TX_SCRIPTS) not in _txsys.path:
        _txsys.path.insert(0, str(_TX_SCRIPTS))
    spec.loader.exec_module(mod)
    return mod


TOOL_DEFS = [
    {
        "name": "read_channel_messages",
        "description": "Fetch recent messages from a Microsoft Teams channel. Use when the user mentions a #channel, asks what was discussed in a channel, or wants a summary of a specific Teams channel.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_id":    {"type": "string", "description": "The Teams group/team ID"},
                "channel_id": {"type": "string", "description": "The channel ID within that team"},
                "channel_name": {"type": "string", "description": "Human-readable channel name for context"},
                "hours": {"type": "integer", "description": "Hours back to look. Default 24.", "default": 24},
            },
            "required": ["team_id", "channel_id"],
        },
    },
    {
        "name": "read_teams_chats",
        "description": "Fetch recent Microsoft Teams chat messages. Use when user asks about Teams, recent conversations, what's happening, catch-me-up summaries, or specific people/topics discussed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "Hours back to look. Default 24.", "default": 24},
                "filter_topic": {"type": "string", "description": "Optional keyword to filter chats by topic (e.g. 'Cohere', 'TPM')"},
                "chat_id": {"type": "string", "description": "Optional Teams chat ID (19:...@thread.v2) to fetch a specific conversation."},
            },
            "required": [],
        },
    },
    {
        "name": "send_teams_message",
        "description": "Open a Teams compose form for the user to review and send. NEVER sends directly — always opens the Teams compose pane so the user can review, edit, and send manually. Use when user asks to send or compose a Teams message. When you have a chat_id, you may omit 'to' — the UI will resolve recipients from the chat.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address(es), comma-separated. MUST be real email addresses (e.g. 'john.doe@example.com'). If you only have a chat_id and not emails, leave this empty — the UI will resolve members from the chat."},
                "message": {"type": "string", "description": "Message content"},
                "chat_id": {"type": "string", "description": "Known Teams chat ID (19:...@thread.v2). Pass this if you know the target chat. When provided, 'to' can be omitted."},
                "chat_topic": {"type": "string", "description": "Display name of the target group chat (e.g. 'Cohere Leads'). Pass alongside chat_id for clear UX."},
                "html": {"type": "boolean", "description": "Send as HTML", "default": False},
            },
            "required": ["message"],
        },
    },
    {
        "name": "list_teams",
        "description": "List all Microsoft Teams the user belongs to. Use when user asks about their teams or wants to find a team ID.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "teams_open_compose",
        "description": (
            "Open a Teams compose form in the third pane so the user can review, edit, and send a Teams message. "
            "Use this INSTEAD OF send_teams_message when you have drafted a message for the user to send — "
            "let them review and approve it first. Pre-fill everything you know: recipient(s), message body, context. "
            "The user can edit the draft and click Send, or ask you to refine it further. "
            "If you know the Teams chat_id (e.g. from reading chats), pass it — the UI resolves correct recipients automatically. "
            "IMPORTANT: 'to' must be REAL email addresses (e.g. 'first.last@example.com'), NEVER 'placeholder' or fake values. "
            "If you don't have emails, pass chat_id and leave 'to' empty."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address(es), comma-separated. Must be real emails. If you only have chat_id, leave empty — UI resolves from chat."},
                "to_names": {"type": "string", "description": "Display name(s) of recipient(s) for the UI (comma-separated)."},
                "message": {"type": "string", "description": "Draft message body for the user to review/edit."},
                "context": {"type": "string", "description": "Optional brief context shown above the draft explaining why you wrote this."},
                "chat_id": {"type": "string", "description": "Known Teams chat ID (19:...@thread.v2). When provided, 'to' can be omitted — recipients are resolved from the chat."},
                "chat_topic": {"type": "string", "description": "Display name of the target group chat (e.g. 'Cohere Leads'). Pass alongside chat_id for clear UX."},
            },
            "required": ["message"],
        },
    },
]

# Transcript tools — pinned context provides (drive_id, item_id, transcript_id)
# as a single triple. Recordings live in the organizer's OneDrive; the IDs
# come from the beta drive-item endpoint.
_TX_INPUTS = {
    "drive_id": {"type": "string", "description": "OneDrive driveId where the recording lives."},
    "item_id": {"type": "string", "description": "DriveItem id of the recording .mp4."},
    "transcript_id": {"type": "string", "description": "Transcript id from list_recording_transcripts."},
}

TOOL_DEFS.extend([
    {
        "name": "get_meeting_transcript_full",
        "description": "Fetch the full speaker-attributed transcript for a meeting recording. Use ONLY when the pinned context indicates the transcript is under the size threshold.",
        "input_schema": {
            "type": "object",
            "properties": _TX_INPUTS,
            "required": ["drive_id", "item_id", "transcript_id"],
        },
    },
    {
        "name": "get_meeting_transcript_header",
        "description": "Get duration, speakers (with talk-time %), cue count, and a 90-second preview. Call this first for large transcripts.",
        "input_schema": {
            "type": "object",
            "properties": _TX_INPUTS,
            "required": ["drive_id", "item_id", "transcript_id"],
        },
    },
    {
        "name": "get_meeting_transcript_range",
        "description": "Get the transcript slice between start_min and end_min. Use for whole-meeting reads in chunks.",
        "input_schema": {
            "type": "object",
            "properties": {**_TX_INPUTS,
                           "start_min": {"type": "number"},
                           "end_min": {"type": "number"}},
            "required": ["drive_id", "item_id", "transcript_id", "start_min", "end_min"],
        },
    },
    {
        "name": "search_meeting_transcript",
        "description": "Substring search across cues. Returns matches with ~30s of context around each.",
        "input_schema": {
            "type": "object",
            "properties": {**_TX_INPUTS,
                           "query": {"type": "string"},
                           "max_results": {"type": "integer", "default": 5}},
            "required": ["drive_id", "item_id", "transcript_id", "query"],
        },
    },
    {
        "name": "get_meeting_transcript_speaker",
        "description": "Return all cues from a single speaker (case-insensitive substring match on display name).",
        "input_schema": {
            "type": "object",
            "properties": {**_TX_INPUTS,
                           "speaker_name": {"type": "string"}},
            "required": ["drive_id", "item_id", "transcript_id", "speaker_name"],
        },
    },
])

TOOL_STATUS = {
    "read_channel_messages": "\U0001f4e2 Reading channel messages...",
    "read_teams_chats": "\U0001f4ac Reading Teams chats...",
    "send_teams_message": "\U0001f4ac Sending Teams message...",
    "list_teams": "\U0001f4ac Listing Teams...",
    "teams_open_compose": "\U0001f4dd Opening Teams compose...",
}

TOOL_STATUS.update({
    "get_meeting_transcript_full": "\U0001f4dd Loading meeting transcript...",
    "get_meeting_transcript_header": "\U0001f4dd Reading transcript header...",
    "get_meeting_transcript_range": "\U0001f4dd Reading transcript range...",
    "search_meeting_transcript": "\U0001f50d Searching transcript...",
    "get_meeting_transcript_speaker": "\U0001f464 Filtering transcript by speaker...",
})


def _tool_read_channel_messages(team_id: str, channel_id: str, channel_name: str = "", hours: int = 24) -> dict:
    from .._m365.helpers import make_teams_gc, html_to_text
    try:
        gc = make_teams_gc()
        if not gc.get_token():
            return {"error": "Teams token expired or missing — please refresh in Settings → Teams token.", "auth_required": True}
    except Exception as e:
        return {"error": f"Teams authentication failed: {e}", "auth_required": True}
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        resp = gc.get(f"/teams/{team_id}/channels/{channel_id}/messages",
                      {"$top": "50",
                       "$filter": f"createdDateTime ge {since_str}",
                       "$select": "id,createdDateTime,from,body,mentions,messageType"})
        msgs = resp.get("value", [])
    except Exception as e:
        if getattr(e, "status_code", 0) in (401, 403):
            return {"error": "Cannot read channel messages — token may lack ChannelMessage.Read.All scope. Try refreshing the Teams token.", "auth_required": True}
        if getattr(e, "status_code", 0) == 400 or "Select" in str(e):
            # Some channel types reject $select — retry without it.
            try:
                resp = gc.get(f"/teams/{team_id}/channels/{channel_id}/messages",
                              {"$top": "50", "$filter": f"createdDateTime ge {since_str}"})
                msgs = resp.get("value", [])
            except Exception as e2:
                return {"error": f"Failed to fetch channel messages: {e2}"}
        else:
            return {"error": f"Failed to fetch channel messages: {e}"}
    results = []
    for m in msgs:
        if not m or not m.get("createdDateTime"):
            continue
        if m.get("messageType", "message") != "message":
            continue
        sender = (m.get("from") or {}).get("user", {}).get("displayName", "")
        body = html_to_text((m.get("body") or {}).get("content", ""), max_len=800)
        # Include mentions/reactions so Claude can detect if user was mentioned
        mentions = [mn.get("mentioned", {}).get("user", {}).get("displayName", "")
                    for mn in (m.get("mentions") or [])
                    if mn.get("mentioned", {}).get("user", {}).get("displayName")]
        if body and sender:
            entry = {"sender": sender, "time": m["createdDateTime"][:16], "body": body}
            if mentions:
                entry["mentions"] = mentions
            results.append(entry)
    label = channel_name or channel_id
    if not results:
        return {"channel": label, "messages": [], "count": 0,
                "note": f"No messages found in the last {hours}h. The channel may be quiet or the token may lack read scope."}
    return {"channel": label, "messages": list(reversed(results)), "count": len(results)}


def _tool_read_teams_chats(hours: int = 24, filter_topic: str = "", chat_id: str = "") -> dict:
    import importlib.util

    # Load the FOCI-based read_chats module
    _rc_path = Path(__file__).parent.parent / "m365-teams" / "scripts" / "read_chats.py"
    _spec = importlib.util.spec_from_file_location("_teams_read_chats", str(_rc_path))
    _rc = importlib.util.module_from_spec(_spec)
    try:
        _spec.loader.exec_module(_rc)
    except Exception as e:
        return {"error": f"Failed to load Teams chat module: {e}"}

    try:
        skype_token, messaging_service = _rc.get_auth()
    except RuntimeError as e:
        return {"error": str(e), "auth_required": True}
    except Exception as e:
        return {"error": f"Teams authentication failed: {e}", "auth_required": True}

    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    def _parse_time(ts: str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    def _normalize(m: dict) -> dict:
        return {
            "sender": m.get("from", ""),
            "time": (m.get("time") or "")[:16].replace("T", " "),
            "body": m.get("content", ""),
        }

    def _within_window(messages: list) -> list:
        return [_normalize(m) for m in messages
                if not _parse_time(m.get("time", "")) or _parse_time(m.get("time", "")) >= since]

    # Single chat requested
    if chat_id:
        try:
            messages = _rc.read_messages(chat_id, skype_token, messaging_service, limit=50)
        except Exception as e:
            return {"error": f"Failed to fetch messages for chat {chat_id}: {e}"}
        return {"chats": [{"chat_id": chat_id, "topic": chat_id,
                           "messages": _within_window(messages)}]}

    # List chats, skip stale ones, fetch messages only for recent chats
    try:
        all_chats = _rc.list_chats(skype_token, messaging_service, limit=50)
    except Exception as e:
        return {"error": f"Failed to fetch Teams chats: {e}"}

    filter_lower = filter_topic.lower() if filter_topic else ""
    results = []

    for chat in all_chats:
        # Skip chats with no activity in the requested window
        last_t = _parse_time(chat.get("last_time", ""))
        if last_t and last_t < since:
            continue

        cid = chat.get("id", "")
        topic = chat.get("topic") or cid[:20]

        if filter_lower and filter_lower not in topic.lower():
            continue

        try:
            messages = _rc.read_messages(cid, skype_token, messaging_service, limit=20)
        except Exception:
            continue

        recent = _within_window(messages)
        if not recent:
            continue

        results.append({
            "chat_id": cid,
            "topic": topic,
            "chat_type": chat.get("type", ""),
            "messages": recent,
        })

    return {"chats": results}


def _resolve_user_id(gc, email: str) -> str:
    """Resolve an email/UPN to a Graph user ID.

    Strategy (same as the people-search picker):
      1. GET /users/{email}  — fast exact match by mail or UPN.
      2. GET /users?$search="mail:{email}"  — directory search by mail field.
      3. GET /users?$search="displayName:{name}"  — directory search by name
         derived from the email prefix (e.g. Akash.Verma@ → "Akash Verma").
      4. GET /me/people?$search="{email}"  — relationship-ranked fallback.
    """
    import re

    # 1. Direct lookup
    try:
        user = gc.get(f"/users/{email}", params={"$select": "id,mail,userPrincipalName"})
        uid = user.get("id", "")
        if uid:
            return uid
    except Exception:
        pass

    eventual = {"ConsistencyLevel": "eventual"}

    # 2. Directory search by mail field
    try:
        data = gc.get("/users", params={
            "$search": f'"mail:{email}"',
            "$select": "id,mail,userPrincipalName",
            "$top": "3",
        }, extra_headers=eventual)
        for u in data.get("value", []):
            m = (u.get("mail") or u.get("userPrincipalName") or "").lower()
            if m == email.lower():
                return u["id"]
        if data.get("value"):
            return data["value"][0]["id"]
    except Exception:
        pass

    # 3. Directory search by display name (derived from email prefix)
    name_query = re.sub(r"[._]+", " ", email.split("@")[0]).strip()
    if name_query:
        try:
            data = gc.get("/users", params={
                "$search": f'"displayName:{name_query}"',
                "$select": "id,mail,userPrincipalName,displayName",
                "$top": "5",
            }, extra_headers=eventual)
            for u in data.get("value", []):
                m = (u.get("mail") or u.get("userPrincipalName") or "").lower()
                if m == email.lower():
                    return u["id"]
            if data.get("value"):
                return data["value"][0]["id"]
        except Exception:
            pass

    # 4. Relationship-ranked fallback
    try:
        people = gc.get("/me/people", params={"$search": f'"{email}"', "$top": "5"})
        for p in people.get("value", []):
            for addr in p.get("scoredEmailAddresses", []):
                if addr.get("address", "").lower() == email.lower():
                    return p.get("id", "")
    except Exception:
        pass
    return ""


def _find_or_create_chat(gc, member_ids: list[str]) -> str:
    """
    Return a chat_id for a 1:1 or group chat with exactly these member IDs.

    Strategy:
    1. Try POST /chats (idempotent, requires Chat.Create or Chat.ReadWrite).
    2. If 403 (scope missing), fall back to scanning /me/chats for an existing
       match — works with just Chat.Read + ChatMessage.Send.
    3. For group chats with no existing match and no Create scope, raises.
    """
    chat_type = "oneOnOne" if len(member_ids) == 2 else "group"
    members_payload = [
        {
            "@odata.type": "#microsoft.graph.aadUserConversationMember",
            "roles": ["owner"],
            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{uid}')",
        }
        for uid in member_ids
    ]
    try:
        resp = gc.post("/chats", {
            "chatType": chat_type,
            "members": members_payload,
        })
        chat_id = resp.get("id", "")
        if chat_id:
            return chat_id
    except Exception as e:
        if getattr(e, "status_code", 0) != 403 and "403" not in str(e) and "Forbidden" not in str(e):
            raise  # non-scope error — re-raise immediately

    # 403 fallback: scan existing chats for a matching set of members
    import logging as _logging
    _log = _logging.getLogger("graph_client")
    other_ids = set(member_ids)
    try:
        chats = gc.get("/me/chats", {
            "$expand": "members",
            "$top": "50",
            "$filter": f"chatType eq '{chat_type}'",
        }).get("value", [])
        for chat in chats:
            member_user_ids = {
                m.get("userId", "") for m in chat.get("members", [])
                if m.get("userId")
            }
            if member_user_ids == other_ids:
                return chat["id"]
    except Exception as ex:
        _log.warning("chat scan fallback failed: %s", ex)
        raise Exception(
            f"Graph API 403: Chat.Create scope is missing. "
            f"Fallback scan of existing chats also failed: {ex}. "
            f"Re-capture your Teams token from a page that includes Chat.Create."
        ) from ex

    raise Exception(
        f"Graph API 403: Chat.Create scope is missing. "
        f"Re-capture your Teams token from a page that includes Chat.Create "
        f"(e.g. teams.microsoft.com → DevTools → Network → any request → copy Bearer token). "
        f"No existing {chat_type} chat found with those members to fall back to."
    )


def _tool_send_teams_message(to: str = "", message: str = "", chat_id: str = "", chat_topic: str = "", html: bool = False) -> dict:
    from hooks.events import BEFORE_TEAMS_MESSAGE
    hook_result = fire_all_skill_hooks(BEFORE_TEAMS_MESSAGE)
    if hook_result["blocked"]:
        return {
            "status": "blocked",
            "reason": hook_result["reason"] or "A plugin hook blocked this Teams message.",
        }
    # Safety: never send directly — always route to compose pane for human review
    return _tool_teams_open_compose(to=to, message=message, chat_id=chat_id, chat_topic=chat_topic, context="Drafted by Gator")


def _tool_list_teams() -> dict:
    from .._m365.helpers import make_teams_gc
    try:
        gc = make_teams_gc()
    except Exception as e:
        return {"error": f"Teams authentication failed: {e}", "auth_required": True}
    data = gc.get("/me/joinedTeams", {"$select": "id,displayName,description"})
    return {"teams": [{"id": t["id"], "name": t.get("displayName", ""), "description": t.get("description", "")}
                      for t in data.get("value", [])]}


def _tool_teams_open_compose(to: str, message: str, to_names: str = "", context: str = "", chat_id: str = "", chat_topic: str = "") -> dict:
    """Pane-signal tool: opens the Teams compose form in the third pane."""
    return {
        "_pane": "teams-compose",
        "data": {
            "to": to,
            "to_names": to_names,
            "message": message,
            "context": context,
            "chat_id": chat_id,
            "chat_topic": chat_topic,
        },
        "_user_message": "Draft opened in /teams compose pane for review. User can ask me to refine it here — multi-turn editing is supported.",
    }


def _tx_get_or_cache_vtt(drive_id: str, item_id: str, transcript_id: str) -> str:
    tx_cache = _tx_load("transcript_cache")
    tx_beta = _tx_load("transcript_beta")
    text = tx_cache.read(transcript_id)
    if text is None:
        text = tx_beta.fetch_transcript_content(drive_id, item_id, transcript_id)
        tx_cache.write(transcript_id, text)
    return text


def _tool_transcript_full(drive_id: str, item_id: str, transcript_id: str) -> dict:
    tx_vtt = _tx_load("transcript_vtt")
    tx_cfg = _tx_load("transcript_config")
    vtt = _tx_get_or_cache_vtt(drive_id, item_id, transcript_id)
    cues = tx_vtt.parse_vtt(vtt)
    return {"text": tx_vtt.cues_to_text(cues),
            "size_tokens_estimate": tx_cfg.estimate_tokens_from_vtt_bytes(len(vtt.encode("utf-8")))}


def _tool_transcript_header(drive_id: str, item_id: str, transcript_id: str) -> dict:
    tx_vtt = _tx_load("transcript_vtt")
    tx_cfg = _tx_load("transcript_config")
    vtt = _tx_get_or_cache_vtt(drive_id, item_id, transcript_id)
    cues = tx_vtt.parse_vtt(vtt)
    h = tx_vtt.build_header(cues, preview_seconds=90)
    h["size_tokens_estimate"] = tx_cfg.estimate_tokens_from_vtt_bytes(len(vtt.encode("utf-8")))
    return h


def _tool_transcript_range(drive_id: str, item_id: str, transcript_id: str,
                           start_min: float, end_min: float) -> dict:
    tx_vtt = _tx_load("transcript_vtt")
    vtt = _tx_get_or_cache_vtt(drive_id, item_id, transcript_id)
    cues = tx_vtt.parse_vtt(vtt)
    sliced = tx_vtt.slice_range(cues, start_min * 60.0, end_min * 60.0)
    return {"start_min": start_min, "end_min": end_min, "count": len(sliced),
            "text": tx_vtt.cues_to_text(sliced)}


def _tool_transcript_search(drive_id: str, item_id: str, transcript_id: str,
                            query: str, max_results: int = 5) -> dict:
    tx_vtt = _tx_load("transcript_vtt")
    tx_cfg = _tx_load("transcript_config")
    vtt = _tx_get_or_cache_vtt(drive_id, item_id, transcript_id)
    cues = tx_vtt.parse_vtt(vtt)
    hits = tx_vtt.search_cues(cues, query, tx_cfg.SEARCH_CONTEXT_SECONDS, max_results)
    return {"total": len(hits), "hits": hits}


def _tool_transcript_speaker(drive_id: str, item_id: str, transcript_id: str,
                             speaker_name: str) -> dict:
    tx_vtt = _tx_load("transcript_vtt")
    vtt = _tx_get_or_cache_vtt(drive_id, item_id, transcript_id)
    cues = tx_vtt.parse_vtt(vtt)
    filt = tx_vtt.filter_speaker(cues, speaker_name)
    return {"speaker": speaker_name, "count": len(filt), "text": tx_vtt.cues_to_text(filt)}


TOOL_HANDLERS = {
    "read_channel_messages": _tool_read_channel_messages,
    "read_teams_chats": _tool_read_teams_chats,
    "send_teams_message": _tool_send_teams_message,
    "list_teams": _tool_list_teams,
    "teams_open_compose": _tool_teams_open_compose,
}

TOOL_HANDLERS.update({
    "get_meeting_transcript_full": _tool_transcript_full,
    "get_meeting_transcript_header": _tool_transcript_header,
    "get_meeting_transcript_range": _tool_transcript_range,
    "search_meeting_transcript": _tool_transcript_search,
    "get_meeting_transcript_speaker": _tool_transcript_speaker,
})
