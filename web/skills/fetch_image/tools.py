"""fetch_image skill — download an image from any supported integration and save
it to disk so the LLM can read it with vision.

Supports:
  - Confluence attachments  (by page_id + filename)
  - Microsoft Graph images  (email inline, OneNote, SharePoint)
  - Teams images            (Skype/ASM CDN, Graph CDN)
  - Any https:// URL        (falls back to unauthenticated fetch)
"""

from __future__ import annotations

import base64
import uuid
from pathlib import Path

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
            "Returns a file_path — read it with vision to describe the image."
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
    from urllib.parse import urlparse

    host = urlparse(url).netloc.lower().split(":")[0]
    if any(host == h or host.endswith("." + h) for h in _GRAPH_HOSTS):
        return "graph"
    if any(host == h or host.endswith("." + h) for h in _TEAMS_HOSTS):
        return "teams"
    if any(host == h or host.endswith("." + h) for h in _SLACK_HOSTS):
        return "slack"
    return "auto"


def _fetch_confluence_attachment(page_id: str, filename: str) -> tuple[bytes, str]:
    """Fetch a Confluence attachment by page_id + filename. Returns (bytes, content_type)."""
    import base64 as _b64
    import os

    import httpx

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
    resp = httpx.get(url, headers={"Authorization": f"Basic {creds}"}, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    ct = resp.headers.get("content-type", "image/png").split(";")[0]
    return resp.content, ct


def _fetch_graph_image(url: str) -> tuple[bytes, str]:
    """Fetch an image from graph.microsoft.com with Bearer auth."""
    import urllib.request as _ur

    from skills._m365.helpers import get_graph_client

    gc = get_graph_client()
    token = gc.get_token()
    req = _ur.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    with _ur.urlopen(req, timeout=20) as resp:
        ct = resp.headers.get("Content-Type", "image/png").split(";")[0]
        return resp.read(), ct


def _fetch_teams_image(url: str) -> tuple[bytes, str]:
    """Fetch a Teams/Skype CDN image with Skype token (falls back to Bearer)."""
    import urllib.request as _ur

    from skills._m365.helpers import get_teams_token

    token = get_teams_token()
    from urllib.parse import urlparse

    host = urlparse(url).netloc.lower()
    if "asm.skype.com" in host:
        auth_header = f"skype_token {token}"
    else:
        auth_header = f"Bearer {token}"
    req = _ur.Request(url, headers={"Authorization": auth_header}, method="GET")
    with _ur.urlopen(req, timeout=20) as resp:
        ct = resp.headers.get("Content-Type", "image/png").split(";")[0]
        return resp.read(), ct


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
    import urllib.request as _ur
    from skills.slack.mcp_client import get_oauth_token

    token = get_oauth_token()
    if not token:
        raise ValueError("Slack not authenticated — sign in via Settings → Apps → Slack")
    req = _ur.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    with _ur.urlopen(req, timeout=20) as resp:
        ct = resp.headers.get("Content-Type", "image/png").split(";")[0]
        return resp.read(), ct


def _fetch_unauthenticated(url: str) -> tuple[bytes, str]:
    import urllib.request as _ur

    req = _ur.Request(url, method="GET")
    with _ur.urlopen(req, timeout=20) as resp:
        ct = resp.headers.get("Content-Type", "image/png").split(";")[0]
        return resp.read(), ct


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
    name = (hint.rsplit(".", 1)[0] if "." in hint else hint or "image") + ext
    out_dir = OUTPUTS_DIR / "fetch_image" / uuid.uuid4().hex[:12]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / name
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
            detected = _detect_source(url) if source == "auto" else source
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
            "file_path": file_path,
            "content_type": ct,
            "size_kb": size_kb,
            "_user_message": f"Image saved ({size_kb} KB). Reading it now...",
        }
    except Exception as ex:
        return {"error": f"Could not fetch image: {ex}"}


TOOL_HANDLERS = {
    "fetch_image": _tool_fetch_image,
}
