"""Slack route group — channels, DMs, threads, search, reactions, auth."""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import shared

router = APIRouter()

# ── Helpers ─────────────────────────────────────────────────────────────────


def _slack_auth_test(token: str, cookie: str = "") -> dict:
    """Call Slack auth.test with token and optional xoxd- cookie."""
    import urllib.request as _req2
    headers: dict = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if cookie:
        headers["Cookie"] = f"d={cookie}"
    r = _req2.Request(
        "https://slack.com/api/auth.test",
        data=urllib.parse.urlencode({"token": token}).encode(),
        headers=headers,
        method="POST",
    )
    with _req2.urlopen(r, timeout=15) as resp:
        return json.loads(resp.read())


def _slack_web_api(endpoint: str, params: dict = None) -> dict:
    """Call the Slack Web API directly using the stored OAuth token."""
    from skills.slack.mcp_client import get_oauth_token
    token = get_oauth_token()
    if not token:
        return {"ok": False, "error": "not_authed"}
    qs = urllib.parse.urlencode(params or {})
    url = f"https://slack.com/api/{endpoint}?{qs}" if qs else f"https://slack.com/api/{endpoint}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _fetch_external_channels() -> list[dict]:
    """Fetch Slack Connect (ext_shared) channels via conversations.list.

    The Slack API returns Slack Connect channels as private_channel with
    is_ext_shared=True. The MCP search tool only sees public/private channels
    but not ext_shared ones, so we call the Web API directly here.
    """
    from skills.slack.mcp_client import _load_token
    stored = _load_token()
    team_id = stored.get("team_id", "")

    results = []
    for ch_type in ("private_channel", "public_channel"):
        cursor = None
        for _ in range(10):  # max 10 pages per type
            params = {
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


def _slack_mcp_call(tool: str, args: dict = None) -> dict:
    """Call a Slack MCP tool, parse JSON result, handle errors."""
    from skills.slack.mcp_client import get_slack_mcp, _UNREACHABLE_MSG
    try:
        mcp = get_slack_mcp()
        text = mcp.call(tool, args or {})
        if text == _UNREACHABLE_MSG:
            raise HTTPException(status_code=503, detail=text)
        # Check for MCP execution errors
        if text and text.startswith("execution_failed:"):
            error_msg = text.split(":", 1)[1].strip().split("\n")[0]
            raise HTTPException(status_code=400, detail=error_msg)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            # MCP may return multiple JSON blocks separated by newlines — try each line
            for line in (text or "").strip().splitlines():
                line = line.strip()
                if line.startswith("{") or line.startswith("["):
                    try:
                        return json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        continue
            return {"raw": text}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Pydantic models ────────────────────────────────────────────────────────


class SlackTokenRequest(BaseModel):
    token: str
    cookie: str = ""


class SlackReactionRequest(BaseModel):
    channel_id: str
    timestamp: str
    name: str  # emoji name without colons


class SlackPostRequest(BaseModel):
    message: str
    thread_ts: str | None = None


# ── Auth routes ─────────────────────────────────────────────────────────────


@router.post("/api/auth/slack")
async def save_slack_token(req: SlackTokenRequest):
    import os as _os
    from pathlib import Path as _Path
    token = req.token.strip().strip('"').strip("'")
    cookie = req.cookie.strip().strip('"').strip("'")
    try:
        result = _slack_auth_test(token, cookie)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not result.get("ok"):
        raise HTTPException(status_code=401, detail=f"Slack rejected token: {result.get('error')}")
    slack_token_file = _Path.home() / ".config" / "slack" / "token.json"
    slack_token_file.parent.mkdir(parents=True, exist_ok=True)
    slack_token_file.write_text(json.dumps({"token": token, "cookie": cookie}, indent=2))
    _os.chmod(str(slack_token_file), 0o600)
    return {
        "ok": True,
        "user": result.get("user"),
        "user_id": result.get("user_id"),
        "team": result.get("team"),
        "team_id": result.get("team_id"),
    }


@router.post("/api/auth/slack/capture")
async def slack_token_capture():
    """Auto-capture Slack xoxc- token and xoxd- cookie via CDP/Edge."""
    import asyncio as _asyncio, os as _os
    from pathlib import Path as _Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from capture_slack_token import capture_slack_token

    import logging as _logging
    _log = _logging.getLogger("slack_capture")

    def _capture_with_log():
        return capture_slack_token(status_cb=lambda m: _log.info("[Slack capture] %s", m))

    loop = _asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _capture_with_log)

    if not result:
        raise HTTPException(
            status_code=504,
            detail="Could not capture Slack token — navigate to your Slack workspace in the Edge window and wait for it to fully load."
        )

    xoxc_token, xoxd_cookie = result

    try:
        auth = _slack_auth_test(xoxc_token, xoxd_cookie)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token captured but validation failed: {e}")
    if not auth.get("ok"):
        raise HTTPException(status_code=401, detail=f"Token captured but Slack rejected it: {auth.get('error')}")

    slack_token_file = _Path.home() / ".config" / "slack" / "token.json"
    slack_token_file.parent.mkdir(parents=True, exist_ok=True)
    slack_token_file.write_text(json.dumps({"token": xoxc_token, "cookie": xoxd_cookie}, indent=2))
    _os.chmod(str(slack_token_file), 0o600)

    return {
        "ok": True,
        "user": auth.get("user"),
        "team": auth.get("team"),
        "has_cookie": bool(xoxd_cookie),
    }


@router.get("/api/auth/slack/status")
async def slack_token_status():
    """Check Slack OAuth token status with live connectivity verification."""
    import asyncio
    from skills.slack.mcp_client import get_slack_auth_status, get_oauth_token, get_slack_mcp, _UNREACHABLE_MSG
    base = get_slack_auth_status()
    if not base.get("configured"):
        return base
    # Verify token is valid via direct Slack API
    try:
        token = get_oauth_token()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _slack_auth_test, token)
        if not result.get("ok"):
            return {**base, "configured": False, "error": result.get("error", "auth_failed")}
    except Exception as e:
        return {**base, "configured": False, "error": str(e)}
    # Verify MCP server is reachable (token valid ≠ MCP reachable)
    try:
        mcp = get_slack_mcp()
        text = await loop.run_in_executor(None, mcp.call, "slack_search_channels", {"query": "", "limit": 1})
        if text == _UNREACHABLE_MSG:
            return {**base, "configured": False, "error": "Slack MCP server unreachable"}
    except Exception as e:
        return {**base, "configured": False, "error": str(e)}
    return base


@router.get("/api/auth/slack/start")
async def slack_oauth_start():
    """Start Slack OAuth flow — spins up temp callback server on port 3118."""
    from skills.slack.mcp_client import start_oauth
    return start_oauth()


# ── Slack Third Pane API ────────────────────────────────────────────────────


@router.get("/api/slack/channels")
async def slack_channels():
    """List Slack channels — parses MCP text response into structured objects."""
    import re as _re
    try:
        data = _slack_mcp_call("slack_search_channels", {
            "query": "", "limit": 100,
            "channel_types": "public_channel,private_channel",
        })
        raw = data.get("results", data.get("raw", "")) if isinstance(data, dict) else str(data)
        channels = []
        # Parse markdown blocks separated by ---
        for block in _re.split(r'\n---\n', raw):
            name_m = _re.search(r'Name:\s*#?([\w-]+)', block)
            if not name_m:
                continue
            # Extract channel ID from permalink URL (e.g. /archives/C013ZD9AZ9T)
            id_m = _re.search(r'/archives/(\w+)', block)
            purpose_m = _re.search(r'Purpose:\s*(.+)', block)
            topic_m = _re.search(r'Topic:\s*(.+)', block)
            type_m = _re.search(r'Channel Type:\s*(\w+)', block)
            channels.append({
                "channel_name": name_m.group(1),
                "channel_id": id_m.group(1) if id_m else name_m.group(1),
                "purpose": purpose_m.group(1).strip() if purpose_m else "",
                "topic": topic_m.group(1).strip() if topic_m else "",
                "type": type_m.group(1) if type_m else "public_channel",
            })
        # Augment with Slack Connect channels via direct Web API (MCP doesn't support them)
        try:
            external = _fetch_external_channels()
            existing_ids = {c["channel_id"] for c in channels}
            channels.extend(c for c in external if c["channel_id"] not in existing_ids)
        except Exception as ext_err:
            print(f"[SLACK] external channels error (non-fatal): {ext_err}")
        return {"channels": channels}
    except Exception as e:
        print(f"[SLACK] channels error: {e}")
        return {"channels": [], "error": str(e)}


@router.get("/api/slack/channels/{channel_id}/info")
async def slack_channel_info(channel_id: str):
    try:
        return _slack_mcp_call("slack_search_channels", {"query": channel_id, "limit": 1})
    except Exception as e:
        print(f"[SLACK] channel info error: {e}")
        return {"channel_id": channel_id}


@router.get("/api/slack/channels/{channel_id}/threads")
async def slack_channel_threads(channel_id: str, limit: int = 30, q: str = "",
                                 start: str = None, end: str = None):
    """Third-pane thread listing — searches channel via MCP, parses text into objects."""
    import re as _re
    args = {"query": f"in:#{channel_id} {q}".strip(), "limit": min(limit, 20)}
    if start:
        args["after"] = start
    if end:
        args["before"] = end
    try:
        data = _slack_mcp_call("slack_search_public_and_private", args)
        raw = data.get("results", "") if isinstance(data, dict) else str(data)
        threads = []
        for block in _re.split(r'\n---\n', raw):
            from_m = _re.search(r'From:\s*(.+?)\s*\(ID:', block)
            time_m = _re.search(r'Time:\s*(.+)', block)
            ts_m = _re.search(r'Message_ts:\s*([\d.]+)', block)
            text_m = _re.search(r'Text:\s*\n(.+?)(?:\nContext|\n---|\Z)', block, _re.DOTALL)
            chan_m = _re.search(r'Channel:.*?\(ID:\s*(\w+)\)', block)
            thread_ts_m = _re.search(r'thread_ts=([\d.]+)', block)
            if not ts_m:
                continue
            threads.append({
                "thread_id": ts_m.group(1),
                "message_ts": ts_m.group(1),
                "channel_id": chan_m.group(1) if chan_m else channel_id,
                "parent_user": from_m.group(1).strip() if from_m else "",
                "parent_user_name": from_m.group(1).strip() if from_m else "",
                "thread_date": time_m.group(1).strip() if time_m else "",
                "text": (text_m.group(1).strip() if text_m else "")[:300],
                "summary": (text_m.group(1).strip() if text_m else "")[:300],
                "reply_count": 0,
                "thread_ts": thread_ts_m.group(1) if thread_ts_m else (ts_m.group(1) if ts_m else ""),
            })
        return {"threads": threads}
    except Exception as e:
        print(f"[SLACK] threads error: {e}")
        return {"threads": []}


@router.get("/api/slack/channels/{channel_id}/messages")
async def slack_channel_messages(channel_id: str, limit: int = 50, oldest: str = None, latest: str = None):
    """Read channel messages via conversations.history Web API for reliable user attribution."""
    import re as _re
    import datetime
    from pathlib import Path as _Path
    from skills.slack.mcp_client import get_oauth_token, _load_token

    token = get_oauth_token()
    if not token:
        raise HTTPException(status_code=401, detail="Slack not authenticated")

    team_id = _load_token().get("team_id", "")

    # Persistent display-name cache (uid -> name)
    _ucache_file = _Path.home() / ".config" / "slack-mcp" / "user_cache.json"
    try:
        _ucache = json.loads(_ucache_file.read_text()) if _ucache_file.exists() else {}
    except Exception:
        _ucache = {}
    _ucache_dirty = False

    def _display_name(uid: str) -> str:
        nonlocal _ucache_dirty
        if uid in _ucache:
            return _ucache[uid]
        params: dict = {"user": uid}
        if team_id:
            params["team_id"] = team_id
        data = _slack_web_api("users.info", params)
        if data.get("ok"):
            p = data.get("user", {}).get("profile", {})
            name = p.get("display_name") or p.get("real_name") or uid
            _ucache[uid] = name
            _ucache_dirty = True
            return name
        _ucache[uid] = uid
        return uid

    # Fetch messages
    params: dict = {"channel": channel_id, "limit": min(limit, 200)}
    if team_id:
        params["team_id"] = team_id
    if oldest:
        params["oldest"] = oldest
    if latest:
        params["latest"] = latest

    data = _slack_web_api("conversations.history", params)
    if not data.get("ok"):
        err = data.get("error", "unknown")
        print(f"[SLACK] conversations.history error: {err}")
        raise HTTPException(status_code=503, detail=f"Slack API error: {err}")

    raw_messages = data.get("messages", [])
    next_cursor = data.get("response_metadata", {}).get("next_cursor")

    messages = []
    for msg in reversed(raw_messages):
        subtype = msg.get("subtype", "")
        if subtype in ("channel_join", "channel_leave", "bot_message") and not msg.get("text"):
            continue

        uid = msg.get("user", msg.get("bot_id", ""))
        user_name = _display_name(uid) if uid else "Member"

        ts = msg.get("ts", "")
        try:
            timestamp = datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            timestamp = ts

        # Decode reaction list
        reactions = [
            {"name": r["name"], "count": r["count"]}
            for r in msg.get("reactions", [])
        ]

        # Thread metadata
        reply_count = msg.get("reply_count", 0)
        latest_reply_ts = msg.get("latest_reply", "")
        try:
            latest_reply = datetime.datetime.fromtimestamp(float(latest_reply_ts)).strftime("%Y-%m-%d %H:%M") if latest_reply_ts else ""
        except Exception:
            latest_reply = latest_reply_ts

        # Clean up mrkdwn user mentions: <@UXXXXXXX> -> @display_name
        text = msg.get("text", "")
        for m_uid in set(_re.findall(r'<@(\w+)>', text)):
            text = text.replace(f"<@{m_uid}>", f"@{_display_name(m_uid)}")

        messages.append({
            "user": user_name,
            "user_id": uid,
            "text": text,
            "ts": ts,
            "timestamp": timestamp,
            "reply_count": reply_count,
            "latest_reply": latest_reply,
            "reactions": reactions,
        })

    if _ucache_dirty:
        try:
            _ucache_file.parent.mkdir(parents=True, exist_ok=True)
            _ucache_file.write_text(json.dumps(_ucache))
        except Exception:
            pass

    return {"messages": messages, "cursor": next_cursor or None}


@router.post("/api/slack/resolve-members")
async def slack_resolve_members(request: Request):
    """Lazily resolve 'Member' entries by searching the channel for user IDs, then resolving via profile."""
    import re as _re
    from skills.slack.mcp_client import get_slack_mcp
    body = await request.json()
    channel_id = body.get("channel_id", "")
    timestamps = body.get("timestamps", [])  # message_ts values of "Member" messages
    if not channel_id or not timestamps:
        return {"resolved": {}}

    mcp = get_slack_mcp()
    ts_set = set(timestamps)
    resolved = {}  # ts -> {user, user_id}

    def _profile_name(uid: str) -> str:
        try:
            p_raw = mcp.call("slack_read_user_profile", {"user_id": uid})
            try:
                p_text = json.loads(p_raw).get("result", p_raw)
            except (json.JSONDecodeError, TypeError):
                p_text = p_raw
            for line in p_text.replace("\\n", "\n").splitlines():
                line = line.strip()
                if line.startswith("Display Name:") and line[len("Display Name:"):].strip():
                    return line[len("Display Name:"):].strip()
                if line.startswith("Real Name:") and line[len("Real Name:"):].strip():
                    return line[len("Real Name:"):].strip()
        except Exception:
            pass
        return ""

    try:
        uid_cache = {}

        # Strategy: search for each missing message by its timestamp range
        # Group timestamps and search with time filters to find them
        for ts in timestamps[:10]:  # Cap at 10 to avoid too many API calls
            if ts in resolved:
                continue
            try:
                # Search around that timestamp (+/-1 second)
                ts_float = float(ts)
                search_raw = mcp.call("slack_search_public_and_private", {
                    "query": f"in:<#{channel_id}>",
                    "limit": 5,
                    "after": str(int(ts_float) - 1),
                    "before": str(int(ts_float) + 1),
                    "include_context": False,
                })
                try:
                    search_text = json.loads(search_raw).get("results", "")
                except (json.JSONDecodeError, TypeError):
                    search_text = search_raw or ""

                for block in _re.split(r'\n---\n', search_text):
                    s_ts = _re.search(r'Message_ts:\s*([\d.]+)', block)
                    s_from = _re.search(r'From:\s*(.*?)\(ID:\s*(\w+)\)', block)
                    if s_ts and s_from and s_ts.group(1) in ts_set:
                        uid = s_from.group(2)
                        name = s_from.group(1).strip()
                        if not name and uid:
                            if uid not in uid_cache:
                                uid_cache[uid] = _profile_name(uid) or uid
                            name = uid_cache[uid]
                        resolved[s_ts.group(1)] = {"user": name or uid, "user_id": uid}
            except Exception:
                pass
    except Exception as e:
        print(f"[SLACK] resolve-members error: {e}")

    return {"resolved": resolved}


@router.get("/api/slack/dms")
async def slack_dms():
    """Discover recent DM conversations by searching im/mpim channel types."""
    import re as _re
    from skills.slack.mcp_client import get_slack_mcp, _UNREACHABLE_MSG
    try:
        mcp = get_slack_mcp()
        raw_json = mcp.call("slack_search_public_and_private", {
            "query": "*",
            "channel_types": "im,mpim",
            "limit": 20,
            "sort": "timestamp",
            "sort_dir": "desc",
            "include_context": False,
        })
        if raw_json == _UNREACHABLE_MSG:
            return {"dms": [], "error": "Slack MCP server unreachable"}
        try:
            parsed = json.loads(raw_json)
            raw = parsed.get("results", raw_json)
        except (json.JSONDecodeError, TypeError):
            raw = raw_json
    except Exception as e:
        print(f"[SLACK] DM discovery error: {e}")
        return {"dms": [], "error": str(e)}

    # Parse DM results and deduplicate by channel_id (keep most recent)
    seen = {}  # channel_id -> dm entry
    for block in _re.split(r'\n---\n', raw):
        chan_m = _re.search(r'Channel:\s*(.*?)\s*\(ID:\s*(\w+)\)', block)
        if not chan_m:
            continue
        chan_type = chan_m.group(1).strip()  # "Group DM" or "DM"
        chan_id = chan_m.group(2)
        if chan_id in seen:
            continue  # Already have this DM from a more recent message

        participants_m = _re.search(r'Participants:\s*(.+?)(?:\n|$)', block)
        from_m = _re.search(r'From:\s*(.+?)(?:\(ID:|\n)', block)
        time_m = _re.search(r'Time:\s*(.+)', block)
        ts_m = _re.search(r'Message_ts:\s*([\d.]+)', block)
        text_m = _re.search(r'Text:\s*\n(.+?)(?:\n---|\Z)', block, _re.DOTALL)

        participants = []
        if participants_m:
            for p in _re.finditer(r'([^(,]+?)\s*\(ID:\s*(\w+)\)', participants_m.group(1)):
                participants.append({"name": p.group(1).strip(), "id": p.group(2)})

        # For 1:1 DMs, use the "From" field
        if not participants and from_m:
            name = from_m.group(1).strip()
            if name:
                participants = [{"name": name, "id": ""}]

        display_name = chan_type
        if "Group" in chan_type and participants:
            # Show first 3 participant names
            names = [p["name"] for p in participants if p["name"] != "Mayuresh Kulkarni"][:3]
            display_name = ", ".join(names)
            if len(participants) > 4:
                display_name += f" +{len(participants) - 3}"
        elif participants:
            other = [p for p in participants if p["name"] != "Mayuresh Kulkarni"]
            display_name = other[0]["name"] if other else participants[0]["name"]

        seen[chan_id] = {
            "channel_id": chan_id,
            "display_name": display_name,
            "participants": participants,
            "last_message": (text_m.group(1).strip()[:100] if text_m else ""),
            "last_ts": ts_m.group(1) if ts_m else "",
            "timestamp": time_m.group(1).strip() if time_m else "",
            "type": "mpim" if "Group" in chan_type else "im",
        }

    return {"dms": list(seen.values())}


@router.get("/api/slack/search")
async def slack_search(q: str = "", after: str = None, before: str = None, limit: int = 20):
    args = {"query": q, "limit": limit}
    if after:
        args["after"] = after
    if before:
        args["before"] = before
    return _slack_mcp_call("slack_search_public_and_private", args)


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


@router.get("/api/slack/threads/{channel_id}/{message_ts}")
async def slack_thread_detail(channel_id: str, message_ts: str, limit: int = 50):
    """Read a thread via conversations.replies Web API for reliable user attribution."""
    import re as _re
    import datetime
    from pathlib import Path as _Path
    from skills.slack.mcp_client import get_oauth_token, _load_token

    token = get_oauth_token()
    if not token:
        raise HTTPException(status_code=401, detail="Slack not authenticated")

    team_id = _load_token().get("team_id", "")

    # Persistent display-name cache
    _ucache_file = _Path.home() / ".config" / "slack-mcp" / "user_cache.json"
    try:
        _ucache = json.loads(_ucache_file.read_text()) if _ucache_file.exists() else {}
    except Exception:
        _ucache = {}
    _ucache_dirty = False

    def _display_name(uid: str) -> str:
        nonlocal _ucache_dirty
        if uid in _ucache:
            return _ucache[uid]
        params: dict = {"user": uid}
        if team_id:
            params["team_id"] = team_id
        data = _slack_web_api("users.info", params)
        if data.get("ok"):
            p = data.get("user", {}).get("profile", {})
            name = p.get("display_name") or p.get("real_name") or uid
            _ucache[uid] = name
            _ucache_dirty = True
            return name
        _ucache[uid] = uid
        return uid

    params: dict = {"channel": channel_id, "ts": message_ts, "limit": min(limit, 200)}
    if team_id:
        params["team_id"] = team_id

    data = _slack_web_api("conversations.replies", params)
    if not data.get("ok"):
        err = data.get("error", "unknown")
        print(f"[SLACK] conversations.replies error: {err}")
        raise HTTPException(status_code=503, detail=f"Slack API error: {err}")

    raw_messages = data.get("messages", [])

    def _fmt_ts(ts: str) -> str:
        try:
            return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ts

    def _clean_text(text: str) -> str:
        for uid in set(_re.findall(r'<@(\w+)>', text)):
            text = text.replace(f"<@{uid}>", f"@{_display_name(uid)}")
        return text

    messages = []
    for msg in raw_messages:
        uid = msg.get("user", msg.get("bot_id", ""))
        user_name = _display_name(uid) if uid else "Member"
        ts = msg.get("ts", "")
        reactions = [
            {"name": r["name"], "count": r["count"]}
            for r in msg.get("reactions", [])
        ]
        messages.append({
            "user": user_name,
            "user_id": uid,
            "text": _clean_text(msg.get("text", "")),
            "timestamp": _fmt_ts(ts),
            "ts": ts,
            "reactions": reactions,
        })

    if _ucache_dirty:
        try:
            _ucache_file.parent.mkdir(parents=True, exist_ok=True)
            _ucache_file.write_text(json.dumps(_ucache))
        except Exception:
            pass

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
    params = {"channel_id": channel_id, "message": req.message}
    if req.thread_ts:
        params["thread_ts"] = req.thread_ts
    return _slack_mcp_call("slack_send_message", params)


@router.get("/api/slack/users/{query}")
async def slack_user_lookup(query: str):
    try:
        return _slack_mcp_call("slack_search_users", {"query": query})
    except Exception as e:
        print(f"[SLACK] user lookup failed for '{query}': {e}")
        return {"user": None, "error": "lookup_failed"}


@router.post("/api/slack/dm")
async def slack_send_dm(req: Request):
    body = await req.json()
    return _slack_mcp_call("slack_send_message", {
        "channel_id": body.get("user_id", body.get("channel_id", "")),
        "message": body.get("message", ""),
    })
