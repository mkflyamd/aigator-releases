"""Generic MCP client — connects to any MCP server using the official MCP Python SDK.

Supports two transports (auto-detected):
  - Streamable HTTP  : tried first (modern servers)
  - SSE              : fallback when server returns 405 or drops the connection

Supports auth_type: none | bearer | api_key | basic
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from typing import Any

import httpx
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.sse import sse_client

from oauth.dcr import parse_resource_metadata_url

_log = logging.getLogger(__name__)


class OAuthRequiredError(Exception):
    """Raised when an MCP server responds with 401 and advertises OAuth via WWW-Authenticate."""
    def __init__(self, metadata_url: str) -> None:
        super().__init__(f"OAuth required — resource metadata: {metadata_url}")
        self.metadata_url = metadata_url


_BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    # Cloudflare-protected hosts (e.g. Atlassian, GitHub) block the default
    # `Python-urllib/3.x` UA as a known scraper signature (Error 1010). Identify
    # as a real client so we're not pre-filtered before the auth header is read.
    "User-Agent": "aigator/1.0 (MCP-Client)",
}

_AUTH_KEYWORDS = (
    "unauthorized", "unauthenticated", "api key", "apikey", "api-key",
    "token", "auth", "forbidden", "403", "401",
)


def _build_auth_headers(auth_type: str, auth_value: str) -> dict[str, str]:
    if auth_type == "bearer":
        if not auth_value:
            raise ValueError("auth_value must not be empty for auth_type='bearer'")
        return {"Authorization": f"Bearer {auth_value}"}
    if auth_type == "api_key":
        if not auth_value:
            raise ValueError("auth_value must not be empty for auth_type='api_key'")
        return {"X-Api-Key": auth_value}
    if auth_type == "basic":
        if not auth_value or ":" not in auth_value:
            raise ValueError("auth_value for auth_type='basic' must be 'identifier:secret' (e.g. 'email@example.com:api_token')")
        encoded = base64.b64encode(auth_value.encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}
    return {}


def _flatten_eg(e: BaseException) -> list[BaseException]:
    """Recursively flatten nested ExceptionGroups into a flat list of leaf exceptions.

    anyio TaskGroups can produce ExceptionGroup(ExceptionGroup(real_error)) — one level of
    unwrap isn't enough. This walks the full tree and returns only non-EG leaves.
    """
    out: list[BaseException] = []
    if isinstance(e, BaseExceptionGroup):
        for sub in e.exceptions:
            out.extend(_flatten_eg(sub))
    else:
        out.append(e)
    return out


def _first_typed_leaf(e: BaseException) -> BaseException:
    """Return the first leaf exception from a (possibly nested) ExceptionGroup, else e itself."""
    leaves = _flatten_eg(e)
    return leaves[0] if leaves else e


def _check_auth_http_error(e: httpx.HTTPStatusError, url: str, user_supplied_auth: bool = False) -> None:
    """Raise OAuthRequiredError or auth RuntimeError for 401/403 responses.

    When ``user_supplied_auth`` is True the caller already attached credentials
    (Basic, Bearer, API key, or a hand-rolled header). A 401 in that case means
    those creds were rejected — escalating to OAuth would mis-route the user to
    a sign-in flow they didn't ask for (e.g. Atlassian 401s on bad Basic creds
    while still advertising Bearer in WWW-Authenticate).
    """
    status = e.response.status_code
    if status in (401, 403):
        wa = e.response.headers.get("www-authenticate", "")
        try:
            body = e.response.text[:300]
        except Exception:
            body = e.response.content[:300].decode("utf-8", errors="replace") if e.response.content else ""
        # Cloudflare 1010 = UA-based block
        if "error_code" in body and "1010" in body:
            raise RuntimeError(
                "Blocked by Cloudflare (Error 1010). The MCP server's edge layer "
                "rejected our request signature. This is a client-side issue, not "
                "an auth problem — file a bug if you see this."
            ) from e
        if status == 401 and wa and not user_supplied_auth:
            metadata_url = parse_resource_metadata_url(wa)
            if metadata_url:
                raise OAuthRequiredError(metadata_url) from e
        if user_supplied_auth and status == 401:
            raise RuntimeError(
                f"auth_error:{status}:Credentials were rejected by the server. "
                "Double-check the token / email:api_token in the Headers field."
            ) from e
        raise RuntimeError(f"auth_error:{status}:{body}") from e


class GenericMCPClient:
    """MCP client for connecting to any MCP server.

    All public methods are synchronous and use asyncio.run() internally — call only from threads with no running event loop.
    Each method call opens a new transport connection; there is no persistent session between calls.
    """

    def __init__(self, cfg: dict) -> None:
        auth_type = cfg.get("auth_type", "none")
        auth_value = cfg.get("auth_value", "")
        self._cfg = cfg
        # Do NOT strip the trailing slash. Some MCP servers (e.g. Nabu) 307
        # redirect `/path` → `/path/` AND downgrade scheme to http on the
        # Location header, which httpx then loops on. Pass the URL exactly
        # as the user gave it — the server's routing rules know best.
        self._url = cfg["url"]
        extra = {k: v for k, v in cfg.get("extra_headers", {}).items()
                 if k.lower() not in ("content-type", "accept")}
        # If the user already supplied the credential as an extra header (e.g.
        # pasted JSON config with templated `Authorization: Basic {email}:{tok}`
        # then filled the placeholders), the header IS the credential — skip
        # the auto-generation path so `_build_auth_headers` doesn't reject the
        # request demanding a separately-typed auth_value.
        extra_keys = {k.lower() for k in extra}
        has_authz = "authorization" in extra_keys
        has_apikey = any(
            k in ("x-api-key", "api-key", "apikey") or k.endswith("-api-key") or k.endswith("-key")
            for k in extra_keys
        )
        effective_auth_type = auth_type
        if (auth_type in ("bearer", "basic") and has_authz) or (auth_type == "api_key" and has_apikey):
            effective_auth_type = "none"
        if effective_auth_type in ("bearer", "api_key") and not auth_value:
            raise ValueError(f"auth_value is required for auth_type='{auth_type}'")
        self._headers = {**_BASE_HEADERS, **_build_auth_headers(effective_auth_type, auth_value), **extra}
        # Track whether the user provided their own credentials. A 401 with
        # user-supplied creds means "rejected" — not "switch to OAuth", even if
        # the server advertises Bearer in WWW-Authenticate. See _check_auth_http_error.
        self._user_supplied_auth = (
            has_authz or has_apikey or auth_type in ("basic", "bearer", "api_key")
        )
        # Self-correct templated Basic auth: many pasted JSON configs use
        # `Authorization: Basic {email}:{api_token}` (or Atlassian's `{email}@{api_token}`)
        # and expect substitution to produce the wire value. Real Basic auth
        # requires base64(email:token). Detect the unencoded form and encode it
        # in place so the server sees a valid header.
        for k in list(self._headers.keys()):
            if k.lower() != "authorization":
                continue
            v = self._headers[k]
            if not isinstance(v, str) or not v.lower().startswith("basic "):
                continue
            payload = v[6:].strip()
            _log.debug("[mcp-diag] basic-fix payload_len=%d has_colon=%s payload_head=%r",
                       len(payload), ":" in payload, payload[:12])
            if not payload:
                continue
            # If it already decodes as valid base64, leave it alone.
            try:
                base64.b64decode(payload, validate=True)
                _log.debug("[mcp-diag] basic-fix payload decoded as valid b64 — skipping encode")
                continue
            except (ValueError, binascii.Error):
                pass
            # Not base64. Normalize the email/token separator: Atlassian's
            # public docs show both `email:api_token` and `email@api_token`, so
            # users paste either. Find the email, then strip any leftover
            # separator chars (`@`, `:`, whitespace) from the start of the token.
            if ":" not in payload:
                import re as _re
                m = _re.match(r"^([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})(.+)$", payload)
                if m:
                    token = m.group(2).lstrip("@: \t")
                    payload = m.group(1) + ":" + token
                    _log.debug("[mcp-diag] basic-fix injected ':' after email — new_payload_len=%d", len(payload))
                else:
                    _log.debug("[mcp-diag] basic-fix no colon and no email pattern — encoding as-is")
            else:
                # Has a colon already — only strip a leading `@` on the token
                # side (from a `{email}@{token}` template that also slipped a
                # literal `:` in). Don't touch other characters: real tokens
                # can contain `:` and we'd corrupt them.
                local, sep, rest = payload.partition(":")
                if rest.startswith("@"):
                    payload = local + sep + rest.lstrip("@")
            self._headers[k] = "Basic " + base64.b64encode(payload.encode("utf-8")).decode("ascii")
            _log.debug("[mcp-diag] basic-fix encoded — new_len=%d", len(self._headers[k]))
        self._transport: str | None = None
        self._server_info_cache: dict = {}
        # DIAG: log exactly what we're about to send (credentials masked).
        # Remove once the AMD/Atlassian basic-auth path is confirmed working.
        try:
            _dbg = {}
            for hk, hv in self._headers.items():
                if hk.lower() == "authorization" and isinstance(hv, str):
                    parts = hv.split(" ", 1)
                    scheme = parts[0] if parts else "?"
                    rest = parts[1] if len(parts) > 1 else ""
                    if scheme.lower() == "basic" and rest:
                        try:
                            decoded = base64.b64decode(rest, validate=True).decode("utf-8", "replace")
                            _dbg[hk] = f"{scheme} <b64:len={len(rest)} decodes-to:{decoded[:3]}***:***{decoded[-3:] if len(decoded) > 6 else ''}>"
                        except Exception:
                            _dbg[hk] = f"{scheme} <RAW-NOT-B64:len={len(rest)} starts:{rest[:8]!r}>"
                    else:
                        _dbg[hk] = f"{scheme} <len={len(rest)}>"
                elif hk.lower() in ("x-api-key", "api-key", "apikey") or hk.lower().endswith("-api-key") or hk.lower().endswith("-key"):
                    _dbg[hk] = f"<len={len(str(hv))}>"
                else:
                    _dbg[hk] = hv
            _log.debug("[mcp-diag] url=%r auth_type=%r->%r outgoing_headers=%s",
                       self._url, auth_type, effective_auth_type, _dbg)
        except Exception as _e:
            _log.debug("[mcp-diag] failed to dump headers: %s", _e)
        self._connect()

    def _connect(self) -> None:
        self._server_info_cache = asyncio.run(self._async_connect())

    async def _async_connect(self) -> dict:
        """Try streamable HTTP first; fall back to SSE on 405 or RemoteProtocolError."""
        try:
            return await self._run_streamable()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 405:
                _log.debug("[mcp] streamable HTTP got 405 — falling back to SSE for %s", self._url)
                return await self._run_sse()
            # 401/403 — check for OAuth or raise auth error
            _check_auth_http_error(e, self._url, self._user_supplied_auth)
            raise  # unreachable but satisfies type checker
        except httpx.RemoteProtocolError:
            _log.debug("[mcp] streamable HTTP RemoteProtocolError — falling back to SSE for %s", self._url)
            return await self._run_sse()
        except (OAuthRequiredError, RuntimeError):
            raise  # Re-raise — do not let outer `except Exception` swallow these
        except httpx.ConnectError as e:
            msg = str(e).lower()
            if "ssl" in msg or "certificate" in msg:
                raise RuntimeError(f"SSL error — check the URL uses https:// and the server certificate is valid: {e}") from e
            if "refused" in msg or "connection refused" in msg:
                raise RuntimeError(f"Connection refused — is the server running at {self._url}?") from e
            if "getaddrinfo" in msg or "name or service not known" in msg or "nodename nor servname" in msg:
                raise RuntimeError(f"Could not resolve host — check the URL: {e}") from e
            raise RuntimeError(f"network:{e}") from e
        except httpx.TimeoutException as e:
            raise RuntimeError("Connection timed out — server did not respond within 15 seconds") from e
        except BaseException as e:
            # anyio wraps task-group failures in ExceptionGroup (possibly nested).
            # Find the first meaningful leaf and re-dispatch through our typed handlers.
            leaves = _flatten_eg(e)
            _log.debug("[mcp] _async_connect caught %s — %d leaf(s): %s",
                       type(e).__name__, len(leaves),
                       [type(x).__name__ for x in leaves])
            # Prefer an HTTPStatusError leaf (auth signal) over a generic ConnectError
            sub = next((x for x in leaves if isinstance(x, httpx.HTTPStatusError)), None) or (leaves[0] if leaves else e)
            if isinstance(sub, httpx.HTTPStatusError):
                if sub.response.status_code == 405:
                    return await self._run_sse()
                status = sub.response.status_code
                if status in (401, 403):
                    wa = sub.response.headers.get("www-authenticate", "")
                    if status == 401 and wa and not self._user_supplied_auth:
                        metadata_url = parse_resource_metadata_url(wa)
                        if metadata_url:
                            raise OAuthRequiredError(metadata_url) from e
                    if self._user_supplied_auth and status == 401:
                        raise RuntimeError(
                            f"auth_error:{status}:Credentials were rejected by the server. "
                            "Double-check the token / email:api_token in the Headers field."
                        ) from e
                    raise RuntimeError(f"auth_error:{status}:") from e
                raise RuntimeError(f"network:HTTP {status}") from e
            if isinstance(sub, httpx.RemoteProtocolError):
                return await self._run_sse()
            if isinstance(sub, httpx.ConnectError):
                msg = str(sub).lower()
                if "ssl" in msg or "certificate" in msg:
                    raise RuntimeError(f"SSL error — check the URL uses https:// and the server certificate is valid: {sub}") from e
                if "refused" in msg or "connection refused" in msg:
                    raise RuntimeError(f"Connection refused — is the server running at {self._url}?") from e
                if "getaddrinfo" in msg or "name or service not known" in msg or "nodename nor servname" in msg:
                    raise RuntimeError(f"Could not resolve host — check the URL: {sub}") from e
                raise RuntimeError(f"network:{sub}") from e
            if isinstance(sub, httpx.TimeoutException):
                raise RuntimeError("Connection timed out — server did not respond within 15 seconds") from e
            if isinstance(sub, (OAuthRequiredError, RuntimeError)):
                raise sub
            if isinstance(sub, McpError):
                # "Session terminated" / similar — server closed the connection
                # during initialize. Causes vary: (a) URL has trailing junk and
                # 404s, (b) server requires a header up-front, or (c) the
                # server accepts the connect but expects a separate auth tool
                # call (e.g. Nabu's set_nabu_credentials). Don't over-prescribe.
                msg = str(sub)
                if "session terminated" in msg.lower() or "session closed" in msg.lower():
                    raise RuntimeError(
                        f"auth_error:session_terminated:Server at {self._url} closed the "
                        "connection before completing the handshake. Common causes: the URL "
                        "has a typo (extra characters, missing path), the server needs a "
                        "header you haven't set yet, or it's temporarily down. Double-check "
                        "the URL and add any required Headers below before retrying."
                    ) from e
                raise RuntimeError(f"MCP protocol error: {msg}") from e
            raise RuntimeError(f"network:{type(sub).__name__}: {sub}") from e

    async def _run_streamable(self) -> dict:
        async with streamablehttp_client(self._url, headers=self._headers, timeout=30) as (r, w, _):
            async with ClientSession(r, w) as session:
                result = await session.initialize()
                self._transport = "streamable_http"
                si = result.serverInfo
                return {"name": getattr(si, "name", ""), "version": getattr(si, "version", "")} if si else {}

    async def _run_sse(self) -> dict:
        async with sse_client(self._url, headers=self._headers, timeout=10, sse_read_timeout=30) as (r, w):
            async with ClientSession(r, w) as session:
                result = await session.initialize()
                self._transport = "sse"
                si = result.serverInfo
                return {"name": getattr(si, "name", ""), "version": getattr(si, "version", "")} if si else {}

    def server_info(self) -> dict:
        return self._server_info_cache

    def list_tools(self) -> list[dict]:
        # Must be called from a non-async context (thread pool / sync route handler).
        # asyncio.run() creates a new event loop; calling from an async context raises RuntimeError.
        return asyncio.run(self._async_list_tools())

    async def _async_list_tools(self) -> list[dict]:
        try:
            return await self._do_list_tools()
        except McpError as e:
            if e.error.code in (-32600, -32001):
                _log.info("[mcp] session expired (code %d) during list_tools — reconnecting", e.error.code)
                try:
                    self._server_info_cache = await self._async_connect()
                    return await self._do_list_tools()
                except OAuthRequiredError:
                    raise  # OAuth re-auth signal must reach the user
                except Exception:
                    raise RuntimeError(self._unreachable_msg())
            raise RuntimeError(self._unreachable_msg()) from e
        except httpx.HTTPStatusError as e:
            _check_auth_http_error(e, self._url, self._user_supplied_auth)
            raise RuntimeError(self._unreachable_msg()) from e
        except (OAuthRequiredError, RuntimeError):
            raise  # Re-raise — do not let outer `except Exception` swallow these
        except BaseException as e:
            leaves = _flatten_eg(e)
            _log.debug("[mcp] _async_list_tools caught %s — leaves: %s",
                       type(e).__name__, [type(x).__name__ for x in leaves])
            http_leaf = next((x for x in leaves if isinstance(x, httpx.HTTPStatusError)), None)
            if http_leaf is not None:
                _check_auth_http_error(http_leaf, self._url, self._user_supplied_auth)
            raise RuntimeError(self._unreachable_msg()) from e

    async def _do_list_tools(self) -> list[dict]:
        run_fn = self._run_streamable_op if self._transport == "streamable_http" else self._run_sse_op

        async def _op(session: ClientSession) -> list[dict]:
            result = await session.list_tools()
            return [t.model_dump(exclude_none=True) for t in result.tools]

        return await run_fn(_op)

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> str:
        # Must be called from a non-async context (thread pool / sync route handler).
        # asyncio.run() creates a new event loop; calling from an async context raises RuntimeError.
        return asyncio.run(self._async_call(tool, arguments))

    async def _async_call(self, tool: str, arguments: dict[str, Any] | None) -> str:
        args = arguments or {}
        try:
            return await self._do_call(tool, args)
        except McpError as e:
            if e.error.code in (-32600, -32001):
                _log.info("[mcp] session expired (code %d) during call — reconnecting", e.error.code)
                try:
                    self._server_info_cache = await self._async_connect()
                    return await self._do_call(tool, args)
                except OAuthRequiredError:
                    raise  # OAuth re-auth signal must reach the user
                except Exception:
                    raise RuntimeError(self._unreachable_msg())
            err_msg = str(e.error.message)
            if any(kw in err_msg.lower() for kw in _AUTH_KEYWORDS):
                name = self._cfg.get("name", self._url)
                # Preserve the server's original text — it often names the exact
                # header/credential needed (e.g. Nabu says "configure 'headers':
                # {'x-nabu-key': '<key>'}"). Prefix with "auth_error:" so the
                # manager layer flags this and the chat UI offers an Edit link.
                raise RuntimeError(f"auth_error:{name}:{err_msg}") from e
            raise RuntimeError(self._unreachable_msg()) from e
        except httpx.HTTPStatusError as e:
            _check_auth_http_error(e, self._url, self._user_supplied_auth)
            raise RuntimeError(self._unreachable_msg()) from e
        except (OAuthRequiredError, RuntimeError):
            raise  # Re-raise — do not let outer `except Exception` swallow these
        except BaseException as e:
            leaves = _flatten_eg(e)
            for leaf in leaves:
                if isinstance(leaf, McpError):
                    msg = str(getattr(leaf.error, "message", ""))
                    if any(kw in msg.lower() for kw in _AUTH_KEYWORDS):
                        name = self._cfg.get("name", self._url)
                        raise RuntimeError(f"auth_error:{name}:{msg}") from e
            http_leaf = next((x for x in leaves if isinstance(x, httpx.HTTPStatusError)), None)
            if http_leaf is not None:
                _check_auth_http_error(http_leaf, self._url, self._user_supplied_auth)
            raise RuntimeError(self._unreachable_msg()) from e

    async def _do_call(self, tool: str, arguments: dict) -> str:
        run_fn = self._run_streamable_op if self._transport == "streamable_http" else self._run_sse_op

        async def _op(session: ClientSession) -> str:
            result = await session.call_tool(tool, arguments)
            text = "\n".join(
                item.text for item in result.content
                if getattr(item, "type", None) == "text" and hasattr(item, "text")
            )
            # MCP servers signal failures via isError=True with the message in
            # content (e.g. Nabu's "API key required"). Raise so the auth-aware
            # exception path in _async_call can classify and tag it.
            if getattr(result, "isError", False):
                raise McpError(ErrorData(code=-32602, message=text or "Tool call failed"))
            return text

        return await run_fn(_op)

    def call_probe(self, tool: str, arguments: dict[str, Any] | None = None) -> tuple[bool, str]:
        """Probe-mode call: returns (is_error, text) using the structural
        `CallToolResult.isError` flag. Unlike `call()`, never raises for
        tool-level errors — the caller decides what to do with them.
        """
        return asyncio.run(self._async_call_probe(tool, arguments or {}))

    async def _async_call_probe(self, tool: str, arguments: dict) -> tuple[bool, str]:
        run_fn = self._run_streamable_op if self._transport == "streamable_http" else self._run_sse_op

        async def _op(session: ClientSession) -> tuple[bool, str]:
            result = await session.call_tool(tool, arguments)
            text = "\n".join(
                item.text for item in result.content
                if getattr(item, "type", None) == "text" and hasattr(item, "text")
            )
            return bool(getattr(result, "isError", False)), text

        try:
            return await run_fn(_op)
        except McpError as e:
            # Some servers raise instead of setting isError. Surface as error.
            return True, str(getattr(e.error, "message", "")) or self._unreachable_msg()

    async def _run_streamable_op(self, op):
        """Open a fresh streamable HTTP session and run op(session)."""
        async with streamablehttp_client(self._url, headers=self._headers, timeout=30) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                return await op(session)

    async def _run_sse_op(self, op):
        """Open a fresh SSE session and run op(session)."""
        async with sse_client(self._url, headers=self._headers, timeout=10, sse_read_timeout=30) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                return await op(session)

    def _unreachable_msg(self) -> str:
        name = self._cfg.get("name", self._url)
        return f"{name} is temporarily unreachable — check Settings > Connections."

    def close(self) -> None:
        pass
