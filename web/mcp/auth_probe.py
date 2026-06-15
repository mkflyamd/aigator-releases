"""Auth-type auto-detection for HTTP MCP servers.

Three strategies, tried in order (strongest signal first):

1. Protected Resource Metadata (RFC 9728) — per the MCP 2025-06-18 spec, MCP
   servers MUST publish /.well-known/oauth-protected-resource. If we get a valid
   PRM document back, the server is a spec-compliant OAuth resource server.
2. Authorization Server Metadata (RFC 8414) — older signal, still useful for
   servers that publish AS metadata at their own origin.
3. WWW-Authenticate probe — send a minimal MCP request with no auth; if the
   server returns 401 with a WWW-Authenticate header, parse the scheme. Also
   honor the `resource_metadata` parameter that RFC 9728-compliant servers
   include in the challenge.

Probes are best-effort: any network failure or unexpected response leaves auth_type
as 'none' so the user can pick manually. We never block the analyze flow on this.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from oauth.dcr import parse_resource_metadata_url as _parse_resource_metadata_url

_log = logging.getLogger(__name__)
_PROBE_TIMEOUT = 5  # seconds — probes must be fast or skipped


def detect_auth_type(url: str) -> str:
    """Return one of: 'oauth2', 'bearer', 'basic', 'api_key', 'none'.

    Returns 'none' on any error or ambiguous result — caller can default to none
    and let the user override.
    """
    if not url or not url.startswith(("http://", "https://")):
        return "none"

    # 1. RFC 9728 Protected Resource Metadata — strongest signal, mandated by the
    #    current MCP auth spec. A valid PRM doc means OAuth Bearer with proper
    #    discovery support.
    prm_url = _probe_protected_resource_metadata(url)
    if prm_url:
        _log.info("[auth-probe] %s publishes PRM at %s -> oauth2", url, prm_url)
        return "oauth2"

    # 2. RFC 8414 Authorization Server Metadata — pre-spec OAuth servers.
    try:
        from oauth.dcr import discover_metadata
        discover_metadata(url)
        _log.info("[auth-probe] %s publishes OAuth AS metadata -> oauth2", url)
        return "oauth2"
    except Exception as e:
        _log.debug("[auth-probe] no OAuth AS metadata at %s: %s", url, e)

    # 3. WWW-Authenticate probe — send a minimal MCP initialize request with no auth.
    scheme = _probe_www_authenticate(url)
    if scheme:
        _log.info("[auth-probe] %s returned WWW-Authenticate: %s", url, scheme)
        return scheme

    return "none"


def _prm_candidate_urls(mcp_url: str) -> list[str]:
    """Per RFC 9728 §3.1 + MCP spec, try path-aware first, then root."""
    parsed = urllib.parse.urlparse(mcp_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    candidates: list[str] = []
    if path:
        candidates.append(f"{origin}/.well-known/oauth-protected-resource{path}")
    candidates.append(f"{origin}/.well-known/oauth-protected-resource")
    seen, uniq = set(), []
    for u in candidates:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def _probe_protected_resource_metadata(url: str) -> str:
    """Return the PRM URL if a valid document is published, else empty string.

    A valid PRM document is JSON with at least one of: `resource`,
    `authorization_servers`, `bearer_methods_supported` — the canonical RFC 9728
    fields. We're permissive here because some implementations omit one or two.
    """
    for candidate in _prm_candidate_urls(url):
        req = urllib.request.Request(candidate, headers={
            "Accept": "application/json",
            "User-Agent": "aigator/1.0 (auth-probe)",
        })
        try:
            with urllib.request.urlopen(req, timeout=_PROBE_TIMEOUT) as resp:
                body = resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            _log.debug("[auth-probe] PRM fetch %s failed: %s", candidate, e)
            continue
        try:
            meta = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(meta, dict):
            continue
        if any(k in meta for k in ("resource", "authorization_servers", "bearer_methods_supported")):
            return candidate
    return ""


def _probe_www_authenticate(url: str) -> str:
    """POST a minimal MCP initialize; on 401 inspect WWW-Authenticate header."""
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "aigator-probe", "version": "1.0"},
        },
    }).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "aigator/1.0 (auth-probe)",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=_PROBE_TIMEOUT)
        return ""  # 2xx with no auth = server allows anonymous, auth_type stays 'none'
    except urllib.error.HTTPError as e:
        if e.code != 401:
            return ""
        wa = e.headers.get("WWW-Authenticate", "") or ""
        wa_lower = wa.lower().strip()
        if wa_lower.startswith("bearer"):
            # If the challenge includes resource_metadata, this is a spec-compliant
            # OAuth 2.1 resource server — report oauth2, not bearer.
            if _parse_resource_metadata_url(wa):
                return "oauth2"
            return "bearer"
        if wa_lower.startswith("basic"):
            return "basic"
        # Some servers signal API-key auth via custom schemes; safe fallback
        if wa_lower:
            return "bearer"
        return ""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        _log.debug("[auth-probe] network error probing %s: %s", url, e)
        return ""


def extract_auth_from_headers(headers: dict) -> tuple[str, str, dict]:
    """If headers contain a recognizable auth header, lift it out into (type, value, remaining_headers).

    Recognises:
      Authorization: Bearer <token>            -> ('bearer', <token>, ...)
      Authorization: Basic <b64>               -> ('basic', <decoded email:token>, ...)
      X-Api-Key: <key> / Api-Key: <key>        -> ('api_key', <key>, ...)

    Returns ('none', '', original_headers) if nothing matches.
    """
    if not isinstance(headers, dict) or not headers:
        return "none", "", dict(headers or {})

    remaining = dict(headers)
    for key in list(remaining.keys()):
        kl = key.lower()
        val = str(remaining[key]).strip()
        if kl == "authorization":
            if val.lower().startswith("bearer "):
                token = val[7:].strip()
                if token and not _is_placeholder(token):
                    remaining.pop(key)
                    return "bearer", token, remaining
            elif val.lower().startswith("basic "):
                import base64
                try:
                    decoded = base64.b64decode(val[6:].strip()).decode("utf-8", errors="replace")
                    if ":" in decoded and not _is_placeholder(decoded):
                        remaining.pop(key)
                        return "basic", decoded, remaining
                except Exception:
                    pass
        elif kl in ("x-api-key", "api-key", "apikey"):
            if val and not _is_placeholder(val):
                remaining.pop(key)
                return "api_key", val, remaining
    return "none", "", remaining


def _is_placeholder(s: str) -> bool:
    """Detect {VAR}-style placeholders so we don't lift '{TOKEN}' out as a real credential."""
    s = s.strip()
    return s.startswith("{") and s.endswith("}") and len(s) < 80


def infer_auth_type_from_headers(headers: dict) -> str:
    """Classify the user's auth intent from header *shape* alone, even when the
    value is templated (e.g. 'Basic {email}@{token}') and can't be lifted.

    Returns 'basic' | 'bearer' | 'api_key' | 'none'. Used to decide which form
    fields to render so a user who pasted a JSON config with placeholders isn't
    redirected to an unrelated auth path (e.g. OAuth) by URL-based probing.
    """
    if not isinstance(headers, dict):
        return "none"
    for key, raw in headers.items():
        kl = str(key).lower()
        val = str(raw).strip()
        if kl == "authorization":
            low = val.lower()
            if low.startswith("bearer"):
                return "bearer"
            if low.startswith("basic"):
                return "basic"
            return "bearer"  # opaque token — bearer is the safe default
        if kl in ("x-api-key", "api-key", "apikey") or kl.endswith("-api-key") or kl.endswith("-key"):
            return "api_key"
    return "none"
