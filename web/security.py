"""Process-local CSRF token for guarding HITL-sensitive endpoints.

The token is generated once per server process and embedded in the served
index.html as window.__CSRF_TOKEN__. The UI sends it back via the
X-CSRF-Token header on sensitive POST requests. The in-process agent loop
has no path to read window globals from the browser, so it cannot forge
the header — even if a future tool gains HTTP-fetch capability into the
local FastAPI server.

This is the runtime backstop for the HITL convention (see CLAUDE.md and
GitHub issue #61).
"""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

_TOKEN: str | None = None


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
