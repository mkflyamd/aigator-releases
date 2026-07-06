"""Slack OAuth token management — PKCE flow and token storage.

MCP transport removed: all Slack API calls now go direct to https://slack.com/api/...
Auth: OAuth 2.0 with PKCE (user-scoped tokens stored in ~/.config/slack-mcp/token.json)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Client ID from the official Slack plugin for Claude Code
SLACK_OAUTH_CLIENT_ID = "1601185624273.8899143856786"
SLACK_AUTH_URL = "https://slack.com/oauth/v2_user/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.user.access"
SLACK_SCOPES = (
    # search:read removed — the Anthropic MCP app doesn't allow it as an approved scope.
    # search.messages Web API requires a custom app with search:read.
    # Channel/DM browsing works via conversations.list (no search:read needed).
    "search:read.public,search:read.private,search:read.mpim,search:read.im,"
    "search:read.files,search:read.users,chat:write,"
    "channels:history,groups:history,mpim:history,im:history,"
    "canvases:read,canvases:write,users:read,users:read.email,"
    "reactions:write,reactions:read,emoji:read,files:read,"
    "channels:write,groups:write,im:write,mpim:write,"
    "channels:read,groups:read,im:read,mpim:read"
)

TOKEN_FILE = Path.home() / ".config" / "slack-mcp" / "token.json"

# Serialises concurrent token refresh calls so two threads don't both exchange
# the refresh token (each exchange invalidates the previous refresh token).
_REFRESH_LOCK = threading.Lock()

# ── OAuth Token Storage ───────────────────────────────────────────────────────

def _load_token() -> dict:
    """Load stored OAuth token from disk."""
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return {}


def _save_token(data: dict) -> None:
    """Save OAuth token to disk with restrictive permissions.

    Also clears the user display-name cache so that workspace switches
    don't serve stale names from the previous workspace.
    """
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(data, indent=2))
    try:
        os.chmod(str(TOKEN_FILE), 0o600)
    except OSError:
        pass  # Windows may not support chmod
    # Clear the display-name cache — lazy import avoids circular dependency
    try:
        import routes.slack as _slack_routes
        if hasattr(_slack_routes, "clear_user_cache"):
            _slack_routes.clear_user_cache()
    except Exception:
        pass


def get_oauth_token() -> str:
    """Get a valid OAuth access token, refreshing if expired.

    _REFRESH_LOCK prevents concurrent threads from both executing a refresh
    when the token is near expiry — each Slack refresh exchange invalidates
    the previous refresh token, so only one can succeed.
    """
    data = _load_token()
    if not data.get("access_token"):
        return ""
    if data.get("expires_at", 0) > time.time() + 60:
        return data["access_token"]
    refresh = data.get("refresh_token", "")
    if not refresh:
        return data.get("access_token", "")
    with _REFRESH_LOCK:
        # Re-read after acquiring lock — another thread may have already refreshed.
        data = _load_token()
        if data.get("expires_at", 0) > time.time() + 60:
            return data["access_token"]
        refreshed = _refresh_token(data.get("refresh_token", refresh))
        if refreshed:
            return refreshed
    return data.get("access_token", "")  # Return stale token as last resort


def _refresh_token(refresh_token: str) -> str:
    """Exchange a refresh token for a new access token."""
    try:
        payload = urllib.parse.urlencode({
            "client_id": SLACK_OAUTH_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }).encode()
        req = urllib.request.Request(SLACK_TOKEN_URL, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read())
        if d.get("ok"):
            authed = d.get("authed_user", {})
            token_data = {
                "access_token": d["access_token"],
                "refresh_token": d.get("refresh_token", refresh_token),
                "expires_at": time.time() + d.get("expires_in", 43200) - 60,
                "team":    d.get("team", {}).get("name", ""),
                "team_id": d.get("team", {}).get("id", ""),
                "user":    authed.get("id", ""),
                "user_display_name": authed.get("name", ""),
                "scope":   d.get("scope", ""),
            }
            _save_token(token_data)
            return token_data["access_token"]
    except Exception as e:
        print(f"[SLACK MCP] Token refresh failed: {e}")
    return ""


def is_slack_authenticated() -> bool:
    """Check if we have a valid Slack OAuth token."""
    return bool(get_oauth_token())


def get_slack_auth_status() -> dict:
    """Return Slack auth status for the settings UI."""
    data = _load_token()
    if not data.get("access_token"):
        return {"configured": False}
    return {
        "configured": True,
        "team": data.get("team", ""),
        "user": data.get("user", ""),
        "scope": data.get("scope", ""),
        "expires_at": data.get("expires_at", 0),
    }


# ── OAuth PKCE Flow ──────────────────────────────────────────────────────────
# The official Slack MCP app (client ID 1601185624273) only allows redirect URIs
# on port 3118. We spin up a temporary HTTP server on that port to receive the
# OAuth callback, then exchange the code for a token.

_CALLBACK_PORT = 3118
_CALLBACK_REDIRECT_URI = f"http://localhost:{_CALLBACK_PORT}/callback"

# Pending PKCE state — persisted to file so it survives app restarts/reloads
_PKCE_FILE = Path.home() / ".config" / "slack-mcp" / ".pkce_pending.json"


def _load_pkce() -> dict:
    if _PKCE_FILE.exists():
        try:
            return json.loads(_PKCE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_pkce(data: dict) -> None:
    _PKCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PKCE_FILE.write_text(json.dumps(data))


def _clear_pkce() -> None:
    try:
        _PKCE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def start_oauth(redirect_uri: str = "") -> dict:
    """Generate OAuth authorization URL with PKCE.

    redirect_uri is ignored — we always use http://localhost:3118/callback
    which is registered with the Slack app. A temp server handles the callback.
    """
    # _pending_pkce stored to file (survives app reloads)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)

    _save_pkce({
        "code_verifier": code_verifier,
        "state": state,
    })

    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": SLACK_OAUTH_CLIENT_ID,
        "scope": SLACK_SCOPES.replace(",", " "),
        "user_scope": "",
        "redirect_uri": _CALLBACK_REDIRECT_URI,
        "state": state,
        "granular_bot_scope": "1",
        "single_channel": "0",
        "user_default": "1",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })

    # Start the temporary callback server in a background thread
    import threading
    t = threading.Thread(target=_run_callback_server, daemon=True)
    t.start()

    return {
        "url": f"{SLACK_AUTH_URL}?{params}",
        "state": state,
    }


def _exchange_code(code: str, code_verifier: str) -> dict:
    """Exchange authorization code for access token."""
    try:
        payload = urllib.parse.urlencode({
            "client_id": SLACK_OAUTH_CLIENT_ID,
            "code": code,
            "redirect_uri": _CALLBACK_REDIRECT_URI,
            "code_verifier": code_verifier,
        }).encode()
        req = urllib.request.Request(SLACK_TOKEN_URL, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read())

        if not d.get("ok"):
            return {"ok": False, "error": d.get("error", "unknown_error")}

        authed_user = d.get("authed_user", {})
        token_data = {
            "access_token": authed_user.get("access_token", d.get("access_token", "")),
            "refresh_token": authed_user.get("refresh_token", d.get("refresh_token", "")),
            "expires_at": time.time() + authed_user.get("expires_in", d.get("expires_in", 43200)) - 60,
            "team": d.get("team", {}).get("name", ""),
            "team_id": d.get("team", {}).get("id", ""),
            "user": authed_user.get("id", ""),
            "user_display_name": authed_user.get("name", ""),
            "scope": authed_user.get("scope", d.get("scope", "")),
        }
        _save_token(token_data)
        return {"ok": True, "team": token_data["team"], "user": token_data["user"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _run_callback_server() -> None:
    """Temporary HTTP server on port 3118 to receive OAuth callback."""
    import http.server
    import socketserver

    result_holder = {}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            # _pending_pkce stored to file (survives app reloads)
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            params = urllib.parse.parse_qs(parsed.query)
            code = params.get("code", [""])[0]
            state = params.get("state", [""])[0]
            error = params.get("error", [""])[0]

            if error:
                self._respond(f"<h2>Slack auth failed: {error}</h2>"
                              "<p>Close this window and try again.</p>", ok=False)
                return

            pkce = _load_pkce()
            if not pkce or pkce.get("state") != state:
                self._respond("<h2>Invalid state</h2>"
                              "<p>Close this window and try again.</p>", ok=False)
                return

            code_verifier = pkce["code_verifier"]
            _clear_pkce()

            result = _exchange_code(code, code_verifier)
            if result.get("ok"):
                self._respond(
                    "<h2>Slack connected!</h2>"
                    f"<p>Team: {result.get('team', '')}</p>"
                    "<p>You can close this window.</p>",
                    ok=True
                )
            else:
                self._respond(
                    f"<h2>Auth failed</h2><p>{result.get('error', 'unknown')}</p>"
                    "<p>Close this window and try again.</p>",
                    ok=False
                )
            result_holder["done"] = True

        def _respond(self, body_html: str, ok: bool = True):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            event_type = "slack-auth-ok" if ok else "slack-auth-fail"
            html = (
                "<html><body><script>"
                f"window.opener && window.opener.postMessage({{type:'{event_type}'}},'*');"
                "setTimeout(function(){window.close()},2000);"
                "</script>"
                f"{body_html}</body></html>"
            )
            self.wfile.write(html.encode())

        def log_message(self, fmt, *args):
            pass  # Suppress noisy logs

    try:
        with socketserver.TCPServer(("localhost", _CALLBACK_PORT), CallbackHandler) as httpd:
            httpd.timeout = 120  # 2 min max wait
            while "done" not in result_holder:
                httpd.handle_request()
    except OSError as e:
        print(f"[SLACK OAuth] Could not start callback server on port {_CALLBACK_PORT}: {e}")


def complete_oauth(code: str, state: str) -> dict:
    """Kept for API compatibility — the callback server handles exchange directly."""
    return {"ok": False, "error": "Use the popup flow — callback handled on port 3118"}


# MCP transport removed — all Slack API calls now go direct via _slack_web_api in routes/slack.py
