"""Confluence REST API client — Basic auth (email + API token)."""

import contextvars
import html
import json
import logging
import os
import time
import base64
from contextlib import contextmanager
from urllib.parse import urlparse

import httpx

log = logging.getLogger("confluence")

_MAX_RETRIES = 3
_BACKOFF_BASE = 1  # seconds

# ── Module-level connection pool ──
_http_pool: httpx.Client | None = None


def _get_pool() -> httpx.Client:
    global _http_pool
    if _http_pool is None or _http_pool.is_closed:
        _http_pool = httpx.Client(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            follow_redirects=True,
        )
    return _http_pool


_SHARED_TOKEN_HOST_SUFFIXES = (".atlassian.net",)
_active_base: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "confluence_active_base", default=None
)


def _primary_base() -> str:
    return os.environ.get("CONFLUENCE_BASE_URL", "")


def _canon(url: str) -> str:
    return url.strip().rstrip("/").lower()


def validate_extra_site_url(url: str) -> str:
    """Return the canonical `https://host/wiki` root for an additional site, or raise ValueError."""

    raw = url.strip()
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/").lower()
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port is not None
        or path not in ("", "/wiki")
    ):
        raise ValueError(
            "An additional Confluence site must look like https://example.atlassian.net/wiki."
        )
    if not any(host.endswith(s) and len(host) > len(s) for s in _SHARED_TOKEN_HOST_SUFFIXES):
        raise ValueError(
            "Additional Confluence sites share the primary token, so the host must end with "
            + " or ".join(_SHARED_TOKEN_HOST_SUFFIXES) + "."
        )
    return f"https://{host}/wiki"


def configured_extra_urls() -> list[str]:
    """Validated additional site URLs from config, excluding the primary site."""

    from config import load_config

    raw = load_config().get("confluence_extra_base_urls", [])
    if not isinstance(raw, list):
        return []
    primary = _canon(_primary_base())
    out: list[str] = []
    for item in raw:
        try:
            base = validate_extra_site_url(str(item))
        except ValueError:
            continue
        if base != primary and base not in out:
            out.append(base)
    return out


def _shares_primary_token() -> bool:
    host = (urlparse(_primary_base()).hostname or "").lower()
    return any(host.endswith(s) for s in _SHARED_TOKEN_HOST_SUFFIXES)


def configured_sites() -> list[str]:
    """Primary site first, then additional sites that may reuse its token."""

    primary = _primary_base().rstrip("/")
    if not primary:
        return []
    return [primary, *(configured_extra_urls() if _shares_primary_token() else [])]


def site_for_url(url: str) -> str | None:
    """The configured site whose host serves `url`, or None."""

    host = (urlparse(url).hostname or "").lower()
    for site in configured_sites():
        if (urlparse(site).hostname or "").lower() == host:
            return site
    return None


@contextmanager
def use_site(base_url: str | None):
    """Send Confluence calls in this context to `base_url` (the primary when None)."""

    token = _active_base.set(base_url)
    try:
        yield
    finally:
        _active_base.reset(token)


def confluence_browse_url() -> str:
    """Single source of truth for the Confluence base URL."""
    base = _primary_base()
    override = _active_base.get()
    if override and _canon(override) != _canon(base):
        if not _shares_primary_token() or _canon(override) not in {
            _canon(u) for u in configured_extra_urls()
        }:
            raise RuntimeError(
                "That Confluence site is not configured to share the primary Confluence credentials. "
                "Add it under Confluence sites in Settings."
            )
        return override.rstrip("/")
    return base


def confluence_api(method: str, path: str, body: dict | None = None) -> dict:
    email = os.environ.get("CONFLUENCE_EMAIL", "") or os.environ.get(
        "ATLASSIAN_EMAIL", ""
    )
    token = os.environ.get("CONFLUENCE_PAT", "") or os.environ.get("ATLASSIAN_PAT", "")
    if not email or not token:
        raise RuntimeError(
            "Confluence credentials not configured — add email + API token in Settings."
        )
    creds = base64.b64encode(f"{email}:{token}".encode()).decode()
    base = confluence_browse_url()
    url = f"{base}/rest/api/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Gator/1.0 (Confluence integration)",
    }
    pool = _get_pool()
    last_err = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = pool.request(
                method,
                url,
                headers=headers,
                content=json.dumps(body).encode() if body else None,
            )
            resp.raise_for_status()
            log.debug("Confluence %s %s -> %s", method, path, resp.status_code)
            return resp.json() if resp.content else {}
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            body_text = e.response.text[:500]
            user_msg = _extract_error_message(body_text, str(e))

            if code == 429:
                retry_after = int(e.response.headers.get("Retry-After", "60"))
                log.warning(
                    "Confluence 429 on %s %s — retrying in %ds (%d/%d)",
                    method,
                    path,
                    retry_after,
                    attempt,
                    _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(min(retry_after, 120))
                    last_err = e
                    continue
                raise RuntimeError(
                    f"Confluence rate-limited after {_MAX_RETRIES} retries: {user_msg}"
                ) from e

            if code == 409:
                raise RuntimeError(
                    "Page was modified by another user — please re-read the page and try again."
                ) from e

            if code >= 500:
                wait = _BACKOFF_BASE * (2 ** (attempt - 1))
                log.warning(
                    "Confluence %d on %s %s — retrying in %ds (%d/%d)",
                    code,
                    method,
                    path,
                    wait,
                    attempt,
                    _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(wait)
                    last_err = e
                    continue
                raise RuntimeError(
                    f"Confluence server error ({code}) after {_MAX_RETRIES} retries: {user_msg}"
                ) from e

            log.warning("Confluence %d on %s %s: %s", code, method, path, user_msg)
            raise RuntimeError(f"Confluence API {code}: {user_msg}") from e
        except Exception as e:
            log.error("Confluence request failed: %s %s — %s", method, path, e)
            raise RuntimeError(str(e)) from e

    raise RuntimeError(
        f"Confluence request failed after {_MAX_RETRIES} attempts"
    ) from last_err


def _extract_error_message(body_text: str, fallback: str) -> str:
    """Parse Atlassian JSON error body and return only the user-facing message."""
    if not body_text:
        return fallback
    try:
        err = json.loads(body_text)
        return err.get("message") or (err.get("errorMessages") or [None])[0] or fallback
    except (json.JSONDecodeError, IndexError, TypeError):
        return fallback
