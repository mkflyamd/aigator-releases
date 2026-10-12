"""Process-local CSRF token for guarding HITL-sensitive endpoints.

The token is generated once per server process and embedded in the served
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

import os
import secrets
from urllib.parse import urlsplit

from fastapi import Header, HTTPException

_TOKEN: str | None = None
_SHELL_KEY: str | None = os.environ.pop("AIGATOR_SHELL_KEY", "") or None


def get_csrf_token() -> str:
    """Return the per-process CSRF token, generating it on first access."""
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = secrets.token_urlsafe(32)
    return _TOKEN


async def verify_csrf(x_csrf_token: str | None = Header(default=None)) -> None:
    """FastAPI dependency: reject requests without a matching CSRF header."""
    expected = get_csrf_token()
    if not x_csrf_token or not secrets.compare_digest(x_csrf_token, expected):
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
