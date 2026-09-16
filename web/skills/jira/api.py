"""Jira REST API client — auto-detects Bearer PAT (Server) or Basic auth (Cloud)."""

import json
import os
import base64
from urllib.parse import urlparse

import httpx

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://jira.xilinx.com")

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


def _jira_auth() -> tuple[str, str, bool]:
    """Returns (auth_header, base_url, is_cloud)."""
    pat = os.environ.get("JIRA_PAT_TOKEN", "")
    email = os.environ.get("JIRA_EMAIL", "")
    api_token = os.environ.get("JIRA_API_TOKEN", "")
    base = os.environ.get("JIRA_BASE_URL", JIRA_BASE_URL)
    is_cloud = "atlassian.net" in base
    if pat:
        return f"Bearer {pat}", base, is_cloud
    elif email and api_token:
        creds = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        return f"Basic {creds}", base, is_cloud
    else:
        raise RuntimeError("Jira credentials not configured — add them in Settings.")


def jira_is_cloud() -> bool:
    _, _, is_cloud = _jira_auth()
    return is_cloud


import re as _re


def jira_api(
    method: str, path: str, body: dict | None = None, api_version: str = "auto"
) -> dict:
    auth_header, base, is_cloud = _jira_auth()
    # Cloud always uses v3 (Atlassian removed /api/2/search, CHANGE-2046); Server stays on v2
    version = "3" if is_cloud else "2"
    # Strip any leading /rest/api/N/ prefix the caller may have included — prevents double-prefixing
    clean_path = _re.sub(r"^/?rest/api/\d+/", "", path.lstrip("/"))
    url = f"{base}/rest/api/{version}/{clean_path}"
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        pool = _get_pool()
        resp = pool.request(
            method,
            url,
            headers=headers,
            content=json.dumps(body).encode() if body else None,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}
    except httpx.HTTPStatusError as e:
        body_text = e.response.text[:500]
        raise RuntimeError(f"HTTP {e.response.status_code}: {body_text}") from e
    except Exception as e:
        raise RuntimeError(str(e)) from e


def jira_api_for_target(target, method: str, path: str, body: dict | None = None) -> dict:
    """Execute a direct REST request only for the draft's captured target.

    Guards that the currently configured Jira site still matches the target
    captured at draft time, then delegates to jira_api() for the actual
    HTTP call.  Delegating to jira_api() means test patches on jira_api
    and jira_browse_url/jira_is_cloud both take effect correctly.
    """
    if getattr(target, "adapter", "") != "builtin-rest":
        raise RuntimeError("This Jira target is not served by the direct REST adapter.")
    base = jira_browse_url()
    actual = f"{urlparse(base).scheme}://{urlparse(base).netloc}{urlparse(base).path.rstrip('/')}"
    expected = str(getattr(target, "base_url", "")).rstrip("/")
    if actual.lower() != expected.lower():
        raise RuntimeError("The direct Jira connection changed after this draft was prepared. Re-draft the action.")
    return jira_api(method, path, body)


def jira_browse_url() -> str:
    _, base, _ = _jira_auth()
    return base


def jira_upload_attachment(issue_key: str, content: bytes, filename: str, content_type: str) -> list[dict]:
    """Upload already-verified staged bytes without reopening a filesystem path."""
    auth_header, base, is_cloud = _jira_auth()
    version = "3" if is_cloud else "2"
    url = f"{base}/rest/api/{version}/issue/{issue_key}/attachments"
    try:
        response = _get_pool().post(
            url,
            headers={"Authorization": auth_header, "X-Atlassian-Token": "no-check", "Accept": "application/json"},
            files={"file": (filename, content, content_type)},
        )
        response.raise_for_status()
        payload = response.json() if response.content else []
        return payload if isinstance(payload, list) else []
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"HTTP {exc.response.status_code}: {exc.response.text[:500]}") from exc


def jira_upload_attachment_for_target(target, issue_key: str, content: bytes, filename: str, content_type: str) -> list[dict]:
    """Target-bound direct attachment upload using the same routing guard.

    Guards that the currently configured Jira site still matches the target
    captured at draft time, then delegates to jira_upload_attachment().
    """
    if getattr(target, "adapter", "") != "builtin-rest":
        raise RuntimeError("This Jira target is not served by the direct REST adapter.")
    base = jira_browse_url()
    actual = f"{urlparse(base).scheme}://{urlparse(base).netloc}{urlparse(base).path.rstrip('/')}"
    if actual.lower() != str(getattr(target, "base_url", "")).rstrip("/").lower():
        raise RuntimeError("The direct Jira connection changed after this draft was prepared. Re-draft the action.")
    return jira_upload_attachment(issue_key, content, filename, content_type)
