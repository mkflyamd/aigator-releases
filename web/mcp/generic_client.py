"""Generic MCP client — connects to any MCP server over JSON-RPC 2.0.

Supports two transports:
  - HTTP  : POST JSON-RPC directly to the URL (standard)
  - SSE   : GET /sse to receive the message endpoint, then POST there

Supports auth_type: none | bearer | api_key
"""
from __future__ import annotations

import http.client
import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


_BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

_INIT_PAYLOAD = {
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "aigator", "version": "1.0"},
    },
    "id": 1,
}


def _build_auth_headers(auth_type: str, auth_value: str) -> dict[str, str]:
    if auth_type == "bearer":
        if not auth_value:
            raise ValueError("auth_value must not be empty for auth_type='bearer'")
        return {"Authorization": f"Bearer {auth_value}"}
    if auth_type == "api_key":
        if not auth_value:
            raise ValueError("auth_value must not be empty for auth_type='api_key'")
        return {"X-Api-Key": auth_value}
    return {}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Force all redirects to raise HTTPError so _post can handle them with POST preserved."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirectHandler())


def _parse_response(raw: bytes, content_type: str) -> dict:
    if "text/event-stream" in content_type:
        for line in raw.decode().splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise RuntimeError("No data line in MCP SSE response")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        preview = raw.decode(errors="replace")[:120].strip()
        raise RuntimeError(f"Server returned non-JSON response: {preview!r}")


def _resolve_location(base_url: str, location: str) -> str:
    if location.startswith("http"):
        return location
    parsed = urllib.parse.urlparse(base_url)
    if location.startswith("/"):
        return f"{parsed.scheme}://{parsed.netloc}{location}"
    return base_url.rsplit("/", 1)[0] + "/" + location


def _post(url: str, payload: dict, headers: dict, session_id: str | None = None, _visited: frozenset[str] | None = None) -> tuple[dict, str | None]:
    _visited = _visited or frozenset()
    hdrs = dict(headers)
    if session_id:
        hdrs["mcp-session-id"] = session_id
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with _OPENER.open(req, timeout=15) as resp:
            raw = resp.read()
            content_type = resp.headers.get("Content-Type", "")
            result = _parse_response(raw, content_type)
            sid = resp.headers.get("mcp-session-id")
            return result, sid
    except urllib.error.HTTPError as e:
        # Follow POST-preserving redirects (307/308) and permanent redirects (301/302)
        if e.code in (301, 302, 307, 308):
            location = _resolve_location(url, e.headers.get("Location", ""))
            # Some servers (broken nginx) 307 from https→http but really just want a trailing slash.
            # If location matches url on host+path (ignoring scheme/trailing slash), retry on original scheme + slash.
            if location:
                u, l = urllib.parse.urlparse(url), urllib.parse.urlparse(location)
                if u.netloc == l.netloc and u.path.rstrip("/") == l.path.rstrip("/") and not url.endswith("/"):
                    location = url + "/"
            # Refuse https → http downgrade
            if url.startswith("https://") and location.startswith("http://"):
                raise RuntimeError(
                    f"Server redirected from HTTPS to HTTP ({url} → {location}) — refusing insecure downgrade"
                ) from e
            # Detect redirect loop
            if location in _visited or len(_visited) >= 5:
                raise RuntimeError(
                    f"Redirect loop detected for {url} — server is misconfigured"
                ) from e
            if location:
                return _post(location, payload, headers, session_id, _visited | {url})
        body = e.read().decode()[:300]
        if e.code in (401, 403):
            raise RuntimeError(f"auth_error:{e.code}:{body}") from e
        raise RuntimeError(f"MCP HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        cause = e.reason
        if isinstance(cause, (ssl.SSLError, ssl.CertificateError)):
            raise RuntimeError(f"SSL error — check the URL uses https:// and the server certificate is valid: {cause}") from e
        if isinstance(cause, socket.timeout) or "timed out" in str(e).lower():
            raise RuntimeError(f"Connection timed out — server did not respond within 15 seconds") from e
        if isinstance(cause, (ConnectionRefusedError, OSError)) and "refused" in str(cause).lower():
            raise RuntimeError(f"Connection refused — is the server running at {url}?") from e
        if isinstance(cause, socket.gaierror):
            raise RuntimeError(f"Could not resolve host — check the URL: {cause}") from e
        raise RuntimeError(f"network:{e}") from e
    except http.client.HTTPException as e:
        raise RuntimeError(f"network:{e}") from e


def _sse_connect(sse_url: str, auth_headers: dict) -> tuple[str, str | None]:
    """SSE transport handshake — GET the SSE endpoint, parse the 'endpoint' event."""
    hdrs = {k: v for k, v in auth_headers.items() if k.lower() != "content-type"}
    hdrs["Accept"] = "text/event-stream"
    hdrs["Cache-Control"] = "no-cache"

    req = urllib.request.Request(sse_url, headers=hdrs, method="GET")
    try:
        with _OPENER.open(req, timeout=15) as resp:
            session_id = resp.headers.get("mcp-session-id")
            last_event: str | None = None

            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if line.startswith("event:"):
                    last_event = line[6:].strip()
                elif line.startswith("data:") and last_event == "endpoint":
                    endpoint_path = line[5:].strip()
                    return _resolve_location(sse_url, endpoint_path), session_id
                elif not line:
                    last_event = None

    except (urllib.error.URLError, http.client.HTTPException) as e:
        raise RuntimeError(f"SSE handshake failed: {e}") from e

    raise RuntimeError("SSE server did not send an endpoint event")


def _is_sse_trigger(msg: str, cause: BaseException | None) -> bool:
    """Return True only for errors that genuinely indicate an SSE server."""
    # RemoteDisconnected: server closed connection without response (SSE servers do this on POST)
    if isinstance(cause, http.client.RemoteDisconnected):
        return True
    # 405 Method Not Allowed: server explicitly rejects POST, may accept SSE GET
    if "405" in msg:
        return True
    return False


class GenericMCPClient:
    def __init__(self, cfg: dict) -> None:
        auth_type = cfg.get("auth_type", "none")
        auth_value = cfg.get("auth_value", "")
        if auth_type in ("bearer", "api_key") and not auth_value:
            raise ValueError(f"auth_value is required for auth_type='{auth_type}'")
        self._cfg = cfg
        self._url = cfg["url"].rstrip("/")
        self._msg_url = self._url
        extra = {k: v for k, v in cfg.get("extra_headers", {}).items()
                 if k.lower() not in ("content-type", "accept")}
        self._headers = {**_BASE_HEADERS, **_build_auth_headers(auth_type, auth_value), **extra}
        self._session_id: str | None = None
        self._init_result: dict | None = None
        self._connect()

    def _unreachable_msg(self) -> str:
        name = self._cfg.get("name", self._url)
        return f"{name} is temporarily unreachable — check Settings > Connections."

    def _connect(self) -> dict:
        """Establish session: try direct HTTP POST first, fall back to SSE transport."""
        try:
            result, sid = _post(self._url, _INIT_PAYLOAD, self._headers)
        except RuntimeError as e:
            msg = str(e)
            cause = e.__cause__
            if _is_sse_trigger(msg, cause):
                msg_url, sid = _sse_connect(self._url, self._headers)
                self._msg_url = msg_url
                result, new_sid = _post(self._msg_url, _INIT_PAYLOAD, self._headers, sid)
                if "error" in result:
                    raise RuntimeError(f"MCP init failed: {result['error']}")
                self._session_id = new_sid or sid
                self._init_result = result
                return result
            raise

        if "error" in result:
            raise RuntimeError(f"MCP init failed: {result['error']}")
        self._session_id = sid
        self._init_result = result
        return result

    def server_info(self) -> dict:
        # Use cached init result — avoids a second handshake
        result = self._init_result or {}
        return result.get("result", {}).get("serverInfo", {})

    def list_tools(self) -> list[dict]:
        payload = {"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 3}
        result, _ = _post(self._msg_url, payload, self._headers, self._session_id)
        return result.get("result", {}).get("tools", [])

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> str:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
            "id": 2,
        }
        try:
            result, _ = _post(self._msg_url, payload, self._headers, self._session_id)
        except RuntimeError as e:
            msg = str(e)
            if msg.startswith("auth_error:"):
                name = self._cfg.get("name", self._url)
                raise RuntimeError(
                    f"Could not authenticate with {name} — check your token in Settings > Connections."
                ) from e
            raise RuntimeError(self._unreachable_msg()) from e
        except Exception as e:
            raise RuntimeError(self._unreachable_msg()) from e

        if "error" in result:
            err = result["error"]
            if err.get("code") in (-32600, -32001):
                try:
                    self._connect()
                    result, _ = _post(self._msg_url, payload, self._headers, self._session_id)
                except Exception:
                    raise RuntimeError(self._unreachable_msg())
                if "error" in result:
                    raise RuntimeError(self._unreachable_msg())
            else:
                raise RuntimeError(self._unreachable_msg())

        content = result.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
