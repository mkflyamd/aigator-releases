"""The aigator://share link and the one message text used by every draft channel."""

import base64
import binascii
import json
from urllib.parse import parse_qs, urlparse

from .errors import ShareError

_MAX_LINK = 2048
_MAX_ID = 512
_MAX_DESCRIPTION = 300


def _invalid() -> ShareError:
    return ShareError("invalid_link", "This is not a valid AI Gator share link.")


def make_share_link(folder: dict) -> str:
    payload = json.dumps(
        {"v": 1, "drive_id": folder["drive_id"], "folder_id": folder["folder_id"]},
        separators=(",", ":"),
        sort_keys=True,
    )
    return "aigator://share?d=" + base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def parse_share_link(url: str) -> dict:
    if not isinstance(url, str) or len(url) > _MAX_LINK:
        raise _invalid()
    try:
        parts = urlparse(url)
        query = parse_qs(parts.query)
    except ValueError:
        raise _invalid() from None
    if parts.scheme != "aigator" or parts.netloc != "share" or parts.path not in ("", "/"):
        raise _invalid()
    values = query.get("d") or []
    if len(values) != 1 or not values[0]:
        raise _invalid()
    encoded = values[0]
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        doc = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError):
        raise _invalid() from None
    if not isinstance(doc, dict) or set(doc) != {"v", "drive_id", "folder_id"} or doc["v"] != 1:
        raise _invalid()
    drive_id, folder_id = doc["drive_id"], doc["folder_id"]
    for value in (drive_id, folder_id):
        if not isinstance(value, str) or not value or len(value) > _MAX_ID:
            raise _invalid()
    return {"drive_id": drive_id, "folder_id": folder_id}


def _flat(text: str, limit: int = 0) -> str:
    out = " ".join(str(text or "").split())
    return out[:limit] if limit else out


def share_message(title: str, author: str, description: str, link: str, web_url: str = "") -> str:
    lines = [f'{_flat(author)} shared the AI Gator skill "{_flat(title)}" with you.']
    summary = _flat(description, _MAX_DESCRIPTION)
    if summary:
        lines += ["", summary]
    lines += [
        "",
        "Open it in AI Gator. You can review what it does before anything is installed:",
        link,
    ]
    if web_url:
        lines += ["", f"If the link does not open, the skill is in OneDrive: {web_url}"]
    return "\n".join(lines)
