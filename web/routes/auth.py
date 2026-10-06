"""Auth routes — M365 token exchange, Teams capture, device auth, GitHub tool/PR/issue."""

import asyncio
import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import secure_store
import shared
from security import verify_csrf

router = APIRouter()
_log = logging.getLogger("auth")


# ── Pydantic models ───────────────────────────────────────────────────────────


class TokenRequest(BaseModel):
    token: str


class GithubToolRequest(BaseModel):
    tool: str
    input: dict = {}


class DeviceCodePollRequest(BaseModel):
    device_code: str
    tenant_id: str = "organizations"


# ── M365 Token Exchange ──────────────────────────────────────────────────────


@router.post("/api/auth/token")
async def save_token(req: TokenRequest):
    import base64, time as _time

    token = req.token.strip().strip('"').strip("'")
    if token.startswith("Bearer "):
        token = token[7:]
    # Decode JWT claims locally — no Graph round-trip needed
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = json.loads(base64.b64decode(payload))
    except Exception:
        raise HTTPException(
            status_code=400, detail="Invalid token format — paste the full Bearer token"
        )
    # Check expiry from claims
    exp = claims.get("exp", 0)
    remaining = int(exp - _time.time())
    if remaining <= 0:
        raise HTTPException(
            status_code=401,
            detail="Token is already expired — recapture via the in-pane overlay",
        )
    # Save under a separate secret name — never overwrites the OAuth token
    secure_store.set_json(
        "graph/teams_token",
        {
            "access_token": token,
            "expires_at": claims.get("exp", _time.time() + 3600),
        },
    )
    remaining = int((claims.get("exp", 0) - _time.time()) / 60)
    scopes = claims.get("scp", "").split()
    return {
        "ok": True,
        "user": claims.get("name", claims.get("upn", "")),
        "expires_in_minutes": remaining,
        "has_chat_read": "Chat.Read" in scopes,
        "scope_count": len(scopes),
    }


# ── Teams Token Capture ──────────────────────────────────────────────────────


@router.post("/api/auth/teams/capture")
async def teams_token_capture():
    """Auto-capture Teams token by opening Outlook in Edge and intercepting CDP network events."""
    import asyncio
    import base64 as _b64
    import time as _time

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from capture_token import capture_token

    loop = asyncio.get_event_loop()
    token = await loop.run_in_executor(None, capture_token)

    if not token:
        raise HTTPException(
            status_code=504,
            detail="Could not capture token — Outlook may not have loaded or SSO timed out. Try signing in manually.",
        )

    raw = token.removeprefix("Bearer ").strip()
    try:
        payload = raw.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = json.loads(_b64.b64decode(payload))
        remaining = int(claims.get("exp", 0) - _time.time())
        if remaining <= 0:
            raise HTTPException(
                status_code=401, detail="Captured token is already expired."
            )
    except HTTPException:
        raise
    except Exception:
        remaining = 3600
        claims = {}

    secure_store.set_json(
        "graph/teams_token",
        {
            "access_token": raw,
            "expires_at": claims.get("exp", _time.time() + remaining),
        },
    )

    return {
        "ok": True,
        "expires_in_minutes": max(0, remaining // 60),
        "scope_count": len(claims.get("scp", "").split()),
    }


@router.get("/api/auth/teams/capture/stream")
async def teams_token_capture_stream():
    """SSE stream: runs capture_token and emits status + result events."""
    import base64 as _b64
    import time as _time
    import queue as _queue
    import threading as _threading

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from capture_token import capture_token

    q: _queue.Queue = _queue.Queue()

    def _run():
        def cb(msg: str):
            q.put(("status", msg))

        tok = capture_token(status_cb=cb)
        q.put(("done", tok))

    _threading.Thread(target=_run, daemon=True).start()

    async def _generate():
        while True:
            await asyncio.sleep(0.1)
            while not q.empty():
                kind, val = q.get()
                if kind == "status":
                    yield f"event: status\ndata: {json.dumps(val)}\n\n"
                elif kind == "done":
                    if not val:
                        yield f"event: error\ndata: {json.dumps('Could not capture token — SSO may need more time. Try again.')}\n\n"
                        return
                    raw = val.removeprefix("Bearer ").strip()
                    try:
                        payload = raw.split(".")[1]
                        payload += "=" * (4 - len(payload) % 4)
                        claims = json.loads(_b64.b64decode(payload))
                        remaining = int(claims.get("exp", 0) - _time.time())
                    except Exception:
                        remaining = 3600
                        claims = {}
                    secure_store.set_json(
                        "graph/teams_token",
                        {
                            "access_token": raw,
                            "expires_at": claims.get("exp", _time.time() + remaining),
                        },
                    )
                    result = {
                        "ok": True,
                        "expires_in_minutes": max(0, remaining // 60),
                        "scope_count": len(claims.get("scp", "").split()),
                    }
                    yield f"event: result\ndata: {json.dumps(result)}\n\n"
                    return

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Auth Status ───────────────────────────────────────────────────────────────


def _slack_status_block() -> dict:
    """Slack agent-token status from the Slack MCP token file. Standalone so it
    runs even when M365 has no token (the dashboard needs Slack status
    independently)."""
    import time as _time

    try:
        sd = secure_store.get_json("slack/token")
    except Exception:
        sd = None
    if not sd:
        return {
            "ok": False,
            "expires_in_minutes": 0,
            "has_refresh_token": False,
            "team": "",
        }
    try:
        exp = float(sd.get("expires_at", 0))
        return {
            "ok": bool(sd.get("access_token")) and _time.time() < exp,
            "expires_in_minutes": max(0, int((exp - _time.time()) // 60)),
            "has_refresh_token": bool(sd.get("refresh_token")),
            "team": sd.get("team", ""),
        }
    except Exception:
        return {
            "ok": False,
            "expires_in_minutes": 0,
            "has_refresh_token": False,
            "team": "",
        }


def _teams_chat_status_block() -> dict:
    """Teams Chat.ReadWrite browser-captured token status."""
    import time as _time

    try:
        td = secure_store.get_json("graph/teams_token")
    except Exception:
        td = None
    if not td:
        return {"ok": False, "expires_in_minutes": 0, "has_refresh_token": False}
    try:
        rem = int(td.get("expires_at", 0) - _time.time())
        return {
            "ok": rem > 0,
            "expires_in_minutes": max(0, rem // 60),
            "has_refresh_token": False,
        }
    except Exception:
        return {"ok": False, "expires_in_minutes": 0, "has_refresh_token": False}


@router.get("/api/auth/status")
async def auth_status():
    import base64, time as _time

    # Slack + Teams-chat status are independent of M365 — build them up front so
    # the dashboard always gets an `apps` payload even when M365 isn't signed in.
    slack_block = _slack_status_block()
    teams_chat_block = _teams_chat_status_block()

    def _apps_payload(m365_api):
        return {
            "m365": {"api": m365_api, "web": None},
            "teams_chat": {"api": teams_chat_block, "web": None},
            "slack": {"api": slack_block, "web": None},
        }

    _m365_absent = {"ok": False, "expires_in_minutes": 0, "has_refresh_token": False}

    try:
        data = secure_store.get_json("graph/token")
    except Exception:
        data = None
    if not data:
        return {
            "authenticated": False,
            "reason": "No token",
            "teams_token_ok": teams_chat_block["ok"],
            "apps": _apps_payload(_m365_absent),
        }
    try:
        token = data.get("access_token", "")
        if not token:
            return {
                "authenticated": False,
                "reason": "No access token",
                "teams_token_ok": teams_chat_block["ok"],
                "apps": _apps_payload(_m365_absent),
            }
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = json.loads(base64.b64decode(payload))
        remaining = int(claims.get("exp", 0) - _time.time())
        scopes = claims.get("scp", "").split()
        teams_ok = teams_chat_block["ok"]
        teams_expires = teams_chat_block["expires_in_minutes"]
        has_refresh = bool(data.get("refresh_token", ""))
        # Logged-in user's email — prefer mail-ish claims; used client-side to
        # exclude self when pre-filling Reply-All CC (#86).
        user_email = (
            claims.get("upn")
            or claims.get("preferred_username")
            or claims.get("email")
            or ""
        )
        if "@" not in user_email:
            user_email = ""
        m365_api = {
            "ok": remaining > 0,
            "expires_in_minutes": max(0, remaining // 60),
            "has_refresh_token": has_refresh,
            "user": claims.get("name", claims.get("upn", "")),
            "email": user_email,
        }
        return {
            "authenticated": remaining > 0,
            "user": claims.get("name", claims.get("upn", "")),
            "email": user_email,
            "expires_in_minutes": max(0, remaining // 60),
            "has_refresh_token": has_refresh,
            "expired": remaining <= 0,
            "has_mail": any(s.startswith("Mail") for s in scopes)
            or "Files.ReadWrite.All" in scopes,
            "scope_count": len(scopes),
            "teams_token_ok": teams_ok,
            "teams_expires_in_minutes": teams_expires,
            # Structured per-app dashboard payload. Webview (web) fields are null
            # here and filled client-side via gatorShell.
            "apps": _apps_payload(m365_api),
        }
    except Exception as e:
        return {
            "authenticated": False,
            "reason": str(e),
            "teams_token_ok": teams_chat_block["ok"],
            "apps": _apps_payload(_m365_absent),
        }


# ── Device Auth ───────────────────────────────────────────────────────────────


@router.post("/api/auth/device/start")
async def device_auth_start():
    from skills._m365.helpers import GraphClient

    try:
        gc = GraphClient()
        info = gc.start_auth()
        return {
            "ok": True,
            "user_code": info["user_code"],
            "url": info["url"],
            "device_code": info["device_code"],
            "expires_in": info["expires_in"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/auth/device/poll")
async def device_auth_poll(req: DeviceCodePollRequest):
    from skills._m365.helpers import GraphClient, reset_graph_client
    import logging as _log

    _logger = _log.getLogger("auth")
    try:
        gc = GraphClient()
        gc._tenant_id = req.tenant_id
        result = gc.complete_auth(req.device_code)
        if result.get("status") == "ok":
            reset_graph_client()
            # Diagnostic: confirm the stored token has the fields needed for
            # refresh. Logs only booleans/expiry, never token values.
            import time as _time

            try:
                _td = secure_store.get_json("graph/token") or {}
                _has_refresh = bool(_td.get("refresh_token"))
                _has_tenant = bool(_td.get("tenant_id"))
                _exp = _td.get("expires_at", 0)
                _remaining = int(_exp - _time.time())
                if not _has_refresh or not _has_tenant:
                    _logger.warning(
                        "Stored token after auth is missing fields — "
                        "has_refresh_token=%s has_tenant_id=%s — SharePoint refresh will fail",
                        _has_refresh,
                        _has_tenant,
                    )
                else:
                    _logger.info(
                        "Stored token OK after auth — access_token expires in %ds, "
                        "has_refresh_token=%s has_tenant_id=%s",
                        _remaining,
                        _has_refresh,
                        _has_tenant,
                    )
            except Exception as _e:
                _logger.warning("Could not read stored token after auth: %s", _e)
            return {"ok": True, "message": result["message"]}
        return {"ok": False, "pending": True}
    except Exception as e:
        msg = str(e)
        if "authorization_pending" in msg:
            return {"ok": False, "pending": True}
        return {"ok": False, "pending": False, "error": msg}


# ── GitHub Direct Tool Dispatch ───────────────────────────────────────────────


@router.post("/api/github/tool")
async def github_tool(req: GithubToolRequest):
    """Direct tool dispatch for GitHub pane -- bypasses the full agentic loop."""
    from skills.github.tools import TOOL_HANDLERS as _gh_handlers

    handler = _gh_handlers.get(req.tool)
    if not handler:
        raise HTTPException(status_code=400, detail=f"Unknown GitHub tool: {req.tool}")
    try:
        return handler(**req.input)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/github/pr")
async def github_get_pr_endpoint(body: dict):
    from skills.github.tools import _github_get_pr

    return _github_get_pr(body["owner"], body["repo"], body["pr_number"])


@router.post("/api/github/issue")
async def github_get_issue_endpoint(body: dict):
    from skills.github.tools import _github_get_issue

    return _github_get_issue(body["owner"], body["repo"], body["issue_number"])


# ── Clear stored credentials ──────────────────────────────────────────────────

_CLEAR_SCOPES = {
    "graph": ["graph/token", "graph/teams_token", "graph/skype_token"],
    "slack": ["slack/token", "slack/pkce"],
}
_PAT_ENV = ("JIRA_API_TOKEN", "JIRA_PAT_TOKEN", "CONFLUENCE_PAT", "GITHUB_TOKEN")


def _revoke_slack(token: dict) -> None:
    access = token.get("access_token", "")
    if not access:
        return
    req = urllib.request.Request(
        "https://slack.com/api/auth.revoke",
        data=urllib.parse.urlencode({"token": access}).encode(),
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10).read()


def _revoke_oauth(record: dict) -> None:
    prov = record.get("provider") or {}
    endpoint = prov.get("revocation_endpoint", "")
    token = record.get("token") or {}
    if not endpoint or not token.get("access_token"):
        return
    if urllib.parse.urlparse(endpoint).scheme != "https":
        raise ValueError("revocation endpoint must use https")
    for hint, value in (
        ("refresh_token", token.get("refresh_token")),
        ("access_token", token.get("access_token")),
    ):
        if value:
            body = urllib.parse.urlencode(
                {"token": value, "token_type_hint": hint, "client_id": prov.get("client_id", "")}
            ).encode()
            urllib.request.urlopen(
                urllib.request.Request(endpoint, data=body, method="POST"), timeout=10
            ).read()


@router.get("/api/auth/storage")
def storage_level():  # sync: protection_level() may call the OS vault
    return {"level": secure_store.protection_level()}


@router.post("/api/auth/clear", dependencies=[Depends(verify_csrf)])
def clear_credentials(body: dict | None = None):  # sync: runs in the threadpool, revocation does blocking I/O
    scope = (body or {}).get("scope", "all")
    valid = {"all", "graph", "slack", "mcp", "pats"}
    if scope not in valid:
        raise HTTPException(400, f"scope must be one of {sorted(valid)}")
    names: list[str] = []
    if scope in ("all", "graph"):
        names += _CLEAR_SCOPES["graph"]
    if scope in ("all", "slack"):
        names += _CLEAR_SCOPES["slack"]
    if scope in ("all", "mcp"):
        names += secure_store.list_names("oauth/")
    if scope in ("all", "pats"):
        names += secure_store.list_names("config/")
    revoked: list[str] = []
    if scope in ("all", "slack"):
        tok = secure_store.get_json("slack/token")
        if tok:
            try:
                _revoke_slack(tok)
                revoked.append("slack")
            except Exception as exc:
                _log.warning("slack revoke failed: %s", type(exc).__name__)
    if scope in ("all", "mcp"):
        for name in secure_store.list_names("oauth/"):
            rec = secure_store.get_json(name)
            if rec:
                try:
                    _revoke_oauth(rec)
                    if (rec.get("provider") or {}).get("revocation_endpoint"):
                        revoked.append(name)
                except Exception as exc:
                    _log.warning("oauth revoke failed for %s: %s", name, type(exc).__name__)
    for name in names:
        secure_store.delete(name)
    if scope in ("all", "pats"):
        for var in _PAT_ENV:
            os.environ.pop(var, None)
        # Drop the in-memory copies too, or the next save_config(shared.cfg)
        # would write the cleared PATs straight back into secure_store.
        from config import _PAT_KEYS

        for key in _PAT_KEYS:
            shared.cfg.pop(key, None)
    if scope in ("all", "graph"):
        from skills._m365.helpers import reset_graph_client

        reset_graph_client()
    return {"cleared": sorted(set(names)), "revoked": revoked}
