"""MCP connection management routes."""
import dataclasses
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from mcp.manager import add_or_update, remove, health_check, list_with_status
from mcp.normalizer import normalize, NormalizeResult
from mcp.github_fetcher import github_fetcher as _real_fetcher
from mcp.auth_probe import detect_auth_type, extract_auth_from_headers, infer_auth_type_from_headers

from oauth import discover_and_register, start_flow, poll as oauth_poll, forget as oauth_forget

router = APIRouter()


class MCPConnectionRequest(BaseModel):
    transport: Literal["http", "stdio"] = "http"
    # http fields
    url: str = ""
    auth_type: str = "none"   # none | bearer | api_key | basic | oauth2
    auth_value: str = ""
    headers: dict[str, str] = {}
    oauth_provider_id: str = ""   # set when auth_type=oauth2
    # stdio fields
    command: str = ""
    args: list[str] = []
    env: dict[str, str] = {}
    # common
    name: str = ""            # empty = auto-detect from server
    connection_id: str = ""   # set on edit to keep id stable across rename


@router.get("/api/config/mcp")
def list_connections():
    return {"connections": list_with_status()}


@router.post("/api/config/mcp")
def add_connection(req: MCPConnectionRequest):
    logger.info("save transport=%s name=%r url=%r command=%r args=%r",
                req.transport, req.name, req.url, req.command, req.args)
    if req.transport == "stdio":
        if not req.command.strip():
            raise HTTPException(status_code=400, detail="command is required for stdio transport")
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
        has_authz_header = any(str(k).lower() == "authorization" for k in (req.headers or {}))
        has_apikey_header = any(
            str(k).lower() in ("x-api-key", "api-key", "apikey")
            or str(k).lower().endswith("-api-key") or str(k).lower().endswith("-key")
            for k in (req.headers or {})
        )
        if not is_edit:
            if req.auth_type in ("bearer", "api_key") and not req.auth_value.strip() and not (has_authz_header or has_apikey_header):
                raise HTTPException(status_code=400, detail="Token/key is required for this auth type")
            if req.auth_type == "basic" and not has_authz_header:
                if not req.auth_value.strip() or ":" not in req.auth_value:
                    raise HTTPException(status_code=400, detail="Basic auth requires 'identifier:secret' (e.g. 'email@example.com:api_token')")
            if req.auth_type == "oauth2" and not req.oauth_provider_id.strip():
                raise HTTPException(status_code=400, detail="Click 'Sign in with OAuth' before saving.")
        else:
            # Edit: only validate if user actually typed something new.
            if req.auth_type == "basic" and req.auth_value.strip() and ":" not in req.auth_value:
                raise HTTPException(status_code=400, detail="Basic auth requires 'identifier:secret' (e.g. 'email@example.com:api_token')")
    result = add_or_update(req.model_dump())
    if not result.get("ok"):
        logger.warning("add_or_update failed url=%r cmd=%r: %s",
                       req.url or None, req.command or None, result.get("error"))
        if result.get("oauth_required"):
            # Return 200 with oauth_required payload — frontend handles it specially
            return result
        if result.get("auth_probe_failed"):
            # Return 200 so the frontend can re-render the form with the Headers field focused
            return result
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to connect"))
    logger.info("save ok name=%r tool_count=%s", result.get("name"), result.get("tool_count"))
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


# ── Dependency helpers (injectable for tests) ─────────────────────────────────

def _get_fetcher():
    """Return the production GitHub fetcher. Tests monkeypatch this."""
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
                inferred_from_user_headers = infer_auth_type_from_headers(result.headers)
                if inferred_from_user_headers != "none":
                    result.auth_type = inferred_from_user_headers
                    logger.info("auth-probe inferred %s from header shape (templated, kept in headers)",
                                inferred_from_user_headers)
            if result.url and result.auth_type in ("", "none"):
                detected = detect_auth_type(result.url)
                if detected != "none":
                    result.auth_type = detected
                    logger.info("auth-probe detected %s for %s", detected, result.url)
        except Exception as e:
            logger.debug("auth-probe failed (non-fatal): %s", e)
    # Build dict manually to handle all_results (which may contain NormalizeResult instances)
    # For nested results in all_results, don't include their all_results to avoid cycles
    def normalize_result_to_dict(nr: NormalizeResult, include_nested: bool = True) -> dict:
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
            "all_results": [normalize_result_to_dict(r, include_nested=False) for r in nr.all_results] if include_nested else [],
            "prerequisite_warning": nr.prerequisite_warning,
            "error": nr.error,
        }
    d = normalize_result_to_dict(result)
    logger.info("analyze ok=%s transport=%s source=%s name=%r url=%r command=%r",
                d["ok"], d["transport"], d["source"], d["name"], d["url"], d["command"])
    return d


# ── OAuth endpoints ───────────────────────────────────────────────────────────

class _OAuthStartRequest(BaseModel):
    url: str
    label: str = ""
    connection_id: str = ""   # empty for a new connection; set when re-auth on an existing one


@router.post("/api/config/mcp/oauth/start")
def oauth_start(req: _OAuthStartRequest, request: Request):
    """Discover OAuth metadata, run DCR if needed, then start the auth flow.

    Returns: {authorize_url, state, provider_id} — frontend opens authorize_url
    in a popup and listens for window.postMessage('oauth-ok').
    """
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="A valid https:// URL is required")
    # Derive the app origin (scheme://host:port) for postMessage targeting.
    # Prefer the Origin header (set on cross-origin requests); fall back to the
    # request's own base URL (works for same-origin XHRs from the AI Gator UI).
    app_origin = request.headers.get("origin", "")
    if not app_origin:
        bu = request.base_url
        app_origin = f"{bu.scheme}://{bu.netloc}".rstrip("/")
    # Register a generous set of localhost redirect URIs; flow.start_flow binds one.
    # Register both `localhost` and `127.0.0.1` variants across the port range —
    # different providers enforce different host strings. The flow MUST bind one
    # of these ports — otherwise the OAuth server rejects the redirect_uri.
    port_range = list(range(33418, 33428))
    redirects = []
    for p in port_range:
        redirects.append(f"http://localhost:{p}/callback")
        redirects.append(f"http://127.0.0.1:{p}/callback")
    # Use the user-supplied connection label as the account scope, so two
    # connections to the same URL with different names get separate OAuth
    # tokens + DCR clients instead of clobbering each other.
    account_key = req.label.strip() if req.label.strip() and req.label.strip() != url else ""
    # Collision guard: if this is a NEW connection (no connection_id) and the
    # provider id we'd produce is already bound to another saved connection,
    # append a uuid so the new connection gets its own token instead of
    # silently sharing — and clobbering — the existing one. This fires even
    # when the user types a distinct name, because the existing connection
    # was likely created before account_key scoping was added.
    from oauth import storage as _oauth_storage
    from mcp.manager import _load_connections
    import uuid as _uuid
    from oauth.dcr import _provider_id_for as _pid_for
    if not req.connection_id.strip():
        proposed_pid = _pid_for(url, account_key=account_key)
        already_used = any(c.get("oauth_provider_id") == proposed_pid
                            for c in _load_connections())
        if already_used and (_oauth_storage.load(proposed_pid) or {}).get("token"):
            suffix = _uuid.uuid4().hex[:6]
            account_key = f"{account_key}-{suffix}" if account_key else suffix
            logger.info("oauth_start: provider %r already claimed; scoping new connection to account_key=%r",
                        proposed_pid, account_key)
    try:
        provider = discover_and_register(url, redirect_uris=redirects,
                                          label=req.label or url,
                                          account_key=account_key)
        logger.info("oauth DCR ok provider_id=%r client_id=%r authorize_url=%r",
                    provider.id, provider.client_id, provider.authorize_url)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        flow = start_flow(provider, port_candidates=port_range, app_origin=app_origin)
        logger.info("oauth flow started state=%r redirect_uri=%r authorize_url=%.120s",
                    flow.get("state"), flow.get("redirect_uri"), flow.get("authorize_url"))
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
