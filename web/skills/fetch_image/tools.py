"""fetch_image skill — download an image from any supported integration and save
it to disk so the LLM can read it with vision.

Supports:
  - Confluence attachments  (by page_id + filename)
  - Microsoft Graph images  (email inline, OneNote, SharePoint)
  - Teams images            (Skype/ASM CDN, Graph CDN)
  - Any https:// URL        (falls back to unauthenticated fetch)
"""

from __future__ import annotations

import ipaddress
import re
import socket
import uuid
from pathlib import Path, PureWindowsPath
from urllib.parse import urljoin, urlsplit

SKILL_ID = "fetch_image"
ALWAYS_ON = False

# Reactive activation: inject this skill's tools mid-turn whenever a tool result
# contains image placeholders — without requiring the classifier to predict it upfront.
ACTIVATES_ON = [
    "[image:",       # [image: filename] or [image](url) from html_to_text
    "images_note",   # injected by read_confluence_page when images are present
]

TOOL_DEFS = [
    {
        "name": "fetch_image",
        "description": (
            "Download an image from an email, Confluence page, OneNote page, or Teams message "
            "and save it to disk so you can visually analyze it. "
            "Use this whenever you encounter [image: filename] or [image](url) placeholders in "
            "content you have already read, or when the user asks to see, describe, explain, or "
            "analyze an image in a document or message. "
            "Pass url for direct image links, or page_id + filename for Confluence attachments. "
            "Returns a file_path — pass it to describe_images to describe the image. "
            "NEVER use run_python, requests, httpx, or another downloader for Teams, Graph, or Slack image URLs; "
            "this tool is the only path that has their authenticated access."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Direct image URL (from [image](url) placeholders, Graph URLs, Teams CDN URLs, etc.). For Slack shared file links surfaced as [image: name](slack-file:FXXXXXXX), pass the full slack-file:FXXXXXXX value here.",
                },
                "page_id": {
                    "type": "string",
                    "description": "Confluence page ID — required when fetching a Confluence attachment by filename.",
                },
                "filename": {
                    "type": "string",
                    "description": "Confluence attachment filename (e.g. 'image-20260911-002530.png') — use with page_id.",
                },
                "source": {
                    "type": "string",
                    "enum": ["confluence", "graph", "teams", "auto"],
                    "description": "Which auth to use. 'auto' (default) detects from the URL.",
                    "default": "auto",
                },
            },
            "required": [],
        },
    },
]

TOOL_STATUS = {
    "fetch_image": "🖼️ Fetching image...",
}

# Allowed Graph/Teams domains (mirrors the existing proxy allowlists)
_GRAPH_HOSTS = {"graph.microsoft.com"}
_TEAMS_HOSTS = {
    "teams.microsoft.com",
    "statics.teams.cdn.office.net",
    "au.statics.teams.cdn.office.net",
    "eu.statics.teams.cdn.office.net",
    "asm.skype.com",
    "sfbassets.com",
}
_SLACK_HOSTS = {
    "files.slack.com",
    "slack-edge.com",
    "slack-imgs.com",
}


def _detect_source(url: str) -> str:
    host = urlsplit(url).hostname or ""
    host = host.lower()
    if any(host == h or host.endswith("." + h) for h in _GRAPH_HOSTS):
        return "graph"
    if any(host == h or host.endswith("." + h) for h in _TEAMS_HOSTS):
        return "teams"
    if any(host == h or host.endswith("." + h) for h in _SLACK_HOSTS):
        return "slack"
    return "auto"


def _host_matches(host: str, allowed_hosts: set[str]) -> bool:
    return any(host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts)


def _validate_fetch_url(url: str, allowed_hosts: set[str] | None = None) -> None:
    """Reject non-public targets before opening a network connection.

    Image URLs may originate in untrusted content. Authenticated callers pass an
    allowlist so their credentials can only be used with the integration that
    issued the URL; anonymous callers still require a public HTTPS destination.
    """
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ValueError("Image URLs must use HTTPS with a public hostname.")
    if allowed_hosts and not _host_matches(host, allowed_hosts):
        raise ValueError("Image URL is not hosted by the authenticated integration.")
    try:
        addresses = {
            item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ValueError("Image URL hostname could not be resolved.") from exc
    if not addresses:
        raise ValueError("Image URL hostname did not resolve to an address.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Image URL must not resolve to a private or local address.")


def _safe_http_get(
    url: str, headers: dict[str, str] | None = None, allowed_hosts: set[str] | None = None
) -> tuple[bytes, str]:
    """Fetch a public HTTPS image without forwarding credentials on redirects."""
    import httpx

    current_url = url
    current_headers = headers or {}
    current_allowed_hosts = allowed_hosts
    for _ in range(4):
        _validate_fetch_url(current_url, current_allowed_hosts)
        response = httpx.get(
            current_url,
            headers=current_headers,
            timeout=20,
            follow_redirects=False,
        )
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                raise ValueError("Image redirect did not provide a destination.")
            current_url = urljoin(current_url, location)
            # A redirect target is independently validated on the next loop.
            # Never forward bearer/Basic credentials to it, even if it shares
            # a parent domain with the original URL.
            current_headers = {}
            current_allowed_hosts = None
            continue
        response.raise_for_status()
        content_type = response.headers.get("content-type", "image/png").split(";")[0]
        return response.content, content_type
    raise ValueError("Image request exceeded the redirect limit.")


def _fetch_confluence_attachment(page_id: str, filename: str) -> tuple[bytes, str]:
    """Fetch a Confluence attachment by page_id + filename. Returns (bytes, content_type)."""
    import base64 as _b64
    import os

    from skills.confluence.api import confluence_api, confluence_browse_url

    # Get attachment metadata
    from urllib.parse import quote as _qp
    result = confluence_api(
        "GET",
        f"content/{page_id}/child/attachment?filename={_qp(filename, safe='')}&expand=version",
    )
    items = result.get("results", [])
    if not items:
        raise ValueError(f"No attachment '{filename}' found on page {page_id}")

    att = items[0]
    download_path = att.get("_links", {}).get("download", "")
    if not download_path:
        raise ValueError(f"No download link for attachment '{filename}'")

    email = os.environ.get("CONFLUENCE_EMAIL", "") or os.environ.get("ATLASSIAN_EMAIL", "")
    token = os.environ.get("CONFLUENCE_PAT", "") or os.environ.get("ATLASSIAN_PAT", "")
    creds = _b64.b64encode(f"{email}:{token}".encode()).decode()
    base = confluence_browse_url()
    url = f"{base}{download_path}"
    host = urlsplit(url).hostname
    return _safe_http_get(
        url,
        headers={"Authorization": f"Basic {creds}"},
        allowed_hosts={host} if host else set(),
    )


def _fetch_graph_image(url: str) -> tuple[bytes, str]:
    """Fetch an image from graph.microsoft.com with Bearer auth."""
    from skills._m365.helpers import get_graph_client

    gc = get_graph_client()
    token = gc.get_token()
    return _safe_http_get(
        url, headers={"Authorization": f"Bearer {token}"}, allowed_hosts=_GRAPH_HOSTS
    )


def _fetch_teams_image(url: str) -> tuple[bytes, str]:
    """Fetch a Teams/Skype CDN image with Skype token (falls back to Bearer)."""
    from skills._m365.helpers import get_teams_token

    token = get_teams_token()
    host = (urlsplit(url).hostname or "").lower()
    if "asm.skype.com" in host:
        auth_header = f"skype_token {token}"
    else:
        auth_header = f"Bearer {token}"
    return _safe_http_get(
        url, headers={"Authorization": auth_header}, allowed_hosts=_TEAMS_HOSTS
    )


def _fetch_slack_file_by_id(file_id: str) -> tuple[bytes, str, str]:
    """Resolve a Slack file ID to url_private via files.info, then fetch the image."""
    import json as _json
    import urllib.request as _ur
    from skills.slack.mcp_client import get_oauth_token

    token = get_oauth_token()
    if not token:
        raise ValueError("Slack not authenticated")
    req = _ur.Request(
        f"https://slack.com/api/files.info?file={file_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with _ur.urlopen(req, timeout=15) as resp:
        data = _json.loads(resp.read())
    if not data.get("ok"):
        raise ValueError(f"files.info failed: {data.get('error', 'unknown')}")
    f_info = data["file"]
    if not f_info.get("mimetype", "").startswith("image/"):
        raise ValueError(f"File {file_id} is not an image (mimetype: {f_info.get('mimetype')})")
    url = f_info.get("url_private", "")
    name = f_info.get("name", file_id)
    if not url:
        raise ValueError(f"No url_private for file {file_id}")
    image_bytes, ct = _fetch_slack_image(url)
    return image_bytes, ct, name


def _fetch_slack_image(url: str) -> tuple[bytes, str]:
    """Fetch a Slack-hosted image using the stored Slack OAuth token."""
    from skills.slack.mcp_client import get_oauth_token

    token = get_oauth_token()
    if not token:
        raise ValueError("Slack not authenticated — sign in via Settings → Apps → Slack")
    return _safe_http_get(
        url, headers={"Authorization": f"Bearer {token}"}, allowed_hosts=_SLACK_HOSTS
    )


def _fetch_unauthenticated(url: str) -> tuple[bytes, str]:
    return _safe_http_get(url)


def _save_image(data: bytes, content_type: str, hint: str = "") -> str:
    """Save image bytes to ~/.gator/outputs/fetch_image/<uuid>/ and return the path."""
    from config import OUTPUTS_DIR

    ext_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }
    ext = ext_map.get(content_type, ".png")
    out_dir = OUTPUTS_DIR / "fetch_image" / uuid.uuid4().hex[:12]
    out_dir.mkdir(parents=True, exist_ok=True)
    # Integration metadata and URL paths are untrusted. Normalize both POSIX
    # and Windows separators to a basename, then generate a conservative local
    # filename rather than joining caller-controlled path components.
    raw_name = Path(PureWindowsPath(hint).name).name
    stem = Path(raw_name).stem or "image"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "image"
    out_root = out_dir.resolve()
    out_path = (out_root / f"{stem}{ext}").resolve()
    try:
        out_path.relative_to(out_root)
    except ValueError as exc:
        raise ValueError("Refusing to save image outside its output directory.") from exc
    out_path.write_bytes(data)
    return str(out_path)


def _tool_fetch_image(
    url: str = "",
    page_id: str = "",
    filename: str = "",
    source: str = "auto",
) -> dict:
    try:
        if page_id and filename:
            # Confluence attachment
            data, ct = _fetch_confluence_attachment(page_id, filename)
            hint = filename
        elif url and url.startswith("slack-file:"):
            # Slack shared file link — resolve file ID to url_private via files.info
            fid = url[len("slack-file:"):]
            data, ct, hint = _fetch_slack_file_by_id(fid)
        elif url:
            # Auth is selected exclusively from the validated URL host. Never
            # trust the model-supplied `source` flag to decide where a token goes.
            detected = _detect_source(url)
            if detected == "graph":
                data, ct = _fetch_graph_image(url)
            elif detected == "teams":
                data, ct = _fetch_teams_image(url)
            elif detected == "slack":
                data, ct = _fetch_slack_image(url)
            else:
                data, ct = _fetch_unauthenticated(url)
            hint = url.rsplit("/", 1)[-1].split("?")[0] or "image"
        else:
            return {"error": "Provide either url or both page_id + filename."}

        file_path = _save_image(data, ct, hint)
        size_kb = len(data) // 1024
        return {
            "fetch_succeeded": True,
            "file_path": file_path,
            "content_type": ct,
            "size_kb": size_kb,
            "next_action": "Call describe_images with this file_path. Do not report any earlier downloader failure as a fetch_image failure.",
            "_user_message": f"Image fetched and saved ({size_kb} KB). Reading it now...",
        }
    except Exception as ex:
        return {"error": f"Could not fetch image: {ex}"}


TOOL_HANDLERS = {
    "fetch_image": _tool_fetch_image,
}
