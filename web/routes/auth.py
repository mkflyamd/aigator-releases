"""Auth routes — M365 token exchange, Teams capture, device auth, GitHub tool/PR/issue."""

import asyncio
import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import shared

router = APIRouter()


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
    import base64, time as _time, os as _os
    from pathlib import Path as _Path
    token = req.token.strip().strip('"').strip("'")
    if token.startswith("Bearer "):
        token = token[7:]
    # Decode JWT claims locally — no Graph round-trip needed
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = json.loads(base64.b64decode(payload))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid token format — paste the full Bearer token")
    # Check expiry from claims
    exp = claims.get("exp", 0)
    remaining = int(exp - _time.time())
    if remaining <= 0:
        raise HTTPException(status_code=401, detail="Token is already expired — get a fresh one from Outlook Web DevTools")
    # Save to separate teams token file — never overwrites the OAuth token
    teams_token_file = _Path.home() / ".config" / "microsoft-graph" / "teams_token.json"
    teams_token_file.parent.mkdir(parents=True, exist_ok=True)
    teams_token_file.write_text(json.dumps({
        "access_token": token,
        "expires_at": claims.get("exp", _time.time() + 3600),
    }, indent=2))
    _os.chmod(str(teams_token_file), 0o600)
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
    from pathlib import Path as _Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from capture_token import capture_token

    loop = asyncio.get_event_loop()
    token = await loop.run_in_executor(None, capture_token)

    if not token:
        raise HTTPException(
            status_code=504,
            detail="Could not capture token — Outlook may not have loaded or SSO timed out. Try signing in manually."
        )

    raw = token.removeprefix("Bearer ").strip()
    try:
        payload = raw.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = json.loads(_b64.b64decode(payload))
        remaining = int(claims.get("exp", 0) - _time.time())
        if remaining <= 0:
            raise HTTPException(status_code=401, detail="Captured token is already expired.")
    except HTTPException:
        raise
    except Exception:
        remaining = 3600
        claims = {}

    teams_token_file = _Path.home() / ".config" / "microsoft-graph" / "teams_token.json"
    teams_token_file.parent.mkdir(parents=True, exist_ok=True)
    teams_token_file.write_text(json.dumps({
        "access_token": raw,
        "expires_at": claims.get("exp", _time.time() + remaining),
    }, indent=2))
    os.chmod(str(teams_token_file), 0o600)

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
    from pathlib import Path as _Path

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
                    teams_token_file = _Path.home() / ".config" / "microsoft-graph" / "teams_token.json"
                    teams_token_file.parent.mkdir(parents=True, exist_ok=True)
                    teams_token_file.write_text(json.dumps({
                        "access_token": raw,
                        "expires_at": claims.get("exp", _time.time() + remaining),
                    }, indent=2))
                    os.chmod(str(teams_token_file), 0o600)
                    result = {
                        "ok": True,
                        "expires_in_minutes": max(0, remaining // 60),
                        "scope_count": len(claims.get("scp", "").split()),
                    }
                    yield f"event: result\ndata: {json.dumps(result)}\n\n"
                    return

    return StreamingResponse(_generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Auth Status ───────────────────────────────────────────────────────────────

@router.get("/api/auth/status")
async def auth_status():
    import base64, time as _time
    from pathlib import Path as _Path
    token_file = _Path.home() / ".config" / "microsoft-graph" / "token.json"
    if not token_file.exists():
        return {"authenticated": False, "reason": "No token file"}
    try:
        data = json.loads(token_file.read_text())
        token = data.get("access_token", "")
        if not token:
            return {"authenticated": False, "reason": "No access token"}
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = json.loads(base64.b64decode(payload))
        remaining = int(claims.get("exp", 0) - _time.time())
        scopes = claims.get("scp", "").split()
        # Check separate Teams browser token
        teams_token_file = _Path.home() / ".config" / "microsoft-graph" / "teams_token.json"
        teams_ok = False
        teams_expires = 0
        if teams_token_file.exists():
            try:
                td = json.loads(teams_token_file.read_text())
                t_remaining = int(td.get("expires_at", 0) - _time.time())
                teams_ok = t_remaining > 0
                teams_expires = max(0, t_remaining // 60)
            except Exception:
                pass
        has_refresh = bool(data.get("refresh_token", ""))
        return {
            "authenticated": remaining > 0,
            "user": claims.get("name", claims.get("upn", "")),
            "expires_in_minutes": max(0, remaining // 60),
            "has_refresh_token": has_refresh,
            "expired": remaining <= 0,
            "has_mail": any(s.startswith("Mail") for s in scopes) or "Files.ReadWrite.All" in scopes,
            "scope_count": len(scopes),
            "teams_token_ok": teams_ok,
            "teams_expires_in_minutes": teams_expires,
        }
    except Exception as e:
        return {"authenticated": False, "reason": str(e)}


# ── Device Auth ───────────────────────────────────────────────────────────────

@router.post("/api/auth/device/start")
async def device_auth_start():
    from skills._m365.helpers import GraphClient
    try:
        gc = GraphClient()
        info = gc.start_auth()
        return {"ok": True, "user_code": info["user_code"], "url": info["url"],
                "device_code": info["device_code"], "expires_in": info["expires_in"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/auth/device/poll")
async def device_auth_poll(req: DeviceCodePollRequest):
    from skills._m365.helpers import GraphClient
    try:
        gc = GraphClient()
        gc._tenant_id = req.tenant_id
        result = gc.complete_auth(req.device_code)
        if result.get("status") == "ok":
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
