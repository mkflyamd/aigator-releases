"""Microsoft Graph API client with OAuth2 device code authentication.

Shared module for all m365-* skills. Handles token storage, refresh,
and authenticated Graph API calls using only Python stdlib.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import threading
import httpx

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# ── Per-thread connection pool ─────────────────────────────────────────────────
# httpx.Client is NOT thread-safe. Using threading.local gives each thread its
# own client so concurrent asyncio.to_thread calls never share state.
_http_pool_local = threading.local()

def _get_http_pool() -> httpx.Client:
    client = getattr(_http_pool_local, 'client', None)
    if client is None or client.is_closed:
        _http_pool_local.client = httpx.Client(
            timeout=httpx.Timeout(30.0, read=60.0),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
            follow_redirects=True,
        )
    return _http_pool_local.client

# ── Module-level lock: prevents concurrent threads from double-refreshing token ─
_token_refresh_lock = threading.Lock()
# Microsoft Teams Desktop public client -- request only narrow scopes; the token
# inherits all pre-authorized scopes (Mail, Calendar, People, etc.) automatically
# from the app registration. Requesting broad scopes explicitly can trigger
# AADSTS65002 on some M365 tenants.
DEFAULT_CLIENT_ID = "1fec8e78-bce4-4aaf-ab1b-5451cc387264"
DEFAULT_SCOPES = "Files.ReadWrite.All Sites.ReadWrite.All offline_access"
TOKEN_FILE = Path.home() / ".config" / "microsoft-graph" / "token.json"
OLD_TOKEN_FILE = Path.home() / ".config" / "sharepoint-files" / "token.json"

log = logging.getLogger("graph_client")


# ── Typed exceptions (subclass RuntimeError for backward compatibility) ─────
class GraphAPIError(RuntimeError):
    """Base for all Graph API errors. Carries HTTP status code."""

    def __init__(self, message: str, status_code: int = 0,
                 error_codes: list[int] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_codes = error_codes or []


class GraphAuthError(GraphAPIError):
    """401/403 from Graph — token expired, missing scope, or AADSTS error."""


class GraphThrottleError(GraphAPIError):
    """429 from Graph — caller is being throttled."""

    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message, status_code=429)
        self.retry_after = retry_after


class GraphClient:
    """Microsoft Graph API client with automatic token management."""

    _MAX_RETRIES = 3

    def __init__(self) -> None:
        self._access_token = ""
        self._refresh_token = ""
        self._expires_at = 0.0
        self._client_id = DEFAULT_CLIENT_ID
        self._tenant_id = ""
        self._load_token()

    def _load_token(self) -> None:
        # Clean up any stale .tmp left by a previous crash mid-write.
        # Only delete if older than 60s — avoids racing with another process's write.
        _tmp = TOKEN_FILE.with_suffix(".tmp")
        if _tmp.exists():
            try:
                if time.time() - _tmp.stat().st_mtime > 60:
                    _tmp.unlink()
            except OSError:
                pass
        if not TOKEN_FILE.exists() and OLD_TOKEN_FILE.exists():
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(str(OLD_TOKEN_FILE), str(TOKEN_FILE))
        if TOKEN_FILE.exists():
            try:
                data = json.loads(TOKEN_FILE.read_text())
                self._refresh_token = data.get("refresh_token", "")
                self._client_id = data.get("client_id", DEFAULT_CLIENT_ID)
                self._tenant_id = data.get("tenant_id", "")
                self._access_token = data.get("access_token", "")
                self._expires_at = data.get("expires_at", 0.0)
            except (json.JSONDecodeError, KeyError):
                pass
        env_token = os.environ.get("MS_ACCESS_TOKEN", "")
        if env_token and not self._access_token:
            self._access_token = env_token.removeprefix("Bearer ").strip()
            # Decode JWT exp claim for accurate expiry; fall back to 50 min
            try:
                payload = self._access_token.split(".")[1]
                payload += "=" * (4 - len(payload) % 4)
                claims = json.loads(base64.b64decode(payload))
                self._expires_at = float(claims.get("exp", time.time() + 3000))
            except Exception:
                self._expires_at = time.time() + 3000

    def _save_token(self) -> None:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = TOKEN_FILE.with_suffix(".tmp")
        payload = json.dumps({
            "refresh_token": self._refresh_token,
            "client_id": self._client_id,
            "tenant_id": self._tenant_id,
            "access_token": self._access_token,
            "expires_at": self._expires_at,
        }, indent=2)
        # Open with restricted permissions from creation — no world-readable window
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(payload)
        except Exception:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        os.replace(str(tmp), str(TOKEN_FILE))

    def _refresh(self) -> str:
        if not self._refresh_token or not self._tenant_id:
            return ""
        with _token_refresh_lock:
            # Re-check under lock — another thread may have refreshed already
            if self._access_token and time.time() < self._expires_at:
                return self._access_token
            try:
                data = urllib.parse.urlencode({
                    "client_id": self._client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "scope": DEFAULT_SCOPES,
                }).encode()
                url = f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token"
                req = urllib.request.Request(url, data=data, method="POST")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    d = json.loads(resp.read())
                self._access_token = d["access_token"]
                self._expires_at = time.time() + d.get("expires_in", 3600) - 60
                if "refresh_token" in d:
                    self._refresh_token = d["refresh_token"]
                self._save_token()
                return self._access_token
            except Exception as exc:
                log.warning("Token refresh failed: %s", exc)
                return ""

    def get_token(self) -> str:
        if self._access_token and time.time() < self._expires_at:
            return self._access_token
        token = self._refresh()
        if token:
            return token
        env_token = os.environ.get("MS_ACCESS_TOKEN", "")
        if env_token:
            return env_token.removeprefix("Bearer ").strip()
        return ""

    def is_authenticated(self) -> bool:
        return bool(self.get_token())

    def start_auth(self, tenant_id: str = "organizations") -> dict[str, str]:
        data = urllib.parse.urlencode({
            "client_id": DEFAULT_CLIENT_ID,
            "scope": DEFAULT_SCOPES,
        }).encode()
        url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/devicecode"
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            d = json.loads(resp.read())
        self._client_id = DEFAULT_CLIENT_ID
        self._tenant_id = tenant_id
        return {
            "message": d["message"], "user_code": d["user_code"],
            "url": d["verification_uri"], "device_code": d["device_code"],
            "expires_in": str(d.get("expires_in", 900)),
        }

    def complete_auth(self, device_code: str) -> dict[str, str]:
        tid = self._tenant_id or "organizations"
        url = f"https://login.microsoftonline.com/{tid}/oauth2/v2.0/token"
        for _ in range(24):
            data = urllib.parse.urlencode({
                "client_id": self._client_id,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
            }).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    d = json.loads(resp.read())
                self._access_token = d["access_token"]
                self._refresh_token = d.get("refresh_token", "")
                self._expires_at = time.time() + d.get("expires_in", 3600) - 60
                try:
                    payload = d["access_token"].split(".")[1]
                    payload += "=" * (4 - len(payload) % 4)
                    claims = json.loads(base64.b64decode(payload))
                    self._tenant_id = claims.get("tid", tid)
                except Exception:
                    pass
                self._save_token()
                return {"status": "ok", "message": "Authentication successful! Tokens saved.",
                        "token_file": str(TOKEN_FILE), "scopes": d.get("scope", "")}
            except urllib.error.HTTPError as e:
                body = json.loads(e.read())
                err = body.get("error", "")
                if err == "authorization_pending":
                    time.sleep(5)
                    continue
                return {"status": "error", "error": f"{err}: {body.get('error_description', '')[:200]}"}
        return {"status": "error", "error": "Timed out waiting for user sign-in. Run auth again."}

    def _headers(self) -> dict[str, str]:
        token = self.get_token()
        if not token:
            raise RuntimeError("No valid access token — sign in via Settings.")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Gator/1.0 (Graph integration)",
        }

    def _extract_graph_error(self, status_code: int, body: str) -> GraphAPIError:
        """Parse Graph error JSON → user-facing message + AADSTS codes."""
        msg = body[:200]
        error_codes: list[int] = []
        try:
            err = json.loads(body)
            msg = err.get("error", {}).get("message", msg)
            error_codes = (err.get("error", {}).get("innerError", {})
                           .get("error_codes", []))
            if not error_codes:
                error_codes = err.get("error_codes", [])
        except (json.JSONDecodeError, AttributeError):
            pass

        if status_code in (401, 403):
            guidance = ""
            if 65002 in error_codes:
                guidance = " Scope conflict — try re-authenticating with narrower scopes."
            elif 70016 in error_codes:
                guidance = " Session expired — please sign in again via Settings."
            elif 50013 in error_codes:
                guidance = " Token not yet valid (clock skew) — wait a moment and retry."
            return GraphAuthError(
                f"Graph API {status_code}: {msg}{guidance}",
                status_code=status_code, error_codes=error_codes,
            )
        return GraphAPIError(f"Graph API {status_code}: {msg}",
                             status_code=status_code)

    # ── HTTP methods with retry, connection pooling, typed exceptions ───

    def _request(self, method: str, url: str, *,
                 headers: dict | None = None,
                 content: bytes | None = None,
                 label: str = "") -> httpx.Response:
        """Central request method with retry logic and connection pooling."""
        hdrs = headers or self._headers()
        pool = _get_http_pool()
        last_err: Exception | None = None
        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                resp = pool.request(method, url, headers=hdrs, content=content)
                resp.raise_for_status()
                # Log mutating operations at INFO so they're visible; reads at DEBUG
                _lvl = logging.INFO if method in ("DELETE", "POST", "PATCH", "PUT") else logging.DEBUG
                log.log(_lvl, "Graph %s %s -> %s", method, label or url, resp.status_code)
                return resp
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                body = e.response.text[:500]
                if code in (429, 502, 503, 504) and attempt < self._MAX_RETRIES:
                    retry_after = int(e.response.headers.get("Retry-After", "30"))
                    wait = min(retry_after, 300) if code == 429 else min(2 ** attempt, 15)
                    log.warning("Graph %d on %s %s — retrying in %ds (%d/%d)",
                                code, method, label, wait, attempt, self._MAX_RETRIES)
                    time.sleep(wait)
                    last_err = e
                    continue
                parsed = self._extract_graph_error(code, body)
                # 404 (not found) and 403 (scope missing) are often expected —
                # log at debug to avoid noisy warnings the caller handles anyway.
                if code in (403, 404):
                    log.debug("Graph %s %s -> %s: %s", method, label, code, parsed)
                else:
                    log.warning("Graph %s %s failed: %s", method, label, parsed)
                raise parsed from e
            except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError) as e:
                log.warning("Graph %s %s network error (attempt %d/%d): %s",
                            method, label, attempt, self._MAX_RETRIES, e)
                if attempt < self._MAX_RETRIES:
                    time.sleep(min(2 ** attempt, 10))
                    last_err = e
                    continue
                raise GraphAPIError(f"Network error on {method} {label}: {e}") from e
        raise GraphThrottleError(
            f"Graph {method} {label} throttled after {self._MAX_RETRIES} retries"
        ) from last_err

    def get(self, path: str, params: dict[str, Any] | None = None,
            extra_headers: dict[str, str] | None = None,
            base_url: str | None = None) -> Any:
        url = f"{base_url or GRAPH_BASE}{urllib.parse.quote(path, safe='/:$()\'=,@')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {**self._headers(), **(extra_headers or {})}
        resp = self._request("GET", url, headers=headers, label=path)
        return resp.json()

    def get_absolute(self, url: str, extra_headers: dict[str, str] | None = None) -> Any:
        """GET a fully-formed absolute URL (e.g. a deltaLink or nextLink from Graph)."""
        headers = {**self._headers(), **(extra_headers or {})}
        resp = self._request("GET", url, headers=headers, label="(absolute)")
        return resp.json()

    def get_text(self, path: str, params: dict[str, Any] | None = None,
                 extra_headers: dict[str, str] | None = None,
                 base_url: str | None = None) -> str:
        """GET returning raw response text (for non-JSON endpoints like VTT)."""
        url = f"{base_url or GRAPH_BASE}{urllib.parse.quote(path, safe='/:$()\'=,@')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {**self._headers(), **(extra_headers or {})}
        resp = self._request("GET", url, headers=headers, label=path)
        return resp.text

    def post(self, path: str, body: dict) -> Any:
        url = f"{GRAPH_BASE}{path}"
        resp = self._request("POST", url, content=json.dumps(body).encode(), label=path)
        return resp.json() if resp.content else {"status": "ok", "status_code": resp.status_code}

    def patch(self, path: str, body: dict) -> Any:
        url = f"{GRAPH_BASE}{path}"
        resp = self._request("PATCH", url, content=json.dumps(body).encode(), label=path)
        return resp.json() if resp.content else {"status": "ok", "status_code": resp.status_code}

    def put_binary(self, path: str, data: bytes,
                   content_type: str = "application/octet-stream") -> Any:
        """Upload raw bytes via PUT — used for OneDrive simple upload (<4 MB)."""
        url = f"{GRAPH_BASE}{path}"
        headers = {**self._headers(), "Content-Type": content_type}
        resp = self._request("PUT", url, headers=headers, content=data, label=path)
        return resp.json() if resp.content else {"status": "ok"}

    def delete(self, path: str) -> dict:
        url = f"{GRAPH_BASE}{path}"
        resp = self._request("DELETE", url, label=path)
        return {"status": "deleted", "status_code": resp.status_code}

    def batch(self, requests: list[dict]) -> list[dict]:
        """Execute a Graph $batch request (up to 20 requests per batch).
        Each request: {"id": "1", "method": "GET", "url": "/me/joinedTeams"}
        Returns list of responses: {"id": "1", "status": 200, "body": {...}}
        """
        url = f"{GRAPH_BASE}/$batch"
        # Process in chunks of 20 (Graph limit)
        all_responses = []
        for i in range(0, len(requests), 20):
            chunk = requests[i:i + 20]
            resp = self._request("POST", url, content=json.dumps({"requests": chunk}).encode(), label="$batch")
            data = resp.json()
            all_responses.extend(data.get("responses", []))
        return all_responses
