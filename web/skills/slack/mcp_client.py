"""Slack MCP client — connects to the official Slack MCP server.

Transport: Streamable HTTP (JSON-RPC 2.0 over SSE)
Endpoint:  https://mcp.slack.com/mcp
Auth:      OAuth 2.0 with PKCE (user-scoped tokens stored locally)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# ── Official Slack MCP ────────────────────────────────────────────────────────
MCP_URL = "https://mcp.slack.com/mcp"
# Client ID from the official Slack plugin for Claude Code
SLACK_OAUTH_CLIENT_ID = "1601185624273.8899143856786"
SLACK_AUTH_URL = "https://slack.com/oauth/v2_user/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.user.access"
SLACK_SCOPES = (
    "search:read.public,search:read.private,search:read.mpim,search:read.im,"
    "search:read.files,search:read.users,chat:write,"
    "channels:history,groups:history,mpim:history,im:history,"
    "canvases:read,canvases:write,users:read,users:read.email,"
    "reactions:write,reactions:read,emoji:read,files:read,"
    "channels:write,groups:write,im:write,mpim:write,"
    "channels:read,groups:read,mpim:read"
)

TOKEN_FILE = Path.home() / ".config" / "slack-mcp" / "token.json"

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

_UNREACHABLE_MSG = (
    "Slack MCP server is temporarily unreachable (network issue). "
    "No token or sign-in action is needed — this is a connectivity problem on the server side. "
    "Try again in a moment."
)
_AUTH_LIKE_KEYWORDS = {"invalid_auth", "token_expired", "not_authed", "account_inactive", "invalid_token"}


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
    """Save OAuth token to disk with restrictive permissions."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(data, indent=2))
    try:
        os.chmod(str(TOKEN_FILE), 0o600)
    except OSError:
        pass  # Windows may not support chmod


def get_oauth_token() -> str:
    """Get a valid OAuth access token, refreshing if expired."""
    data = _load_token()
    if not data.get("access_token"):
        return ""
    # Check expiry (with 60s buffer)
    if data.get("expires_at", 0) > time.time() + 60:
        return data["access_token"]
    # Try refresh
    refresh = data.get("refresh_token", "")
    if refresh:
        refreshed = _refresh_token(refresh)
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
            token_data = {
                "access_token": d["access_token"],
                "refresh_token": d.get("refresh_token", refresh_token),
                "expires_at": time.time() + d.get("expires_in", 43200) - 60,
                "team": d.get("team", {}).get("name", ""),
                "user": d.get("authed_user", {}).get("id", ""),
                "scope": d.get("scope", ""),
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
            "scope": authed_user.get("scope", d.get("scope", "")),
        }
        _save_token(token_data)

        # Reset MCP client so it reconnects with new token
        global _client
        _client = None

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


# ── MCP Transport ────────────────────────────────────────────────────────────

def _parse_response(raw: bytes, content_type: str) -> dict:
    """Parse MCP response — handles both plain JSON and SSE formats."""
    if "text/event-stream" in content_type:
        for line in raw.decode().splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise RuntimeError("No data line in MCP SSE response")
    return json.loads(raw)


def _post(payload: dict, session_id: str | None = None, token: str = "") -> tuple[dict, str | None]:
    headers = dict(_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session_id:
        headers["mcp-session-id"] = session_id
    data = json.dumps(payload).encode()
    req = urllib.request.Request(MCP_URL, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            content_type = resp.headers.get("Content-Type", "")
            result = _parse_response(raw, content_type)
            sid = resp.headers.get("mcp-session-id")
            return result, sid
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        raise RuntimeError(f"MCP HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(_UNREACHABLE_MSG) from e


class SlackMCPClient:
    """Session-aware MCP client for the official Slack MCP server."""

    def __init__(self) -> None:
        self._session_id: str | None = None
        self._token = get_oauth_token()
        if not self._token:
            raise RuntimeError("Slack not authenticated — sign in via Settings.")
        self._connect()

    def _connect(self) -> None:
        self._token = get_oauth_token()
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "aigator", "version": "1.0"},
            },
            "id": 1,
        }
        result, sid = _post(payload, token=self._token)
        if "error" in result:
            raise RuntimeError(f"MCP init failed: {result['error']}")
        self._session_id = sid

    def list_tools(self) -> list[dict]:
        """Discover available tools from the MCP server."""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": 3,
        }
        result, _ = _post(payload, self._session_id, self._token)
        return result.get("result", {}).get("tools", [])

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> str:
        """Call an MCP tool and return the text result."""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
            "id": 2,
        }
        try:
            result, _ = _post(payload, self._session_id, self._token)
        except Exception as e:
            print(f"[SLACK MCP] Network error: {e}")
            raise RuntimeError(_UNREACHABLE_MSG) from e
        if "error" in result:
            err = result["error"]
            # Session expired — reconnect once and retry
            if err.get("code") in (-32600, -32001):
                try:
                    self._connect()
                    result, _ = _post(payload, self._session_id, self._token)
                except Exception as e:
                    print(f"[SLACK MCP] Reconnect failed: {e}")
                    raise RuntimeError(_UNREACHABLE_MSG)
                if "error" in result:
                    print(f"[SLACK MCP] Error after reconnect: {result['error']}")
                    raise RuntimeError(_UNREACHABLE_MSG)
            else:
                print(f"[SLACK MCP] Server error: {err}")
                raise RuntimeError(_UNREACHABLE_MSG)
        content = result.get("result", {}).get("content", [])
        text = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
        text_lower = text.lower()
        if any(kw in text_lower for kw in _AUTH_LIKE_KEYWORDS):
            return _UNREACHABLE_MSG
        return text


# Module-level singleton — one session per worker process
_client: SlackMCPClient | None = None


def get_slack_mcp() -> SlackMCPClient:
    global _client
    if _client is None:
        try:
            _client = SlackMCPClient()
        except Exception:
            _client = None
            raise RuntimeError(_UNREACHABLE_MSG)
    return _client
