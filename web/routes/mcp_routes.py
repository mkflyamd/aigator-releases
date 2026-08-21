"""MCP connection management routes."""

import dataclasses
import logging
import os
import socket
import subprocess
import sys
import time
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from mcp.manager import (
    add_or_update,
    remove,
    health_check,
    list_with_status,
    complete_pending_secrets,
    _load_connections,
)
from mcp.normalizer import normalize, NormalizeResult
from mcp.url_fetcher import url_fetcher as _real_fetcher
from mcp.auth_probe import (
    detect_auth_type,
    extract_auth_from_headers,
    infer_auth_type_from_headers,
)

from oauth import (
    discover_and_register,
    register_byoc_provider,
    start_flow,
    poll as oauth_poll,
    forget as oauth_forget,
    handle_callback,
    CALLBACK_URI,
)

router = APIRouter()


class MCPConnectionRequest(BaseModel):
    transport: Literal["http", "stdio"] = "http"
    # http fields
    url: str = ""
    auth_type: str = "none"  # none | bearer | api_key | basic | oauth2
    auth_value: str = ""
    headers: dict[str, str] = {}
    oauth_provider_id: str = ""  # set when auth_type=oauth2
    # stdio fields
    command: str = ""
    args: list[str] = []
    env: dict[str, str] = {}
    # common
    name: str = ""  # empty = auto-detect from server
    connection_id: str = ""  # set on edit to keep id stable across rename


@router.get("/api/config/mcp")
def list_connections():
    return {"connections": list_with_status()}


@router.post("/api/config/mcp")
def add_connection(req: MCPConnectionRequest):
    logger.info(
        "save transport=%s name=%r url=%r command=%r args=%r",
        req.transport,
        req.name,
        req.url,
        req.command,
        req.args,
    )
    if req.transport == "stdio":
        if not req.command.strip():
            raise HTTPException(
                status_code=400, detail="command is required for stdio transport"
            )
    else:
        if not req.url.strip():
            raise HTTPException(status_code=400, detail="URL is required")
        # On edit, blank credential fields mean "keep existing" — the manager fills them in.
        is_edit = bool(req.connection_id.strip())
        # If the user supplies the credential via an explicit Authorization
        # header (common when pasting JSON configs with {placeholder}
        # templates), don't also demand auth_value — the header IS the
        # credential. This skips validation for bearer/api_key/basic when an
        # Authorization header is present.
        has_authz_header = any(
            str(k).lower() == "authorization" for k in (req.headers or {})
        )
        has_apikey_header = any(
            str(k).lower() in ("x-api-key", "api-key", "apikey")
            or str(k).lower().endswith("-api-key")
            or str(k).lower().endswith("-key")
            for k in (req.headers or {})
        )
        if not is_edit:
            if (
                req.auth_type in ("bearer", "api_key")
                and not req.auth_value.strip()
                and not (has_authz_header or has_apikey_header)
            ):
                raise HTTPException(
                    status_code=400, detail="Token/key is required for this auth type"
                )
            if req.auth_type == "basic" and not has_authz_header:
                if not req.auth_value.strip() or ":" not in req.auth_value:
                    raise HTTPException(
                        status_code=400,
                        detail="Basic auth requires 'identifier:secret' (e.g. 'email@example.com:api_token')",
                    )
            if req.auth_type == "oauth2" and not req.oauth_provider_id.strip():
                raise HTTPException(
                    status_code=400, detail="Click 'Sign in with OAuth' before saving."
                )
        else:
            # Edit: only validate if user actually typed something new.
            if (
                req.auth_type == "basic"
                and req.auth_value.strip()
                and ":" not in req.auth_value
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Basic auth requires 'identifier:secret' (e.g. 'email@example.com:api_token')",
                )
    try:
        result = add_or_update(req.model_dump())
    except Exception as e:
        logger.warning(
            "add_or_update raised unhandled exception url=%r cmd=%r: %s",
            req.url or None,
            req.command or None,
            e,
        )
        raise HTTPException(status_code=400, detail=str(e))
    if not result.get("ok"):
        logger.warning(
            "add_or_update failed url=%r cmd=%r: %s",
            req.url or None,
            req.command or None,
            result.get("error"),
        )
        if result.get("oauth_required"):
            # Return 200 with oauth_required payload — frontend handles it specially
            return result
        if result.get("auth_probe_failed"):
            # Return 200 so the frontend can re-render the form with the Headers field focused
            return result
        raise HTTPException(
            status_code=400, detail=result.get("error", "Failed to connect")
        )
    logger.info(
        "save ok name=%r tool_count=%s status=%s",
        result.get("name"),
        result.get("tool_count"),
        result.get("status"),
    )
    return result


@router.delete("/api/config/mcp/{connection_id}")
def delete_connection(connection_id: str):
    result = remove(connection_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
    return result


@router.post("/api/config/mcp/{connection_id}/health")
def connection_health(connection_id: str):
    return health_check(connection_id)


class CompleteSecretsRequest(BaseModel):
    values: dict[str, str] = {}


@router.post("/api/config/mcp/{connection_id}/complete-secrets")
def complete_connection_secrets(connection_id: str, req: CompleteSecretsRequest):
    """Fill in a pending plugin MCP connection's missing secret values and
    really connect it (Increment 4b, decision #5 — reuses the exact same
    add-modal placeholder-fill mechanism a manually-added connection uses;
    see mcp.manager.complete_pending_secrets for the substitution rules).

    Returns 200 with {ok:false, error} on a bad credential / connect failure
    — mirrors add_connection's own auth_probe_failed convention — so the
    frontend can re-render the form with the error inline rather than
    treating this like a generic 4xx/5xx. The connection stays disabled
    (with plugin_id preserved) until a later successful attempt.
    """
    conn = next((c for c in _load_connections() if c.get("id") == connection_id), None)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    if conn.get("enabled", True):
        raise HTTPException(status_code=400, detail="Connection is already enabled")
    return complete_pending_secrets(connection_id, req.values)


# ── Dependency helpers (injectable for tests) ─────────────────────────────────


def _get_fetcher():
    """Return the production URL fetcher. Tests monkeypatch this."""
    from mcp.normalizer import GITHUB_FETCH_ENABLED

    return _real_fetcher if GITHUB_FETCH_ENABLED else None


def _get_llm():
    """Return a lazy wrapper that builds the gateway LLM callable only when invoked."""
    from mcp.normalizer import LLM_FALLBACK_ENABLED

    if not LLM_FALLBACK_ENABLED:
        return None

    def _lazy_llm(prompt: str) -> str:
        from mcp.normalizer import _make_gateway_llm

        return _make_gateway_llm()(prompt)

    return _lazy_llm


# ── Analyze endpoint ──────────────────────────────────────────────────────────


class _AnalyzeRequest(BaseModel):
    raw_input: str


@router.post("/api/config/mcp/analyze")
def analyze_mcp(req: _AnalyzeRequest):
    """Analyze raw input and return a NormalizeResult. Read-only — no side effects."""
    result = normalize(
        req.raw_input,
        fetcher=_get_fetcher(),
        llm=_get_llm(),
    )
    # Auto-detect auth so the user doesn't have to pick from a dropdown.
    # Step 1: lift any real auth header out of `headers` into auth_type/auth_value.
    # Step 2: if still 'none' and we have a URL, probe the server (OAuth metadata
    #         first, then WWW-Authenticate). Either step is best-effort and
    #         silently falls back to 'none' on any error.
    if result.ok and result.transport == "http":
        try:
            if result.headers and result.auth_type in ("", "none"):
                a_type, a_val, remaining = extract_auth_from_headers(result.headers)
                if a_type != "none":
                    result.auth_type = a_type
                    result.auth_value = a_val
                    result.headers = remaining
                    logger.info("auth-probe lifted %s from headers", a_type)
            # User-intent guard: if the pasted config has credential-shaped
            # headers (even with {placeholders}), respect that and DON'T let
            # URL probing override the choice. The user already told us how
            # they want to auth; OAuth discovery shouldn't hijack their JSON.
            inferred_from_user_headers = "none"
            if result.headers and result.auth_type in ("", "none"):
                inferred_from_user_headers = infer_auth_type_from_headers(
                    result.headers
                )
                if inferred_from_user_headers != "none":
                    result.auth_type = inferred_from_user_headers
                    logger.info(
                        "auth-probe inferred %s from header shape (templated, kept in headers)",
                        inferred_from_user_headers,
                    )
            if result.url and result.auth_type in ("", "none"):
                detected = detect_auth_type(result.url)
                if detected != "none":
                    result.auth_type = detected
                    logger.info("auth-probe detected %s for %s", detected, result.url)
        except Exception as e:
            logger.debug("auth-probe failed (non-fatal): %s", e)

    # Build dict manually to handle all_results (which may contain NormalizeResult instances)
    # For nested results in all_results, don't include their all_results to avoid cycles
    def normalize_result_to_dict(
        nr: NormalizeResult, include_nested: bool = True
    ) -> dict:
        return {
            "ok": nr.ok,
            "transport": nr.transport,
            "name": nr.name,
            "url": nr.url,
            "auth_type": nr.auth_type,
            "auth_value": nr.auth_value,
            "headers": nr.headers,
            "command": nr.command,
            "args": nr.args,
            "env": nr.env,
            "source": nr.source,
            "confidence": nr.confidence,
            "all_results": (
                [
                    normalize_result_to_dict(r, include_nested=False)
                    for r in nr.all_results
                ]
                if include_nested
                else []
            ),
            "prerequisite_warning": nr.prerequisite_warning,
            "error": nr.error,
        }

    d = normalize_result_to_dict(result)
    # If the server requires OAuth and we already have a stored provider for this
    # URL, return the provider_id so the modal pre-populates "Signed in" and
    # Connect can send the right token without forcing the user to re-authorize.
    if d.get("auth_type") == "oauth2" and d.get("url"):
        try:
            from oauth.dcr import _provider_id_for
            from oauth import storage as _oauth_storage

            pid = _provider_id_for(d["url"])
            stored = _oauth_storage.load(pid)
            if stored and stored.get("token", {}).get("access_token"):
                d["oauth_provider_id"] = pid
                logger.info(
                    "analyze: found existing OAuth provider %r for %s", pid, d["url"]
                )
        except Exception:
            pass
    logger.info(
        "analyze ok=%s transport=%s source=%s name=%r url=%r command=%r",
        d["ok"],
        d["transport"],
        d["source"],
        d["name"],
        d["url"],
        d["command"],
    )
    return d


# ── Google Workspace preset ───────────────────────────────────────────────────
# Single source of truth for the "Connect Google" wizard. The frontend reads
# this to render the wizard and to know which servers to register + which scopes
# to request. The MCP URLs here MUST match the entries in
# mcp/url_fetcher.py:_KNOWN_DOC_URLS so a user who later pastes a
# developers.google.com doc URL lands on the same connection record.

_GOOGLE_PRESET = {
    "id": "google-workspace",
    "label": "Google Workspace",
    "preview": True,  # Google's MCP servers are in Developer Preview
    "preview_note": (
        "Connects via the GA Google REST API — no Preview enrollment needed."
    ),
    "redirect_uri": CALLBACK_URI,
    "console_url": "https://console.cloud.google.com/auth/clients",
    "scopes_url": "https://console.cloud.google.com/auth/scopes",
    # Each Google Workspace MCP server requires TWO APIs enabled in the Google
    # Cloud project: the underlying REST API AND a separate "*mcp*" API. The
    # wizard shows these as explicit enable links because skipping the MCP API
    # is the #1 cause of 403 on tools/list — the OAuth flow succeeds but the
    # MCP server rejects the token because its own API isn't enabled.
    "apis": {
        "Gmail": [
            {
                "name": "Gmail API",
                "url": "https://console.cloud.google.com/flows/enableapi?apiid=gmail.googleapis.com",
            },
            {
                "name": "Gmail MCP API",
                "url": "https://console.cloud.google.com/flows/enableapi?apiid=gmailmcp.googleapis.com",
            },
        ],
        "Google Calendar": [
            {
                "name": "Calendar API",
                "url": "https://console.cloud.google.com/flows/enableapi?apiid=calendar-json.googleapis.com",
            },
            {
                "name": "Calendar MCP API",
                "url": "https://console.cloud.google.com/flows/enableapi?apiid=calendarmcp.googleapis.com",
            },
        ],
    },
    # The OAuth consent screen's Data Access section MUST list every scope
    # below. If a scope isn't registered there, Google silently drops it from
    # the issued token — the OAuth flow succeeds, tools/list works (the MCP
    # server accepts any valid token), but the first real API call (e.g.
    # search_threads) fails with 403 "The caller does not have permission".
    # This is the #1 cause of that error and is separate from API enablement.
    "consent_scopes": {
        "Gmail": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
        ],
        "Google Calendar": [
            "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
            "https://www.googleapis.com/auth/calendar.events.freebusy",
            "https://www.googleapis.com/auth/calendar.events.readonly",
        ],
    },
    # HTTP mode — the server runs as a persistent streamable-http process
    # on port 8080 and handles OAuth internally. Connecting via HTTP
    # avoids the stdio block-on-OAuth issue that prevents tool discovery.
    # The server must be running before the connection is created.
    "servers": [
        {
            "name": "Google Workspace",
            "transport": "http",
            "command": "uvx",
            "args": [
                "workspace-mcp",
                "--transport",
                "streamable-http",
                "--tool-tier",
                "complete",
            ],
            "url": "http://127.0.0.1:8080/mcp",
            "scopes_note": (
                "All Google Workspace services (Gmail, Drive, Calendar, Docs, "
                "Sheets, Slides, Forms, Tasks, Contacts, Chat, Search, Apps Script). "
                "Uses the GA Google REST API — no Preview enrollment needed."
            ),
            # Generic env-var injection: the key is the env var name the server
            # expects; the value is the config key to read from. The wizard
            # resolves these before saving the connection. This mechanism works
            # for any preset — not just Google.
            "env_mapping": {
                "GOOGLE_OAUTH_CLIENT_ID": "google_oauth_client_id",
                "GOOGLE_OAUTH_CLIENT_SECRET": "google_oauth_client_secret",
            },
            # Default env vars that don't come from config — hardcoded values
            # the server needs. These are merged with the resolved env_mapping
            # values at connect time.
            "env_defaults": {
                "WORKSPACE_MCP_PORT": "8080",
                "GOOGLE_OAUTH_REDIRECT_URI": "http://localhost:8080/oauth2callback",
                "OAUTHLIB_INSECURE_TRANSPORT": "1",
                "UV_SYSTEM_CERTS": "true",
            },
        },
    ],
}


class _PresetResolveRequest(BaseModel):
    """Request body for preset env-var resolution."""

    transport: Literal["http", "stdio"] = "stdio"
    command: str = ""
    args: list[str] = []
    url: str = ""
    name: str = ""
    env_mapping: dict[str, str] = {}
    env_defaults: dict[str, str] = {}


@router.post("/api/config/mcp/presets/resolve")
def resolve_preset(req: _PresetResolveRequest):
    """Resolve a preset server definition into a complete MCPConnectionRequest.

    Two layers of env vars:
    1. env_defaults — hardcoded values the server needs (e.g. WORKSPACE_MCP_PORT).
       These are always included.
    2. env_mapping — config-key lookups (e.g. GOOGLE_OAUTH_CLIENT_ID → reads from
       config.json). Missing values cause a 400 error so the user knows what to
       configure.
    """
    from config import load_config

    cfg = load_config()

    # Start with defaults (always present)
    env: dict[str, str] = dict(req.env_defaults)

    # Resolve mapped env vars from config
    missing: list[str] = []
    for env_var, config_key in req.env_mapping.items():
        if env_var in env:
            continue
        value = os.environ.get(env_var) or cfg.get(config_key, "") or ""
        if value:
            env[env_var] = value
        else:
            missing.append(env_var)

    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Missing required config values for: {', '.join(missing)}. "
                "Set them in config.json or as environment variables."
            ),
        )

    return {
        "transport": req.transport,
        "command": req.command,
        "args": req.args,
        "url": req.url,
        "name": req.name,
        "auth_type": "none",
        "env": env,
    }


# Track spawned preset servers so we don't double-spawn
_spawned_pids: dict[str, int] = {}


def _port_from_url(url: str) -> int | None:
    """Extract the TCP port from a URL string. Returns None if not parseable."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        if parsed.port:
            return parsed.port
    except Exception:
        pass
    return None


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """True if a TCP connection to (host, port) succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@router.post("/api/config/mcp/presets/spawn")
def spawn_preset_server(req: _PresetResolveRequest):
    """Spawn a preset's MCP server as a detached background process.

    Used for HTTP-mode presets like Google Workspace where the server runs
    persistently on a known port and handles OAuth internally. The frontend
    calls this before POST /api/config/mcp to ensure the server is running.

    Waits for the server to bind its port before returning (up to 30s) so the
    subsequent connect-on-save doesn't race a still-booting server. uvx may
    need to fetch the package on first run, so the timeout is generous.

    Returns {ok, pid, url} or {ok: False, error}.
    """
    from config import load_config

    cfg = load_config()

    env: dict[str, str] = dict(req.env_defaults)
    for env_var, config_key in req.env_mapping.items():
        if env_var in env:
            continue
        value = os.environ.get(env_var) or cfg.get(config_key, "") or ""
        if value:
            env[env_var] = value

    command = (req.command or "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")
    args = req.args or []
    if not args:
        raise HTTPException(status_code=400, detail="args are required")

    # Always kill old process and spawn fresh — avoids port conflicts
    # from previous sessions
    key = f"{command}:{' '.join(args)}"
    if key in _spawned_pids:
        try:
            import psutil

            old = _spawned_pids[key]
            if psutil.pid_exists(old):
                psutil.Process(old).terminate()
        except Exception:
            pass
    try:
        # CREATE_NO_WINDOW (Windows) / start_new_session (Unix) keeps the spawned
        # server in the background without opening a visible console window.
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen([command] + args, env={**os.environ, **env}, **kwargs)
    except Exception as e:
        return {"ok": False, "error": f"Failed to start server: {e}"}

    _spawned_pids[key] = proc.pid
    logger.info("preset spawn ok: %s %s (pid=%d)", command, " ".join(args), proc.pid)

    # Wait for the server to bind its port so the connect-on-save that follows
    # doesn't fail with "connection refused". A fixed client-side sleep can't
    # account for uvx package fetch time on first run (can be 10s+).
    port = _port_from_url(req.url)
    ready = False
    if port:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return {"ok": False, "error": "Server process exited during startup"}
            if _port_open("127.0.0.1", port):
                ready = True
                logger.info("preset spawn port ready: %d (pid=%d)", port, proc.pid)
                break
            time.sleep(0.5)
        if not ready:
            logger.warning(
                "preset spawn port %d not ready after 30s (pid=%d) — "
                "returning anyway; connect may fail",
                port,
                proc.pid,
            )
    return {"ok": True, "pid": proc.pid, "url": req.url, "ready": ready}


class _SpawnStopRequest(BaseModel):
    command: str = ""
    args: list[str] = []


@router.post("/api/config/mcp/presets/spawn/stop")
def stop_spawned_server(req: _SpawnStopRequest):
    """Kill a previously spawned preset server by its command+args key."""
    import psutil

    key = f"{req.command}:{' '.join(req.args)}"
    pid = _spawned_pids.pop(key, None)
    if pid:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        logger.info("preset spawn stopped: %s (pid=%d)", key, pid)
    return {"ok": True}


@router.get("/api/config/mcp/presets/google")
def get_google_preset():
    """Return the Google Workspace MCP preset definition.

    Used by the Connect-Google wizard in the modal to know which servers to
    register, which OAuth scopes to request, and the redirect URI the user
    must register in their Google Cloud Console. Read-only.

    If shared Google OAuth credentials are configured (via env vars or config
    keys), the preset includes them as `shared_client_id` / `shared_client_secret`.
    When present, the wizard skips the Google Cloud Console steps entirely —
    the user just clicks Connect and signs in with Google. This is the zero-
    console experience: one person creates the OAuth client once, every user
    benefits. Google's MCP setup docs require a Web application client (not
    Desktop app), so both client_id AND client_secret are needed.
    """
    from config import load_config

    cfg = load_config()
    shared_id = (
        os.environ.get("GATOR_GOOGLE_CLIENT_ID")
        or cfg.get("google_oauth_client_id")
        or ""
    )
    shared_secret = (
        os.environ.get("GATOR_GOOGLE_CLIENT_SECRET")
        or cfg.get("google_oauth_client_secret")
        or ""
    )
    out = dict(_GOOGLE_PRESET)
    if shared_id:
        out["shared_client_id"] = shared_id
    if shared_secret:
        out["shared_client_secret"] = shared_secret
    return out


@router.get("/api/config/mcp/presets/google/status")
def google_workspace_status():
    """Check if the Google Workspace MCP connection exists and is enabled.

    Returns {connected: bool, connection_id: str|null, name: str|null,
             connect_status: str|null}.
    connect_status is "connecting" while the async connect worker is in
    progress, "failed" if the last connect attempt failed, or null
    when the connection is in a stable state.
    Used by the Settings > Apps > Google Workspace section to show
    Connect vs Disconnect vs Connecting.
    """
    try:
        for conn in list_with_status():
            cid = conn.get("id", "")
            name = conn.get("name", "")
            if cid == "mcp-google-workspace" or "google workspace" in name.lower():
                status = conn.get("connect_status")
                return {
                    "connected": conn.get("enabled", True),
                    "connection_id": cid,
                    "name": name,
                    "connect_status": status,
                }
    except Exception:
        pass
    return {
        "connected": False,
        "connection_id": None,
        "name": None,
        "connect_status": None,
    }


# ── OAuth endpoints ───────────────────────────────────────────────────────────


class _OAuthStartRequest(BaseModel):
    url: str
    label: str = ""
    connection_id: str = (
        ""  # empty for a new connection; set when re-auth on an existing one
    )
    client_id: str = ""  # bring-your-own OAuth client (skip DCR when supplied)
    client_secret: str = ""  # bring-your-own OAuth client secret
    scopes: list[str] = []  # OAuth scopes; auto-detected from server when empty


@router.post("/api/config/mcp/oauth/start")
def oauth_start(req: _OAuthStartRequest, request: Request):
    """Discover OAuth metadata, run DCR if needed, then start the auth flow.

    When client_id is supplied, skips DCR and uses the provided credentials
    directly (bring-your-own-client mode, required for Google OAuth, etc.).

    Returns: {authorize_url, state, provider_id} — frontend opens authorize_url
    in a popup and listens for window.postMessage('oauth-ok').
    """
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="A valid https:// URL is required")
    account_key = (
        req.label.strip() if req.label.strip() and req.label.strip() != url else ""
    )
    # Origin of the request that actually hit THIS Gator instance (e.g.
    # http://localhost:8000 primary, http://localhost:8002 dev-workbench).
    app_origin = f"{request.base_url.scheme}://{request.base_url.netloc}".rstrip("/")

    # Bring-your-own-client path — skip DCR, use supplied credentials directly
    if req.client_id.strip():
        # BYOC providers (e.g. Google) require ONE manually pre-registered
        # redirect_uri in their own developer console — it can't self-update
        # per port like DCR does, so always use the fixed/documented
        # CALLBACK_URI here regardless of which port served this request.
        # (Override via GATOR_OAUTH_CALLBACK_URI if that fixed URI needs to
        # point somewhere other than the default :8000.)
        try:
            provider = register_byoc_provider(
                url,
                client_id=req.client_id.strip(),
                client_secret=req.client_secret.strip(),
                redirect_uris=[CALLBACK_URI],
                label=req.label or url,
                account_key=account_key,
                scopes=req.scopes or None,
            )
            logger.info(
                "oauth BYOC ok provider_id=%r authorize_url=%r",
                provider.id,
                provider.authorize_url,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        flow_app_origin = ""  # start_flow() falls back to CALLBACK_URI
    else:
        # DCR path — auto-register with the OAuth server. Unlike BYOC, DCR
        # providers (e.g. Atlassian/Rovo) self-register whatever redirect_uri
        # we ask for (see oauth/dcr.py), so it's safe — and necessary — to use
        # THIS request's actual origin instead of a fixed port. This is what
        # makes OAuth work correctly from any Gator instance/port (primary,
        # dev-workbench, etc.) instead of only the one hardcoded port.
        redirects = [f"{app_origin}/oauth/callback"]
        from oauth import storage as _oauth_storage
        from mcp.manager import _load_connections
        import uuid as _uuid
        from oauth.dcr import _provider_id_for as _pid_for

        if not req.connection_id.strip():
            proposed_pid = _pid_for(url, account_key=account_key)
            already_used = any(
                c.get("oauth_provider_id") == proposed_pid for c in _load_connections()
            )
            if already_used and (_oauth_storage.load(proposed_pid) or {}).get("token"):
                suffix = _uuid.uuid4().hex[:6]
                account_key = f"{account_key}-{suffix}" if account_key else suffix
                logger.info(
                    "oauth_start: provider %r already claimed; scoping new connection to account_key=%r",
                    proposed_pid,
                    account_key,
                )
        try:
            provider = discover_and_register(
                url,
                redirect_uris=redirects,
                label=req.label or url,
                account_key=account_key,
            )
            logger.info(
                "oauth DCR ok provider_id=%r client_id=%r authorize_url=%r",
                provider.id,
                provider.client_id,
                provider.authorize_url,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        flow_app_origin = app_origin

    try:
        flow = start_flow(provider, app_origin=flow_app_origin)
        logger.info(
            "oauth flow started state=%r redirect_uri=%r authorize_url=%.120s",
            flow.get("state"),
            flow.get("redirect_uri"),
            flow.get("authorize_url"),
        )
    except Exception as e:
        logger.exception("oauth start_flow failed")
        raise HTTPException(status_code=500, detail=f"Could not start OAuth flow: {e}")
    return flow


@router.get("/api/config/mcp/oauth/poll")
def oauth_poll_status(state: str):
    """Frontend polls this after opening the popup. Returns {status, ok?, error?}."""
    result = oauth_poll(state)
    if result.get("status") != "pending":
        logger.info("oauth poll resolved state=%r result=%s", state, result)
    return result


@router.post("/api/config/mcp/oauth/forget")
def oauth_forget_provider(provider_id: str):
    """Wipe stored OAuth credentials for a provider (after user disconnects)."""
    oauth_forget(provider_id)
    return {"ok": True}


@router.get("/oauth/callback")
def oauth_callback(request: Request):
    """Fixed OAuth redirect URI — registered once in the OAuth app as http://localhost:8000/oauth/callback."""
    from fastapi.responses import HTMLResponse

    params = dict(request.query_params)
    ok, msg = handle_callback(params)

    # Determine the app origin for postMessage — prefer the Referer, fall back to our own origin.
    app_origin = f"{request.base_url.scheme}://{request.base_url.netloc}".rstrip("/")

    from oauth.callback_server import _js_string_literal

    event_type = "oauth-ok" if ok else "oauth-fail"
    origin_lit = _js_string_literal(app_origin)
    html = (
        "<html><body style='font-family:system-ui;padding:2em;text-align:center'>"
        "<script>"
        f"window.opener && window.opener.postMessage({{type:'{event_type}'}},'{origin_lit}');"
        "setTimeout(function(){{window.close()}},1500);"
        "</script>"
        f"<h2>{'Connected!' if ok else 'Sign-in failed'}</h2>"
        f"<p>{msg}</p><p>You can close this window.</p>"
        "</body></html>"
    )
    return HTMLResponse(content=html)


# ── Custom Apps (generic web app panes) ───────────────────────────────────────
# Users can add any web app by URL. The shell opens it in a WebContentsView
# alongside the existing hardcoded panes (Outlook, Teams, Slack, etc.).
# Stored in config.json under "custom_apps": [{ id, name, url, icon }].


class CustomAppRequest(BaseModel):
    name: str
    url: str
    icon: str = ""  # emoji or image URL; empty = generic globe


@router.get("/api/config/custom-apps")
def list_custom_apps():
    from config import load_config

    cfg = load_config()
    return {"apps": cfg.get("custom_apps", [])}


@router.post("/api/config/custom-apps")
def add_custom_app(req: CustomAppRequest):
    from config import load_config, save_config
    import re

    cfg = load_config()
    apps = cfg.get("custom_apps", [])
    # Generate a stable id from the name
    app_id = "custom-" + re.sub(r"[^a-z0-9]+", "-", req.name.lower()).strip("-")
    # Deduplicate id
    existing_ids = {a["id"] for a in apps}
    base_id = app_id
    suffix = 2
    while app_id in existing_ids:
        app_id = f"{base_id}-{suffix}"
        suffix += 1
    app = {
        "id": app_id,
        "name": req.name.strip(),
        "url": req.url.strip(),
        "icon": req.icon.strip() or "\U0001f310",  # globe emoji
    }
    apps.append(app)
    cfg["custom_apps"] = apps
    save_config(cfg)
    logger.info(
        "custom-app added: id=%s name=%s url=%s", app_id, app["name"], app["url"]
    )
    return {"ok": True, "app": app}


@router.delete("/api/config/custom-apps/{app_id}")
def remove_custom_app(app_id: str):
    from config import load_config, save_config

    cfg = load_config()
    apps = cfg.get("custom_apps", [])
    updated = [a for a in apps if a.get("id") != app_id]
    if len(updated) == len(apps):
        raise HTTPException(status_code=404, detail="Custom app not found")
    cfg["custom_apps"] = updated
    save_config(cfg)
    return {"ok": True}
