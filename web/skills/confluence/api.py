"""Confluence REST API client — Basic auth (email + API token)."""
import html
import json
import logging
import os
import time
import base64

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


def confluence_browse_url() -> str:
    """Single source of truth for the Confluence base URL."""
    return os.environ.get("CONFLUENCE_BASE_URL", "")


def confluence_api(method: str, path: str, body: dict | None = None) -> dict:
    email = os.environ.get("CONFLUENCE_EMAIL", "") or os.environ.get("ATLASSIAN_EMAIL", "")
    token = os.environ.get("CONFLUENCE_PAT", "") or os.environ.get("ATLASSIAN_PAT", "")
    if not email or not token:
        raise RuntimeError("Confluence credentials not configured — add email + API token in Settings.")
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
            resp = pool.request(method, url, headers=headers,
                                content=json.dumps(body).encode() if body else None)
            resp.raise_for_status()
            log.debug("Confluence %s %s -> %s", method, path, resp.status_code)
            return resp.json() if resp.content else {}
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            body_text = e.response.text[:500]
            user_msg = _extract_error_message(body_text, str(e))

            if code == 429:
                retry_after = int(e.response.headers.get("Retry-After", "60"))
                log.warning("Confluence 429 on %s %s — retrying in %ds (%d/%d)",
                            method, path, retry_after, attempt, _MAX_RETRIES)
                if attempt < _MAX_RETRIES:
                    time.sleep(min(retry_after, 120))
                    last_err = e
                    continue
                raise RuntimeError(f"Confluence rate-limited after {_MAX_RETRIES} retries: {user_msg}") from e

            if code == 409:
                raise RuntimeError("Page was modified by another user — please re-read the page and try again.") from e

            if code >= 500:
                wait = _BACKOFF_BASE * (2 ** (attempt - 1))
                log.warning("Confluence %d on %s %s — retrying in %ds (%d/%d)",
                            code, method, path, wait, attempt, _MAX_RETRIES)
                if attempt < _MAX_RETRIES:
                    time.sleep(wait)
                    last_err = e
                    continue
                raise RuntimeError(f"Confluence server error ({code}) after {_MAX_RETRIES} retries: {user_msg}") from e

            log.warning("Confluence %d on %s %s: %s", code, method, path, user_msg)
            raise RuntimeError(f"Confluence API {code}: {user_msg}") from e
        except Exception as e:
            log.error("Confluence request failed: %s %s — %s", method, path, e)
            raise RuntimeError(str(e)) from e

    raise RuntimeError(f"Confluence request failed after {_MAX_RETRIES} attempts") from last_err


def _extract_error_message(body_text: str, fallback: str) -> str:
    """Parse Atlassian JSON error body and return only the user-facing message."""
    if not body_text:
        return fallback
    try:
        err = json.loads(body_text)
        return (
            err.get("message")
            or (err.get("errorMessages") or [None])[0]
            or fallback
        )
    except (json.JSONDecodeError, IndexError, TypeError):
        return fallback
