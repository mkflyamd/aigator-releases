"""Process-local CSRF token for guarding HITL-sensitive endpoints.

The token is derived per server process and per origin (Host header) and embedded in the served
index.html as window.__CSRF_TOKEN__. The UI sends it back via the
X-CSRF-Token header on sensitive POST requests. The in-process agent loop
has no path to read window globals from the browser, so it cannot forge
the header — even if a future tool gains HTTP-fetch capability into the
local FastAPI server.

This is the runtime backstop for the HITL convention (see CLAUDE.md and
GitHub issue #61).

The token is only handed out to the AI Gator shell. The Electron shell
generates a per-launch secret, passes it in AIGATOR_SHELL_KEY and sends it as
X-AIGator-Shell-Key to this backend; GET / and GET /api/csrf require it when
one is configured. The key is read once at import and removed from os.environ
so child processes (shells, sandboxed runs, pip) cannot inherit it. With no
key configured (backend started by hand, tests) the endpoints stay open.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from urllib.parse import urlsplit

from fastapi import Header, HTTPException, Request

_TOKEN: bytes | None = None
_SHELL_KEY: str | None = os.environ.pop("AIGATOR_SHELL_KEY", "") or None


def get_csrf_token(host: str) -> str:
    """Return the CSRF token for one origin (the Host header of the page request).

    The token is an HMAC of the lowercase host under a per-process random secret.
    A token taken from one origin (for example localhost:8000) is not valid for
    another (127.0.0.1:8000), and no token survives a restart.
    """
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = secrets.token_bytes(32)
    digest = hmac.new(_TOKEN, host.strip().lower().encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


async def verify_csrf(request: Request, x_csrf_token: str | None = Header(default=None)) -> None:
    """FastAPI dependency: reject requests without a CSRF header that matches this origin."""
    expected = get_csrf_token(request.headers.get("host", ""))
    if not x_csrf_token or not secrets.compare_digest(x_csrf_token.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")


# Routes that send, create, edit or delete user data. Each must require the CSRF token (verify_csrf);
# tests/test_csrf_route_inventory.py fails if one is missing, unprotected, or renamed without updating this list.
# Add every new send/create/delete route here and give it dependencies=[Depends(verify_csrf)].
SENSITIVE_ROUTES: frozenset[str] = frozenset({
    "POST /api/aigator/create-docx",
    "POST /api/aigator/create-excel",
    "POST /api/aigator/create-pptx",
    "POST /api/aigator/update-docx",
    "POST /api/aigator/update-excel",
    "POST /api/aigator/update-pptx",
    "POST /api/calendar/events/{event_id}/respond",
    "DELETE /api/config/custom-apps/{app_id}",
    "DELETE /api/config/llm/profiles/{profile_id}",
    "DELETE /api/config/mcp/{connection_id}",
    "DELETE /api/config/persona/{persona_id}",
    "POST /api/confluence/page",
    "PUT /api/confluence/page/{page_id}",
    "DELETE /api/context/pin/{source}/{item_id}",
    "DELETE /api/context/pins",
    "DELETE /api/conversation/{context_id}",
    "POST /api/email/forward",
    "POST /api/email/messages/{message_id}/respond",
    "POST /api/email/reply",
    "POST /api/email/send",
    "DELETE /api/extensions/setup/{session_id}",
    "POST /api/github/issue",
    "POST /api/github/pr",
    "POST /api/jira/issue/{issue_key}/assign",
    "POST /api/jira/issue/{issue_key}/comment",
    "POST /api/jira/issue/{issue_key}/transition",
    "POST /api/marketplace/create",
    "PUT /api/marketplace/skill-md/{skill_id}",
    "DELETE /api/marketplace/uninstall/{skill_id}",
    "POST /api/onedrive/drives/{drive_id}/folders/{parent_id}",
    "POST /api/onedrive/folders/{parent_id}",
    "DELETE /api/onedrive/items/{item_id}",
    "PATCH /api/onedrive/items/{item_id}",
    "POST /api/onedrive/upload/{folder_id}",
    "PATCH /api/onenote/pages/{page_id}",
    "DELETE /api/onenote/pin/{page_id}",
    "POST /api/onenote/sections/{section_id}/pages",
    "POST /api/scheduler/jobs",
    "DELETE /api/scheduler/jobs/{job_id}",
    "PATCH /api/scheduler/jobs/{job_id}",
    "POST /api/scheduler/jobs/{job_id}/run-now",
    "POST /api/slack/channels/{channel_id}/post",
    "POST /api/slack/channels/{channel_id}/send",
    "POST /api/slack/dm",
    "POST /api/slack/dm/send",
    "POST /api/slack/react",
    "POST /api/slack/unreact",
    "POST /api/tasks",
    "DELETE /api/tasks/completed",
    "DELETE /api/tasks/{task_id}",
    "POST /api/teams/channels",
    "POST /api/teams/channels/{team_id}/{channel_id}/send",
    "POST /api/teams/chats/new",
    "POST /api/teams/chats/{chat_id}/members/add",
    "DELETE /api/teams/chats/{chat_id}/members/{member_mri}",
    "DELETE /api/teams/chats/{chat_id}/messages/{message_id}",
    "PATCH /api/teams/chats/{chat_id}/messages/{message_id}",
    "POST /api/teams/chats/{chat_id}/messages/{message_id}/react",
    "PATCH /api/teams/chats/{chat_id}/rename",
    "POST /api/teams/chats/{chat_id}/send",
    "POST /api/teams/send-message",
    "POST /api/upload/onedrive",
    "POST /api/widgets",
    "DELETE /api/widgets/{widget_id}",
    "PATCH /api/widgets/{widget_id}",
})


async def require_shell_key(x_aigator_shell_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency: when a shell key is configured, require it exactly."""
    if _SHELL_KEY is None:
        return
    if not x_aigator_shell_key or not secrets.compare_digest(
        x_aigator_shell_key.encode("utf-8"), _SHELL_KEY.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="Shell key missing or invalid")


_CDN = "https://cdn.jsdelivr.net"
_HOST_OK = re.compile(r"^[A-Za-z0-9.\-]+(:\d+)?$|^\[[0-9A-Fa-f:]+\](:\d+)?$")


def new_csp_nonce() -> str:
    return secrets.token_urlsafe(16)


def script_json(value) -> str:
    """JSON for an inline script. A "<" is escaped so data can never close the script tag."""
    return json.dumps(value).replace("<", "\\u003c")


def csp_header_name() -> str:
    """AIGATOR_CSP_REPORT_ONLY=1 turns the policy into report-only (browser logs, does not block)."""
    if os.environ.get("AIGATOR_CSP_REPORT_ONLY") == "1":
        return "Content-Security-Policy-Report-Only"
    return "Content-Security-Policy"


def build_csp(nonce: str, host: str) -> str:
    """Content-Security-Policy for the app page: no inline script without the per-response nonce.

    Scripts load only from this server and the pinned CDN. Inline styles stay allowed
    (the UI sets style attributes everywhere); that is a documented residual.
    """
    ws = f" ws://{host}" if _HOST_OK.match(host or "") else ""
    directives = [
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}' {_CDN}",
        f"style-src 'self' 'unsafe-inline' {_CDN} https://fonts.googleapis.com",
        f"font-src 'self' data: {_CDN} https://fonts.gstatic.com",
        "img-src 'self' data: blob: https:",
        "media-src 'self' blob:",
        f"connect-src 'self'{ws} {_CDN} http://localhost:8001",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'",
    ]
    return "; ".join(directives)


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def origin_allowed(method: str, host: str | None, origin: str | None, referer: str | None) -> bool:
    """State-changing browser requests must come from the page this server serves.

    Browsers always attach Origin (or at least Referer) to cross-site POSTs, so a
    foreign page or a DNS-rebound hostname is refused. Requests that carry neither
    header are not browser-initiated and fall through to the token checks.
    """
    if method.upper() in _SAFE_METHODS:
        return True
    source = origin or referer
    if not source:
        return True
    parsed = urlsplit(source)
    return (
        parsed.scheme == "http"
        and parsed.hostname in _LOOPBACK_HOSTS
        and bool(host)
        and parsed.netloc.lower() == host.lower()
    )
