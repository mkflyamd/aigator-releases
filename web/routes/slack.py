"""Slack route group — channels, DMs, threads, search, reactions, auth."""

import asyncio
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import shared

router = APIRouter()

# ── Module-level user display-name cache ─────────────────────────────────────
# Persists for the process lifetime; backed by user_cache.json but only read
# once on first use. Failed/rate-limited resolutions are NOT written here.
_USER_CACHE: dict[str, str] = {}
_USER_CACHE_LOCK = threading.Lock()
_USER_CACHE_FILE = Path.home() / ".config" / "slack-mcp" / "user_cache.json"
_USER_CACHE_LOADED = False
_USERS_LIST_FETCHED = False  # tracks whether users.list has been used to bulk-populate cache


def _ensure_user_cache_loaded() -> None:
    """Load user_cache.json into _USER_CACHE exactly once per process."""
    global _USER_CACHE_LOADED
    if _USER_CACHE_LOADED:
        return
    with _USER_CACHE_LOCK:
        if _USER_CACHE_LOADED:
            return
        try:
            if _USER_CACHE_FILE.exists():
                data = json.loads(_USER_CACHE_FILE.read_text())
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(k, str) and isinstance(v, str):
                            _USER_CACHE[k] = v
        except Exception:
            pass
        _USER_CACHE_LOADED = True


def _flush_user_cache() -> None:
    """Persist the in-memory cache to disk (best-effort, non-blocking path)."""
    try:
        _USER_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _USER_CACHE_LOCK:
            snapshot = dict(_USER_CACHE)
        _USER_CACHE_FILE.write_text(json.dumps(snapshot))
    except Exception:
        pass


def clear_user_cache() -> None:
    """Clear the module-level user cache (called on workspace/token switch).

    Also wipes user_cache.json on disk so stale entries don't reload on next restart.
    """
    global _USER_CACHE_LOADED
    with _USER_CACHE_LOCK:
        _USER_CACHE.clear()
        _USER_CACHE_LOADED = False
    try:
        _USER_CACHE_FILE.write_text("{}")
    except Exception:
        pass


# ── HITL Draft-Approval Token Registry ───────────────────────────────────────
# /post issues a short-lived single-use confirm_token.
# /send requires that token — backend-enforced HITL with no database needed.
_PENDING_DRAFTS: dict[str, dict] = {}
_PENDING_DRAFTS_LOCK = threading.Lock()
_DRAFT_TTL_SECONDS = 300  # 5-minute window for human to approve


def _issue_draft_token(channel_id: str, message: str, thread_ts: str | None) -> str:
    """Issue a single-use approval token for a drafted Slack message."""
    token = secrets.token_urlsafe(32)
    with _PENDING_DRAFTS_LOCK:
        _PENDING_DRAFTS[token] = {
            "expires": time.time() + _DRAFT_TTL_SECONDS,
            "channel_id": channel_id,
            "message": message,
            "thread_ts": thread_ts,
        }
    return token


def _consume_draft_token(token: str) -> dict | None:
    """Validate and consume a draft token (single-use, TTL-checked)."""
    with _PENDING_DRAFTS_LOCK:
        draft = _PENDING_DRAFTS.pop(token, None)  # pop = single-use
    if draft and draft["expires"] > time.time():
        return draft
    return None


# ── Helpers ─────────────────────────────────────────────────────────────────




def _slack_forward_meta(msg: dict) -> dict | None:
    """Return structured forward metadata if this message is a forwarded message.

    Returns dict with {sender, text, footer} or None if not a forward.
    A message is considered a forward when it has attachments with either
    author_name (bot/app attribution) or is_share=True (native Slack share).
    """
    attachments = msg.get("attachments", [])
    base_text = msg.get("text", "") or ""

    for att in attachments:
        # Detect forward: attachment has author_name OR Slack native share flag
        if att.get("author_name") or att.get("is_share") or att.get("from_url"):
            quoted_text = att.get("text") or att.get("fallback") or ""
            # Don't treat as forward if attachment content is identical to msg.text (unfurl)
            if quoted_text.strip() and quoted_text.strip() != base_text.strip():
                return {
                    "sender": att.get("author_name") or "",
                    "text": quoted_text,
                    "footer": att.get("footer") or "",
                    "pretext": att.get("pretext") or base_text,
                }
    return None


def _slack_extract_text(msg: dict) -> str:
    """Extract displayable text from a Slack message, including forwarded/attachment content.

    Forwarded messages often have text='' or boilerplate text with real content in attachments.
    Always reads attachments and appends non-duplicate content to the base text.
    """
    text = msg.get("text", "") or ""

    # Always read attachments — forwards may have boilerplate text AND attachment content
    attachments = msg.get("attachments", [])
    if attachments:
        att_parts = []
        for att in attachments:
            if att.get("pretext"):
                att_parts.append(att["pretext"])
            if att.get("author_name"):
                att_parts.append(f"*{att['author_name']}*")
            att_text = att.get("text") or att.get("fallback") or ""
            # Avoid duplicating if attachment content is identical to msg.text
            if att_text and att_text.strip() != text.strip():
                att_parts.append(att_text)
            if att.get("footer"):
                att_parts.append(f"_{att['footer']}_")
        if att_parts:
            att_combined = "\n".join(att_parts)
            text = (text + "\n" + att_combined).strip() if text else att_combined

    # blocks: rich_text Block Kit format used by some forwards and bots
    if not text:
        for block in msg.get("blocks", []):
            if block.get("type") == "rich_text":
                for el in block.get("elements", []):
                    for item in el.get("elements", []):
                        if item.get("type") == "text":
                            text += item.get("text", "")

    return text


def _slack_web_api(endpoint: str, params: dict = None, method: str = "GET") -> dict:
    """Call the Slack Web API directly using the stored OAuth token.

    method="GET"  → params sent as query string (default)
    method="POST" → params sent as JSON body (required for chat.postMessage etc.)
    """
    from skills.slack.mcp_client import get_oauth_token
    token = get_oauth_token()
    if not token:
        return {"ok": False, "error": "not_authed"}
    headers = {"Authorization": f"Bearer {token}"}
    if method == "POST":
        data_bytes = json.dumps(params or {}).encode()
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"https://slack.com/api/{endpoint}",
            data=data_bytes, headers=headers, method="POST",
        )
    else:
        qs = urllib.parse.urlencode(params or {})
        url = f"https://slack.com/api/{endpoint}?{qs}" if qs else f"https://slack.com/api/{endpoint}"
        req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _fetch_ext_channels_for_type(ch_type: str, team_id: str) -> list[dict]:
    """Fetch one page-set of ext_shared channels for a single channel type."""
    results = []
    cursor = None
    for _ in range(10):  # max 10 pages per type
        params: dict = {
            "types": ch_type,
            "limit": 200,
            "exclude_archived": "true",
        }
        if team_id:
            params["team_id"] = team_id
        if cursor:
            params["cursor"] = cursor
        data = _slack_web_api("conversations.list", params)
        if not data.get("ok"):
            break
        for ch in data.get("channels", []):
            if not ch.get("is_ext_shared"):
                continue
            results.append({
                "channel_name": ch.get("name", ""),
                "channel_id": ch.get("id", ""),
                "purpose": ch.get("purpose", {}).get("value", "") if isinstance(ch.get("purpose"), dict) else "",
                "topic": ch.get("topic", {}).get("value", "") if isinstance(ch.get("topic"), dict) else "",
                "type": "external_shared",
            })
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return results


def _fetch_external_channels() -> list[dict]:
    """Fetch Slack Connect (ext_shared / is_ext_shared) channels via conversations.list.

    Runs private_channel and public_channel fetches concurrently via threads
    so both page-sets are in flight simultaneously. The actual is_ext_shared
    filtering is done in _fetch_ext_channels_for_type.
    """
    from skills.slack.mcp_client import _load_token
    stored = _load_token()
    team_id = stored.get("team_id", "")

    results_private: list[dict] = []
    results_public: list[dict] = []
    errors = []

    def _fetch(ch_type: str, out: list) -> None:
        try:
            out.extend(_fetch_ext_channels_for_type(ch_type, team_id))
        except Exception as e:
            errors.append(e)

    t_private = threading.Thread(target=_fetch, args=("private_channel", results_private))
    t_public  = threading.Thread(target=_fetch, args=("public_channel",  results_public))
    t_private.start()
    t_public.start()
    t_private.join()
    t_public.join()

    return results_private + results_public




# ── Pydantic models ────────────────────────────────────────────────────────


class SlackReactionRequest(BaseModel):
    channel_id: str
    timestamp: str
    name: str  # emoji name without colons


class SlackPostRequest(BaseModel):
    message: str
    thread_ts: str | None = None
    confirm_token: str | None = None  # required by /send; issued by /post


# ── Auth routes ─────────────────────────────────────────────────────────────




@router.get("/api/auth/slack/status")
async def slack_token_status():
    """Check Slack OAuth token status with live connectivity verification."""
    from skills.slack.mcp_client import get_slack_auth_status, get_oauth_token
    base = get_slack_auth_status()
    if not base.get("configured"):
        return base
    loop = asyncio.get_running_loop()
    token = await loop.run_in_executor(None, get_oauth_token)
    if not token:
        return {**base, "configured": False, "error": "no_token"}
    result = await loop.run_in_executor(None, _slack_web_api, "auth.test", {})
    if not result.get("ok"):
        return {**base, "configured": False, "error": result.get("error", "auth_failed")}
    return base


@router.get("/api/auth/slack/start")
async def slack_oauth_start():
    """Start Slack OAuth flow — spins up temp callback server on port 3118."""
    from skills.slack.mcp_client import start_oauth
    return start_oauth()


# ── Slack Third Pane API ────────────────────────────────────────────────────


def _fetch_channels_for_type(ch_type: str, team_id: str) -> list[dict]:
    """Fetch all non-ext_shared channels of one type via conversations.list (sync, for executor)."""
    results = []
    cursor = None
    for _ in range(5):  # max 5 pages
        params: dict = {"types": ch_type, "limit": 200, "exclude_archived": "true"}
        if team_id:
            params["team_id"] = team_id
        if cursor:
            params["cursor"] = cursor
        data = _slack_web_api("conversations.list", params)
        if not data.get("ok"):
            print(f"[SLACK] conversations.list error ({ch_type}): {data.get('error')}")
            break
        for ch in data.get("channels", []):
            if ch.get("is_ext_shared"):
                continue  # handled by _fetch_external_channels
            results.append({
                "channel_name": ch.get("name", ""),
                "channel_id": ch.get("id", ""),
                "purpose": ch.get("purpose", {}).get("value", "") if isinstance(ch.get("purpose"), dict) else "",
                "topic": ch.get("topic", {}).get("value", "") if isinstance(ch.get("topic"), dict) else "",
                "type": ch_type,
            })
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return results


@router.get("/api/slack/channels")
async def slack_channels():
    """List Slack channels — public, private, and ext_shared fetched concurrently."""
    loop = asyncio.get_running_loop()
    from skills.slack.mcp_client import _load_token
    stored = await loop.run_in_executor(None, _load_token)
    team_id = stored.get("team_id", "")

    # Fetch public, private, and ext_shared channels concurrently
    public_fut = loop.run_in_executor(None, _fetch_channels_for_type, "public_channel", team_id)
    private_fut = loop.run_in_executor(None, _fetch_channels_for_type, "private_channel", team_id)
    external_fut = loop.run_in_executor(None, _fetch_external_channels)

    public_chs, private_chs, external_chs = await asyncio.gather(
        public_fut, private_fut, external_fut, return_exceptions=True
    )

    channels = []
    for result in (public_chs, private_chs):
        if isinstance(result, list):
            channels.extend(result)

    existing_ids = {c["channel_id"] for c in channels}
    if isinstance(external_chs, list):
        channels.extend(c for c in external_chs if c["channel_id"] not in existing_ids)

    return {"channels": channels}


@router.get("/api/slack/channels/{channel_id}/info")
async def slack_channel_info(channel_id: str):
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _slack_web_api, "conversations.info", {"channel": channel_id})
    if not data.get("ok"):
        print(f"[SLACK] conversations.info error: {data.get('error')}")
        return {"channel_id": channel_id}
    ch = data.get("channel", {})
    return {
        "channel_id": ch.get("id", channel_id),
        "channel_name": ch.get("name", ""),
        "purpose": ch.get("purpose", {}).get("value", "") if isinstance(ch.get("purpose"), dict) else "",
        "topic": ch.get("topic", {}).get("value", "") if isinstance(ch.get("topic"), dict) else "",
        "type": "private_channel" if ch.get("is_private") else "public_channel",
    }


def _slack_search_messages(query: str, limit: int = 20) -> dict:
    """Call search.messages Web API. Returns normalized dict with 'threads' list."""
    params: dict = {"query": query, "count": min(limit, 100)}
    data = _slack_web_api("search.messages", params)
    if not data.get("ok"):
        err = data.get("error", "unknown")
        if "missing_scope" in err:
            return {"ok": False, "error": "missing_scope:search:read — re-authenticate to grant search access", "messages": []}
        return {"ok": False, "error": err, "messages": []}
    msg_block = data.get("messages", {})
    matches = msg_block.get("matches", [])
    next_cursor = msg_block.get("pagination", {}).get("next_cursor", "")
    results = []
    for m in matches:
        ch = m.get("channel", {})
        ts = m.get("ts", "")
        results.append({
            "thread_id": ts,
            "message_ts": ts,
            "channel_id": ch.get("id", ""),
            "channel_name": ch.get("name", ""),
            "parent_user": m.get("username", m.get("user", "")),
            "parent_user_name": m.get("username", m.get("user", "")),
            "thread_date": "",
            "text": (m.get("text") or "")[:300],
            "summary": (m.get("text") or "")[:300],
            "reply_count": 0,
            "thread_ts": m.get("thread_ts", ts),
            "permalink": m.get("permalink", ""),
        })
    return {"ok": True, "messages": results, "cursor": next_cursor}


@router.get("/api/slack/channels/{channel_id}/threads")
async def slack_channel_threads(channel_id: str, limit: int = 30, q: str = "",
                                 start: str = None, end: str = None):
    """Third-pane thread listing via search.messages Web API (clean JSON, no MCP)."""
    query = f"in:<#{channel_id}> {q}".strip() if q else f"in:<#{channel_id}>"
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _slack_search_messages, query, min(limit, 20))
    if not result.get("ok"):
        print(f"[SLACK] threads error: {result.get('error')}")
        return {"threads": [], "error": result.get("error")}
    return {"threads": result["messages"]}


def _resolve_uid_sync(uid: str, team_id: str) -> tuple[str, str | None]:
    """Resolve a Slack UID to a display name synchronously.

    Returns (uid, name_or_None). None means the lookup failed and the result
    must NOT be cached (so it can be retried on the next request).
    """
    _ensure_user_cache_loaded()
    with _USER_CACHE_LOCK:
        if uid in _USER_CACHE:
            return uid, _USER_CACHE[uid]
    params: dict = {"user": uid}
    if team_id:
        params["team_id"] = team_id
    data = _slack_web_api("users.info", params)
    if not data.get("ok") and team_id:
        # External/guest users live on a different workspace; retry without team_id.
        print(f"[SLACK] users.info with team_id failed for {uid}: {data.get('error')} — retrying without team_id")
        data = _slack_web_api("users.info", {"user": uid})
    if not data.get("ok"):
        # Last resort: bulk-fetch users.list once to populate cache for all internal users.
        # This handles users where users.info returns user_not_found due to workspace restrictions.
        global _USERS_LIST_FETCHED
        with _USER_CACHE_LOCK:
            already = _USERS_LIST_FETCHED
        if not already:
            # Paginate through all users (AMD workspace has >200)
            cursor = None
            for _ in range(10):  # max 10 pages = 2000 users
                params: dict = {"limit": 200, **({"team_id": team_id} if team_id else {})}
                if cursor:
                    params["cursor"] = cursor
                list_data = _slack_web_api("users.list", params)
                if not list_data.get("ok"):
                    break
                with _USER_CACHE_LOCK:
                    for member in list_data.get("members", []):
                        mid = member.get("id", "")
                        if mid and mid not in _USER_CACHE:
                            p = member.get("profile", {})
                            n = p.get("real_name") or p.get("display_name") or ""
                            if n:
                                _USER_CACHE[mid] = n
                cursor = list_data.get("response_metadata", {}).get("next_cursor", "")
                if not cursor:
                    break
            with _USER_CACHE_LOCK:
                _USERS_LIST_FETCHED = True
        # Now check cache again
        with _USER_CACHE_LOCK:
            if uid in _USER_CACHE:
                return uid, _USER_CACHE[uid]
    if data.get("ok"):
        p = data.get("user", {}).get("profile", {})
        # Store raw — the frontend _slackMrkdwn calls _slackEsc() before innerHTML,
        # so pre-escaping here would cause double-encoding (&amp; visible to users).
        name = p.get("real_name") or p.get("display_name") or f"User·{uid[-4:]}"
        with _USER_CACHE_LOCK:
            _USER_CACHE[uid] = name
        return uid, name
    # Do NOT cache failures — let them be retried on the next request
    return uid, None


async def _resolve_uids_batch(uids: set[str], team_id: str, loop: asyncio.AbstractEventLoop) -> dict[str, str]:
    """Resolve a set of UIDs concurrently. Returns uid -> display_name mapping.

    UIDs that fail resolution map to themselves (fallback), but are not written
    to the module-level cache.
    """
    _ensure_user_cache_loaded()
    with _USER_CACHE_LOCK:
        unknown = {u for u in uids if u not in _USER_CACHE}

    if unknown:
        tasks = [
            loop.run_in_executor(None, _resolve_uid_sync, uid, team_id)
            for uid in unknown
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        cache_updated = False
        for res in results:
            if isinstance(res, Exception):
                continue
            uid, name = res
            if name is not None:
                cache_updated = True

        if cache_updated:
            asyncio.ensure_future(loop.run_in_executor(None, _flush_user_cache))

    with _USER_CACHE_LOCK:
        return {uid: _USER_CACHE.get(uid, f"User·{uid[-4:]}") for uid in uids}


@router.get("/api/slack/channels/{channel_id}/messages")
async def slack_channel_messages(channel_id: str, limit: int = 50, oldest: str = None, latest: str = None, cursor: str = None):
    """Read channel messages via conversations.history Web API for reliable user attribution."""
    import datetime

    loop = asyncio.get_running_loop()
    from skills.slack.mcp_client import get_oauth_token, _load_token

    token, stored = await asyncio.gather(
        loop.run_in_executor(None, get_oauth_token),
        loop.run_in_executor(None, _load_token),
    )
    if not token:
        raise HTTPException(status_code=401, detail="Slack not authenticated")

    team_id = stored.get("team_id", "")

    params: dict = {"channel": channel_id, "limit": min(limit, 200)}
    if team_id:
        params["team_id"] = team_id
    if oldest:
        params["oldest"] = oldest
    if latest:
        params["latest"] = latest
    if cursor:
        params["cursor"] = cursor

    data = await loop.run_in_executor(None, _slack_web_api, "conversations.history", params)
    if not data.get("ok"):
        err = data.get("error", "unknown")
        print(f"[SLACK] conversations.history error: {err}")
        raise HTTPException(status_code=503, detail=f"Slack API error: {err}")

    raw_messages = data.get("messages", [])
    next_cursor = data.get("response_metadata", {}).get("next_cursor")

    # Collect all UIDs (message senders + mention targets) for batch resolution
    all_uids: set[str] = set()
    for msg in raw_messages:
        uid = msg.get("user", msg.get("bot_id", ""))
        if uid:
            all_uids.add(uid)
        for m_uid in re.findall(r'<@(\w+)>', _slack_extract_text(msg)):
            all_uids.add(m_uid)

    name_map = await _resolve_uids_batch(all_uids, team_id, loop)

    messages = []
    for msg in reversed(raw_messages):
        subtype = msg.get("subtype", "")
        if subtype in ("channel_join", "channel_leave") and not _slack_extract_text(msg):
            continue
        if subtype == "bot_message" and not _slack_extract_text(msg):
            continue

        uid = msg.get("user", msg.get("bot_id", ""))
        user_name = name_map.get(uid, uid) if uid else "Member"

        ts = msg.get("ts", "")
        try:
            timestamp = datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            timestamp = ts

        authed_uid = stored.get("user", "")
        reactions = [
            {
                "name": r["name"],
                "count": r["count"],
                "self_reacted": authed_uid in r.get("users", []),
            }
            for r in msg.get("reactions", [])
        ]

        reply_count = msg.get("reply_count", 0)
        latest_reply_ts = msg.get("latest_reply", "")
        try:
            latest_reply = datetime.datetime.fromtimestamp(float(latest_reply_ts)).strftime("%Y-%m-%d %H:%M") if latest_reply_ts else ""
        except Exception:
            latest_reply = latest_reply_ts

        fwd = _slack_forward_meta(msg)
        text = _slack_extract_text(msg) if not fwd else (msg.get("text", "") or "")
        for m_uid in set(re.findall(r'<@(\w+)>', text)):
            # Keep <@UID|Name> so frontend _slackMrkdwn renders it as a styled chip
            resolved = name_map.get(m_uid, f"User·{m_uid[-4:]}")
            text = text.replace(f"<@{m_uid}>", f"<@{m_uid}|{resolved}>")

        msg_obj: dict = {
            "user": user_name,
            "user_id": uid,
            "text": text,
            "ts": ts,
            "timestamp": timestamp,
            "reply_count": reply_count,
            "latest_reply": latest_reply,
            "reactions": reactions,
        }
        if fwd:
            msg_obj["forward"] = fwd
        messages.append(msg_obj)

    return {"messages": messages, "cursor": next_cursor or None}


@router.post("/api/slack/resolve-members")
async def slack_resolve_members(request: Request):
    """Resolve 'Member' entries by UID via users.info — MCP search removed."""
    body = await request.json()
    channel_id = body.get("channel_id", "")
    timestamps = body.get("timestamps", [])
    if not channel_id or not timestamps:
        return {"resolved": {}}
    # Without MCP search-by-timestamp, cannot resolve UIDs from "Member" placeholders.
    # Frontend falls back to showing "Member" which is acceptable.
    return {"resolved": {}}


@router.get("/api/slack/dms")
async def slack_dms():
    """Discover DM conversations via conversations.list?types=im,mpim (no MCP, clean JSON)."""
    from skills.slack.mcp_client import _load_token

    loop = asyncio.get_running_loop()
    stored = await loop.run_in_executor(None, _load_token)
    authed_user_id = stored.get("user", "")
    authed_user_name = stored.get("user_display_name", "")
    team_id = stored.get("team_id", "")

    # If the stored token has no user ID, call auth.test to get it
    if not authed_user_id:
        auth_result = await loop.run_in_executor(None, _slack_web_api, "auth.test", {})
        if auth_result.get("ok"):
            authed_user_id = auth_result.get("user_id", "")
            if not authed_user_name:
                authed_user_name = auth_result.get("user", "")

    # Resolve your own name so it shows correctly in group DM lists
    if authed_user_id and authed_user_id not in _USER_CACHE:
        _resolve_uid_sync(authed_user_id, team_id)
    if authed_user_id and not authed_user_name:
        authed_user_name = _USER_CACHE.get(authed_user_id, "")

    def _is_me(p: dict) -> bool:
        if authed_user_id and p.get("id") == authed_user_id:
            return True
        if authed_user_name and p.get("name") == authed_user_name:
            return True
        return False

    # Fetch all IM and MPIM channels
    params: dict = {"types": "im,mpim", "limit": 50, "exclude_archived": "true"}
    if team_id:
        params["team_id"] = team_id
    data = await loop.run_in_executor(None, _slack_web_api, "conversations.list", params)
    if not data.get("ok"):
        return {"dms": [], "error": data.get("error", "unknown")}

    channels = data.get("channels", [])

    # Fetch all channel histories concurrently (not sequentially)
    async def _fetch_hist(ch: dict) -> tuple[dict, dict]:
        chan_id = ch.get("id", "")
        hist_p: dict = {"channel": chan_id, "limit": 1}
        if team_id:
            hist_p["team_id"] = team_id
        hist = await loop.run_in_executor(None, _slack_web_api, "conversations.history", hist_p)
        return ch, hist

    hist_results = await asyncio.gather(*[_fetch_hist(ch) for ch in channels], return_exceptions=True)

    # Collect UIDs to resolve that aren't already cached
    valid_results = [(ch, hist) for item in hist_results
                     if not isinstance(item, Exception)
                     for ch, hist in [item]]
    unknown_uids = {ch.get("user", "") for ch, _ in valid_results
                    if ch.get("user") and ch.get("user") not in _USER_CACHE}

    # Resolve all unknown UIDs concurrently
    if unknown_uids:
        def _resolve_uid(uid: str) -> tuple[str, str]:
            u_data = _slack_web_api("users.info", {"user": uid})
            if u_data.get("ok"):
                p = u_data.get("user", {}).get("profile", {})
                return uid, p.get("real_name") or p.get("display_name") or uid
            return uid, uid

        uid_results = await asyncio.gather(
            *[loop.run_in_executor(None, _resolve_uid, uid) for uid in unknown_uids],
            return_exceptions=True,
        )
        with _USER_CACHE_LOCK:
            for r in uid_results:
                if not isinstance(r, Exception):
                    _USER_CACHE[r[0]] = r[1]

    dms = []
    for ch, hist in valid_results:
        chan_id = ch.get("id", "")
        is_mpim = ch.get("is_mpim", False)
        last_msgs = hist.get("messages", []) if hist.get("ok") else []
        last_msg = last_msgs[0] if last_msgs else {}

        other_uid = ch.get("user", "")
        participants = []

        if is_mpim:
            # MPIM channels don't have a single "user" field — fetch all members
            try:
                members_data = await loop.run_in_executor(
                    None, _slack_web_api, "conversations.members",
                    {"channel": chan_id, "limit": 20}
                )
                member_ids = members_data.get("members", []) if members_data.get("ok") else []
                for mid in member_ids:
                    if mid == authed_user_id:
                        continue  # skip self
                    m_name = _USER_CACHE.get(mid)
                    if not m_name:
                        _, m_name = await loop.run_in_executor(None, _resolve_uid_sync, mid, team_id)
                        if not m_name:
                            m_name = f"User·{mid[-4:]}"
                    participants.append({"name": m_name, "id": mid})
            except Exception:
                pass  # fall back to channel ID display name
        elif other_uid and other_uid != authed_user_id:
            if other_uid not in _USER_CACHE:
                u_data = await loop.run_in_executor(None, _slack_web_api, "users.info", {"user": other_uid})
                if u_data.get("ok"):
                    p = u_data.get("user", {}).get("profile", {})
                    resolved = p.get("real_name") or p.get("display_name") or other_uid
                    with _USER_CACHE_LOCK:
                        _USER_CACHE[other_uid] = resolved
            other_name = _USER_CACHE.get(other_uid, other_uid)
            participants = [{"name": other_name, "id": other_uid}]

        other = [p for p in participants if not _is_me(p)]
        if is_mpim:
            names = [p["name"] for p in other[:3]]
            display_name = ", ".join(names) if names else chan_id
            if len(other) > 3:
                display_name += f" +{len(other) - 3}"
        else:
            display_name = other[0]["name"] if other else chan_id

        ts = last_msg.get("ts", "")
        preview = last_msg.get("text") or ""
        for m_uid in set(re.findall(r'<@(\w+)>', preview)):
            resolved = _USER_CACHE.get(m_uid, f"User·{m_uid[-4:]}")
            preview = preview.replace(f"<@{m_uid}>", f"@{resolved}")
        dms.append({
            "channel_id": chan_id,
            "display_name": display_name,
            "participants": participants,
            "last_message": preview[:100],
            "last_ts": ts,
            "timestamp": ts,
            "type": "mpim" if is_mpim else "im",
        })

    dms.sort(key=lambda d: d["last_ts"], reverse=True)
    return {"dms": dms}


@router.get("/api/slack/search")
async def slack_search(q: str = "", after: str = None, before: str = None, limit: int = 20):
    """Global Slack message search via search.messages Web API."""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _slack_search_messages, q or "*", limit)
    return result


@router.post("/api/slack/react")
async def slack_add_reaction(req: SlackReactionRequest):
    """Add a reaction to a Slack message using the Slack Web API directly."""
    import urllib.parse, urllib.request, urllib.error
    from skills.slack.mcp_client import get_oauth_token
    token = get_oauth_token()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated with Slack")
    try:
        data = urllib.parse.urlencode({
            "channel": req.channel_id,
            "timestamp": req.timestamp,
            "name": req.name,
        }).encode()
        api_req = urllib.request.Request(
            "https://slack.com/api/reactions.add",
            data=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(api_req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("ok"):
            return {"ok": True}
        return {"ok": False, "error": result.get("error", "unknown")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/slack/unreact")
async def slack_remove_reaction(req: SlackReactionRequest):
    """Remove a reaction from a Slack message using the Slack Web API directly."""
    import urllib.parse, urllib.request, urllib.error
    from skills.slack.mcp_client import get_oauth_token
    token = get_oauth_token()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated with Slack")
    try:
        data = urllib.parse.urlencode({
            "channel": req.channel_id,
            "timestamp": req.timestamp,
            "name": req.name,
        }).encode()
        api_req = urllib.request.Request(
            "https://slack.com/api/reactions.remove",
            data=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(api_req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("ok"):
            return {"ok": True}
        return {"ok": False, "error": result.get("error", "unknown")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/slack/threads/{channel_id}/{message_ts}")
async def slack_thread_detail(channel_id: str, message_ts: str, limit: int = 50):
    """Read a thread via conversations.replies Web API for reliable user attribution."""
    import datetime

    loop = asyncio.get_running_loop()
    from skills.slack.mcp_client import get_oauth_token, _load_token

    token, stored = await asyncio.gather(
        loop.run_in_executor(None, get_oauth_token),
        loop.run_in_executor(None, _load_token),
    )
    if not token:
        raise HTTPException(status_code=401, detail="Slack not authenticated")

    team_id = stored.get("team_id", "")

    params: dict = {"channel": channel_id, "ts": message_ts, "limit": min(limit, 200)}
    if team_id:
        params["team_id"] = team_id

    data = await loop.run_in_executor(None, _slack_web_api, "conversations.replies", params)
    if not data.get("ok"):
        err = data.get("error", "unknown")
        print(f"[SLACK] conversations.replies error: {err}")
        raise HTTPException(status_code=503, detail=f"Slack API error: {err}")

    raw_messages = data.get("messages", [])

    all_uids: set[str] = set()
    for msg in raw_messages:
        uid = msg.get("user", msg.get("bot_id", ""))
        if uid:
            all_uids.add(uid)
        for m_uid in re.findall(r'<@(\w+)>', _slack_extract_text(msg)):
            all_uids.add(m_uid)

    name_map = await _resolve_uids_batch(all_uids, team_id, loop)

    def _fmt_ts(ts: str) -> str:
        try:
            return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ts

    def _clean_text(msg_or_text) -> str:
        text = _slack_extract_text(msg_or_text) if isinstance(msg_or_text, dict) else (msg_or_text or "")
        for uid in set(re.findall(r'<@(\w+)>', text)):
            resolved = name_map.get(uid, f"User·{uid[-4:]}")
            text = text.replace(f"<@{uid}>", f"<@{uid}|{resolved}>")
        return text

    messages = []
    # conversations.replies already returns oldest-first (parent at [0], replies ascending)
    for msg in raw_messages:
        uid = msg.get("user", msg.get("bot_id", ""))
        user_name = name_map.get(uid, uid) if uid else "Member"
        ts = msg.get("ts", "")
        authed_uid = stored.get("user", "")
        reactions = [
            {
                "name": r["name"],
                "count": r["count"],
                "self_reacted": authed_uid in r.get("users", []),
            }
            for r in msg.get("reactions", [])
        ]
        fwd = _slack_forward_meta(msg)
        thread_msg: dict = {
            "user": user_name,
            "user_id": uid,
            "text": _clean_text(msg) if not fwd else (msg.get("text", "") or ""),
            "timestamp": _fmt_ts(ts),
            "ts": ts,
            "reactions": reactions,
        }
        if fwd:
            thread_msg["forward"] = fwd
        messages.append(thread_msg)

    parent = messages[0] if messages else {}
    return {
        "thread_id": message_ts,
        "channel_id": channel_id,
        "parent_user": parent.get("user", ""),
        "parent_text": parent.get("text", ""),
        "parent_timestamp": parent.get("timestamp", ""),
        "thread_date": parent.get("timestamp", ""),
        "messages": messages,
        "reply_count": max(len(messages) - 1, 0),
    }


@router.post("/api/slack/channels/{channel_id}/post")
async def slack_post_message(channel_id: str, req: SlackPostRequest):
    """Issue a draft and a single-use confirm_token — never auto-sends per CLAUDE.md."""
    token = _issue_draft_token(channel_id, req.message, req.thread_ts)
    draft: dict = {
        "draft": True,
        "channel_id": channel_id,
        "message": req.message,
        "confirm_token": token,
    }
    if req.thread_ts:
        draft["thread_ts"] = req.thread_ts
    return draft


@router.post("/api/slack/channels/{channel_id}/send")
async def slack_send_message_confirmed(channel_id: str, req: SlackPostRequest):
    """Confirmed send — validates the single-use confirm_token before dispatching."""
    draft = _consume_draft_token(req.confirm_token or "")
    if not draft:
        raise HTTPException(status_code=403, detail="Invalid or expired confirm_token — re-draft the message.")
    # Use channel_id from the token (bound at draft-issue time, not overridable via URL).
    payload: dict = {"channel": draft["channel_id"], "text": draft["message"]}
    if draft.get("thread_ts"):
        payload["thread_ts"] = draft["thread_ts"]
    data = _slack_web_api("chat.postMessage", payload, method="POST")
    if not data.get("ok"):
        raise HTTPException(status_code=503, detail=f"Slack error: {data.get('error', 'unknown')}")
    return {"ok": True, "ts": data.get("ts")}


@router.get("/api/slack/users/{query}")
async def slack_user_lookup(query: str):
    """Look up a Slack user by name/email.

    Strategy (in order):
    1. If query looks like an email, use users.lookupByEmail (fast, exact).
    2. Search _USER_CACHE (populated from conversations.history calls) — covers
       people the user has already interacted with.
    3. Fetch one page of users.list with team_id as a last resort for a broader search.
    """
    loop = asyncio.get_running_loop()
    from skills.slack.mcp_client import _load_token
    stored = await loop.run_in_executor(None, _load_token)
    team_id = stored.get("team_id", "")
    ql = query.lower()

    def _make_user_result(uid: str, data: dict) -> dict:
        profile = data.get("profile", {})
        return {
            "user": {
                "id": uid,
                "display_name": profile.get("real_name") or profile.get("display_name", ""),
                "real_name": profile.get("real_name", ""),
                "email": profile.get("email", ""),
                "title": profile.get("title", ""),
                "username": data.get("name", ""),
                "user_id": uid,
            }
        }

    # Strategy 1: email lookup (exact, fast)
    if "@" in query:
        data = await loop.run_in_executor(None, _slack_web_api, "users.lookupByEmail", {"email": query})
        if data.get("ok"):
            return _make_user_result(data["user"]["id"], data["user"])

    results: list[dict] = []

    # Strategy 2: search _USER_CACHE (UIDs → display names from prior history/DM loads)
    with _USER_CACHE_LOCK:
        cache_snapshot = dict(_USER_CACHE)
    cache_uid_tasks = [
        loop.run_in_executor(None, _slack_web_api, "users.info", {"user": uid})
        for uid, name in cache_snapshot.items()
        if ql in name.lower()
    ]
    if cache_uid_tasks:
        infos = await asyncio.gather(*cache_uid_tasks, return_exceptions=True)
        for info in infos:
            if not isinstance(info, Exception) and info.get("ok"):
                u = info["user"]
                results.append(_make_user_result(u["id"], u)["user"])

    # Strategy 3: one page of users.list (internal workspace members)
    params: dict = {"limit": 200}
    if team_id:
        params["team_id"] = team_id
    data = await loop.run_in_executor(None, _slack_web_api, "users.list", params)
    seen_ids = {r["id"] for r in results}
    if data.get("ok"):
        for member in data.get("members", []):
            if member.get("deleted") or member.get("is_bot"):
                continue
            if member["id"] in seen_ids:
                continue
            profile = member.get("profile", {})
            display = (profile.get("real_name") or profile.get("display_name") or "").lower()
            email_val = (profile.get("email") or "").lower()
            handle = (member.get("name") or "").lower()
            if ql in display or ql in email_val or ql in handle:
                results.append(_make_user_result(member["id"], member)["user"])
                seen_ids.add(member["id"])

    if results:
        return {"users": results}
    return {"user": None, "error": "not_found"}


@router.post("/api/slack/dm")
async def slack_send_dm(req: Request):
    """Issue a draft DM and a single-use confirm_token — never auto-sends per CLAUDE.md."""
    body = await req.json()
    # JS sends user_identifier; accept user_id / channel_id as fallbacks for compatibility
    channel_id = body.get("user_identifier", body.get("user_id", body.get("channel_id", "")))
    message = body.get("message", "")
    token = _issue_draft_token(channel_id, message, None)
    return {
        "draft": True,
        "channel_id": channel_id,
        "message": message,
        "confirm_token": token,
    }


@router.post("/api/slack/dm/send")
async def slack_send_dm_confirmed(req: Request):
    """Confirmed DM send — validates the single-use confirm_token before dispatching."""
    body = await req.json()
    draft = _consume_draft_token(body.get("confirm_token", ""))
    if not draft:
        raise HTTPException(status_code=403, detail="Invalid or expired confirm_token — re-draft the message.")
    data = _slack_web_api("chat.postMessage", {"channel": draft["channel_id"], "text": draft["message"]}, method="POST")
    if not data.get("ok"):
        raise HTTPException(status_code=503, detail=f"Slack error: {data.get('error', 'unknown')}")
    return {"ok": True, "ts": data.get("ts")}
