"""Dynamic Client Registration (RFC 7591) for MCP-spec OAuth servers.

discover_and_register(mcp_url) → OAuthProvider
    1. Fetches /.well-known/oauth-authorization-server (probing parent paths
       per RFC 8414).
    2. POSTs a registration request to the registration_endpoint.
    3. Persists the resulting client_id (+ optional client_secret) under
       storage so subsequent flows reuse the registration.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from . import storage
from .provider import OAuthProvider

_log = logging.getLogger(__name__)

_CLIENT_NAME = "AI Gator"
_SOFTWARE_ID = "ai-gator"
_TIMEOUT = 15

_RESOURCE_METADATA_RE = re.compile(
    r'resource_metadata\s*=\s*["\']?([^"\'`,\s]+)["\']?', re.IGNORECASE
)


def parse_resource_metadata_url(www_authenticate: str) -> str | None:
    """Extract resource_metadata URL from WWW-Authenticate header per RFC 9728 §5.1.

    Example header:
        WWW-Authenticate: Bearer realm="example", resource_metadata="https://api.example.com/.well-known/oauth-protected-resource"
    Returns the URL string, or None if not present.
    """
    m = _RESOURCE_METADATA_RE.search(www_authenticate)
    return m.group(1) if m else None


def _slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def _provider_id_for(mcp_url: str, account_key: str = "") -> str:
    """Per-URL provider id, optionally scoped by an account key.

    Same URL with different account_key → distinct providers (separate tokens
    and DCR clients). Two real-world cases this enables:
      - Same MCP server with multiple user accounts (e.g. two Atlassian tenants).
      - Cloud vs on-prem instances that happen to share a host path but enforce
        different OAuth scopes/audiences.
    Empty account_key preserves the legacy host-only id for back-compat.
    """
    host = urllib.parse.urlparse(mcp_url).netloc or "mcp"
    safe = host.replace(":", "_").replace(".", "-")
    base = f"mcp-{safe}"
    acct = _slug(account_key)
    return f"{base}-{acct}" if acct else base


def _fetch_json(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "aigator/1.0 (OAuth-Client)",
    })
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as e:
        _log.debug("[dcr] metadata fetch %s failed: %s", url, e)
        return None


def _candidate_metadata_urls(mcp_url: str) -> list[str]:
    """Per RFC 8414, OAuth metadata may be at the origin or alongside the resource."""
    parsed = urllib.parse.urlparse(mcp_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    out = []
    out.append(f"{origin}/.well-known/oauth-authorization-server")
    if path:
        out.append(f"{origin}/.well-known/oauth-authorization-server{path}")
    out.append(f"{origin}/.well-known/openid-configuration")
    # de-dupe, preserve order
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def _probe_protected_resource(mcp_url: str) -> str | None:
    """Send an unauth request to the MCP URL; parse resource_metadata from a
    401 WWW-Authenticate header per RFC 9728 §5.1. Returns the metadata URL or None.
    """
    req = urllib.request.Request(mcp_url, headers={
        "Accept": "application/json, text/event-stream",
        "User-Agent": "aigator/1.0 (OAuth-Client)",
    })
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            wa = resp.headers.get("WWW-Authenticate", "")
    except urllib.error.HTTPError as e:
        wa = e.headers.get("WWW-Authenticate", "") if e.headers else ""
        _log.debug("[dcr] MCP probe got HTTP %d, WWW-Authenticate=%r", e.code, wa)
    except urllib.error.URLError as e:
        _log.debug("[dcr] MCP probe failed: %s", e)
        return None
    return parse_resource_metadata_url(wa) if wa else None


def _candidate_protected_resource_urls(mcp_url: str) -> list[str]:
    """Per RFC 9728, /.well-known/oauth-protected-resource may live at the
    origin or alongside the resource path."""
    parsed = urllib.parse.urlparse(mcp_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    out = [f"{origin}/.well-known/oauth-protected-resource"]
    if path:
        out.append(f"{origin}/.well-known/oauth-protected-resource{path}")
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def _resolve_as_from_protected_resource(pr_meta: dict) -> dict | None:
    """Given Protected Resource Metadata, fetch the first authorization server's metadata."""
    auth_servers = pr_meta.get("authorization_servers") or []
    for issuer in auth_servers:
        # Per RFC 8414, AS metadata lives at {issuer}/.well-known/oauth-authorization-server
        # or {issuer}/.well-known/openid-configuration.
        issuer = issuer.rstrip("/")
        for url in (
            f"{issuer}/.well-known/oauth-authorization-server",
            f"{issuer}/.well-known/openid-configuration",
            issuer,  # some servers serve the doc at the issuer URL directly
        ):
            meta = _fetch_json(url)
            if meta and meta.get("authorization_endpoint") and meta.get("token_endpoint"):
                _log.info("[dcr] resolved AS metadata via %s (issuer=%s)", url, issuer)
                return meta
    return None


def discover_metadata(mcp_url: str) -> dict:
    # 1. RFC 9728 path: probe the MCP URL for a 401 with resource_metadata,
    #    OR try the well-known protected-resource paths directly.
    pr_url = _probe_protected_resource(mcp_url)
    pr_candidates = [pr_url] if pr_url else []
    pr_candidates.extend(_candidate_protected_resource_urls(mcp_url))
    for url in pr_candidates:
        if not url:
            continue
        pr_meta = _fetch_json(url)
        if pr_meta and pr_meta.get("authorization_servers"):
            _log.info("[dcr] found protected-resource metadata at %s", url)
            as_meta = _resolve_as_from_protected_resource(pr_meta)
            if as_meta:
                return as_meta

    # 2. Legacy path: AS metadata published alongside the resource itself.
    for url in _candidate_metadata_urls(mcp_url):
        meta = _fetch_json(url)
        if meta and meta.get("authorization_endpoint") and meta.get("token_endpoint"):
            _log.info("[dcr] discovered OAuth metadata via %s", url)
            return meta

    raise RuntimeError(
        f"Could not discover OAuth metadata for {mcp_url}. Tried protected-resource "
        "metadata (/.well-known/oauth-protected-resource) and authorization-server "
        "metadata (/.well-known/oauth-authorization-server) — neither was published. "
        "If this server uses a non-OAuth auth (API token / header), pick a different "
        "auth type instead."
    )


def _register_client(registration_endpoint: str, redirect_uris: list[str]) -> dict:
    payload = {
        "client_name": _CLIENT_NAME,
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",  # public client (PKCE)
        "software_id": _SOFTWARE_ID,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        registration_endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "aigator/1.0 (OAuth-Client)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"DCR registration failed: HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        raise RuntimeError(f"DCR registration failed: {e}") from e


def discover_and_register(
    mcp_url: str,
    redirect_uris: list[str],
    label: str = "",
    force: bool = False,
    account_key: str = "",
) -> OAuthProvider:
    """Return an OAuthProvider for the given MCP URL, performing DCR if needed.

    redirect_uris must include every URI the OAuth flow may use (typically a
    list of localhost callback URLs across a port range).

    account_key (optional) scopes the provider id so the same URL can hold
    multiple independent OAuth identities (e.g. two accounts, cloud vs on-prem).
    """
    provider_id = _provider_id_for(mcp_url, account_key=account_key)
    cached = storage.load(provider_id) if not force else {}
    cached_provider = cached.get("provider") if isinstance(cached, dict) else None

    if cached_provider and cached_provider.get("client_id") and not force:
        # If our intended redirect URIs aren't all covered by the cached DCR
        # registration, we must re-register — the OAuth server will reject any
        # redirect_uri we didn't register. We track this via `registered_redirect_uris`
        # stored alongside the provider.
        registered = set(cached.get("registered_redirect_uris") or [])
        needed = set(redirect_uris)
        if not registered or not needed.issubset(registered):
            _log.info("[dcr] cached registration missing redirect URIs %s — re-registering",
                      needed - registered)
        else:
            prov = OAuthProvider.from_dict(cached_provider)
            # Refresh authorize/token URLs in case the server moved them.
            try:
                meta = discover_metadata(mcp_url)
                prov.authorize_url = meta.get("authorization_endpoint", prov.authorize_url)
                prov.token_url = meta.get("token_endpoint", prov.token_url)
                prov.registration_endpoint = meta.get("registration_endpoint", prov.registration_endpoint)
                prov.issuer = meta.get("issuer", prov.issuer)
                cached["provider"] = prov.to_dict()
                storage.save(provider_id, cached)
            except RuntimeError:
                pass
            return prov

    meta = discover_metadata(mcp_url)
    registration_endpoint = meta.get("registration_endpoint")
    if not registration_endpoint:
        raise RuntimeError(
            f"{mcp_url} advertises OAuth metadata but does not support Dynamic "
            "Client Registration — manual app registration is required."
        )
    reg = _register_client(registration_endpoint, redirect_uris)
    client_id = reg.get("client_id")
    if not client_id:
        raise RuntimeError(f"DCR response missing client_id: {reg}")

    prov = OAuthProvider(
        id=provider_id,
        mode="dcr",
        authorize_url=meta["authorization_endpoint"],
        token_url=meta["token_endpoint"],
        registration_endpoint=registration_endpoint,
        client_id=client_id,
        client_secret=reg.get("client_secret", ""),
        scopes=[],  # MCP servers gate scopes server-side; leave empty unless caller sets
        issuer=meta.get("issuer", ""),
        label=label or urllib.parse.urlparse(mcp_url).netloc,
    )
    storage.save(provider_id, {
        "provider": prov.to_dict(),
        "registered_redirect_uris": list(redirect_uris),
    })
    return prov
