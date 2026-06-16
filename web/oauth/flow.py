"""OAuth 2.1 authorization-code + PKCE flow orchestrator.

start_flow(provider) returns {authorize_url, state, provider_id} and binds
a localhost callback that exchanges the code in-process. The frontend
opens the authorize URL in a popup; when the user consents, the popup
hits our localhost callback and posts 'oauth-ok' to the opener.

get_access_token(provider_id) returns a valid token, refreshing when
within 60s of expiry.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import pkce, storage
from .callback_server import start_callback_listener, stop_all as _stop_callback_listeners
from .provider import OAuthProvider

_log = logging.getLogger(__name__)
_TIMEOUT = 30

# in-process pending flows keyed by state
_PENDING: dict[str, dict] = {}
_PENDING_LOCK = threading.Lock()

# Per-provider refresh locks — prevent two concurrent refreshes from burning a
# one-time-use refresh token. The dict itself needs a lock for create-on-miss.
_REFRESH_LOCKS: dict[str, threading.Lock] = {}
_REFRESH_LOCKS_LOCK = threading.Lock()


def _refresh_lock(provider_id: str) -> threading.Lock:
    with _REFRESH_LOCKS_LOCK:
        lock = _REFRESH_LOCKS.get(provider_id)
        if lock is None:
            lock = threading.Lock()
            _REFRESH_LOCKS[provider_id] = lock
        return lock


def _post_form(url: str, params: dict, client_secret: str = "") -> dict:
    body = urllib.parse.urlencode(params).encode()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": "aigator/1.0 (OAuth-Client)",
    }
    if client_secret:
        import base64
        creds = base64.b64encode(f"{params['client_id']}:{client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"OAuth token endpoint HTTP {e.code}: {body_text}") from e
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        raise RuntimeError(f"OAuth token request failed: {e}") from e


def _exchange_code(provider: OAuthProvider, code: str, code_verifier: str) -> dict:
    params = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": provider.redirect_uri,
        "client_id": provider.client_id,
        "code_verifier": code_verifier,
    }
    result = _post_form(provider.token_url, params, provider.client_secret)
    if "access_token" not in result:
        raise RuntimeError(f"Token response missing access_token: {result}")
    token = {
        "access_token": result["access_token"],
        "refresh_token": result.get("refresh_token", ""),
        "token_type": result.get("token_type", "Bearer"),
        "scope": result.get("scope", ""),
        "expires_at": time.time() + int(result.get("expires_in", 3600)) - 60,
    }
    storage.update_token(provider.id, token)
    return token


def _refresh(provider: OAuthProvider, refresh_token: str) -> dict:
    params = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": provider.client_id,
    }
    result = _post_form(provider.token_url, params, provider.client_secret)
    if "access_token" not in result:
        raise RuntimeError(f"Refresh failed: {result}")
    token = {
        "access_token": result["access_token"],
        "refresh_token": result.get("refresh_token", refresh_token),
        "token_type": result.get("token_type", "Bearer"),
        "scope": result.get("scope", ""),
        "expires_at": time.time() + int(result.get("expires_in", 3600)) - 60,
    }
    storage.update_token(provider.id, token)
    return token


def start_flow(provider: OAuthProvider, port_candidates: list[int] | None = None,
               app_origin: str = "") -> dict:
    """Bind a callback listener, build the authorize URL, return params for the popup."""
    verifier = pkce.make_verifier()
    challenge = pkce.make_challenge(verifier)
    state = pkce.make_state()

    flow_state = {
        "provider": provider,
        "verifier": verifier,
        "result": None,        # filled by callback: {ok, error?}
        "done": None,          # threading.Event from listener
    }

    def on_params(params: dict) -> tuple[bool, str]:
        if params.get("error"):
            flow_state["result"] = {"ok": False, "error": params.get("error_description") or params["error"]}
            return False, params.get("error_description") or params["error"]
        if params.get("state") != state:
            flow_state["result"] = {"ok": False, "error": "state mismatch"}
            return False, "Invalid state — please retry."
        code = params.get("code", "")
        if not code:
            flow_state["result"] = {"ok": False, "error": "missing code"}
            return False, "No authorization code returned."
        try:
            _exchange_code(provider, code, verifier)
        except Exception as e:
            flow_state["result"] = {"ok": False, "error": str(e)}
            return False, str(e)
        flow_state["result"] = {"ok": True}
        return True, "Authorization complete."

    # Evict any prior listener — otherwise a stale one holds the
    # provider-registered port and answers redirects keyed to the wrong state.
    _stop_callback_listeners()
    port, done = start_callback_listener(on_params, port_candidates=port_candidates,
                                          app_origin=app_origin)
    flow_state["done"] = done
    # Use 127.0.0.1 explicitly. `localhost` resolves to ::1 (IPv6) first on
    # Windows, and our callback server binds IPv4 only — the browser would hang.
    # Atlassian, GitHub, etc. accept literal 127.0.0.1 in the redirect URI.
    provider.redirect_uri = f"http://127.0.0.1:{port}/callback"

    # Persist updated redirect_uri to the cached provider so refresh works.
    cached = storage.load(provider.id)
    cached["provider"] = provider.to_dict()
    storage.save(provider.id, cached)

    authorize_params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": provider.redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if provider.scopes:
        authorize_params["scope"] = " ".join(provider.scopes)
    authorize_params.update(provider.extra_authorize_params)

    with _PENDING_LOCK:
        _PENDING[state] = flow_state

    sep = "&" if "?" in provider.authorize_url else "?"
    authorize_url = f"{provider.authorize_url}{sep}{urllib.parse.urlencode(authorize_params)}"
    return {
        "authorize_url": authorize_url,
        "state": state,
        "provider_id": provider.id,
        "redirect_uri": provider.redirect_uri,
    }


def poll(state: str) -> dict:
    """Non-blocking check used by polling frontends.

    Also reaps stale pending flows: if the callback server's done event fired
    (timeout or window closed) but no result was set, treat as a timeout and
    free the slot — otherwise the entry sits in _PENDING forever and the port
    pool slowly exhausts as failed attempts accumulate.
    """
    with _PENDING_LOCK:
        flow = _PENDING.get(state)
    if not flow:
        return {"status": "unknown"}
    result = flow.get("result")
    if result is None:
        done = flow.get("done")
        if done is not None and done.is_set():
            # Callback server stopped without producing a result → timed out
            result = {"ok": False, "error": "OAuth flow timed out — please retry."}
            flow["result"] = result
        else:
            return {"status": "pending"}
    with _PENDING_LOCK:
        _PENDING.pop(state, None)
    return {"status": "done", **result}


def get_access_token(provider_id: str) -> str:
    data = storage.load(provider_id)
    token = data.get("token") or {}
    access = token.get("access_token", "")
    if not access:
        return ""
    if token.get("expires_at", 0) > time.time() + 60:
        return access
    # Serialize refresh per-provider. Most OAuth servers issue one-time-use
    # refresh tokens — concurrent refreshes would invalidate each other.
    with _refresh_lock(provider_id):
        # Re-read under the lock: another waiter may have just refreshed.
        data = storage.load(provider_id)
        token = data.get("token") or {}
        access = token.get("access_token", "")
        if token.get("expires_at", 0) > time.time() + 60:
            return access
        refresh = token.get("refresh_token", "")
        prov_dict = data.get("provider")
        if refresh and prov_dict:
            try:
                new_token = _refresh(OAuthProvider.from_dict(prov_dict), refresh)
                return new_token["access_token"]
            except RuntimeError as e:
                _log.warning("[oauth] refresh failed for %s: %s", provider_id, e)
    return access  # may be expired; caller will get 401 and prompt re-auth


def is_authorized(provider_id: str) -> bool:
    return bool(get_access_token(provider_id))


def forget(provider_id: str) -> None:
    storage.delete(provider_id)
