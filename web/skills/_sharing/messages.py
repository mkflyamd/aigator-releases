"""The aigator://share link and the one message text used by every draft channel."""

import base64
import binascii
import html
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


# [[Name]] marks a label the reader will see in the app: quoted in text, bold in HTML.
_STEPS = (
    ("Copy the link", "Copy the whole link below, starting with aigator://."),
    (
        "Open AI Gator",
        "Click the [[Skill Marketplace]] button (a hammer-and-screwdriver icon, in the row just above the box where you "
        "type your prompt). Then click the [[+ Add]] tab and choose [[Import from URL]].",
    ),
    (
        "Paste it to review the skill",
        "Paste the link into [[Share link]] and click [[Review]]. Nothing installs until you click [[Install]].",
    ),
)
_HEADING_COLOR = "#1f8f4e"


def _labels(detail: str, left: str, right: str) -> str:
    return detail.replace("[[", left).replace("]]", right)


def share_message(title: str, author: str, description: str, link: str, web_url: str = "") -> str:
    lines = [f'{_flat(author)} shared the AI Gator skill "{_flat(title)}" with you.']
    summary = _flat(description, _MAX_DESCRIPTION)
    if summary:
        lines += ["", summary]
    lines += ["", "To add it in AI Gator:"]
    for n, (head, detail) in enumerate(_STEPS, 1):
        lines.append(f"{n}. {head}. {_labels(detail, '"', '"')}")
        if n == 1:
            lines.append(f"   {link}")
    if web_url:
        lines += ["", f"If you cannot open AI Gator, the skill is in OneDrive: {web_url}"]
    return "\n".join(lines)


def share_message_html(title: str, author: str, description: str, link: str, web_url: str = "") -> str:
    """Same content as share_message, as headings and paragraphs using only tags and styles the draft sanitizer keeps."""
    def esc(text: str) -> str:
        return html.escape(text, quote=False)

    parts = [f'<p>{esc(_flat(author))} shared the AI Gator skill <b>"{esc(_flat(title))}"</b> with you.</p>']
    summary = _flat(description, _MAX_DESCRIPTION)
    if summary:
        parts.append(f"<p>{esc(summary)}</p>")
    parts.append("<p><b>To add it in AI Gator:</b></p>")
    for n, (head, detail) in enumerate(_STEPS, 1):
        parts.append(f'<h2 style="color: {_HEADING_COLOR}">{n}. {esc(head)}</h2><p>{_labels(esc(detail), "<b>", "</b>")}</p>')
        if n == 1:
            parts.append(f"<p><b>{esc(link)}</b></p>")
    if web_url:
        link_attr = html.escape(web_url, quote=True)
        parts.append(f'<p>If you cannot open AI Gator, the skill is in OneDrive: <a href="{link_attr}">{esc(web_url)}</a></p>')
    return "".join(parts)
