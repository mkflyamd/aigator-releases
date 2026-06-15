"""Locate the recording attached to a Teams meeting chat.

Teams posts a `RichText/Media_CallRecording` message into the meeting chat when
the recording finishes. The message embeds a SharePoint share URL for the
recording's .mp4 file. We:

  1. Read the chat via the Skype FOCI path (the only path that returns
     non-message events when the Graph Chat.Read scope is unavailable).
  2. Parse the URIObject XML to extract the share URL and metadata.
  3. Resolve the share URL via Graph `/shares/{id}/driveItem` to obtain
     (driveId, itemId) — the inputs to transcript_beta.

`contentTypes="...Transcript..."` on the RecordingContent element tells us
whether a transcript exists. We surface that so callers can skip cards for
recordings that never produced one.
"""
from __future__ import annotations

import base64
import importlib.util
import re
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_M365 = _SCRIPTS.parent.parent / "_m365"
if str(_M365) not in sys.path:
    sys.path.insert(0, str(_M365))
from helpers import get_graph_client  # type: ignore


_RECORDING_MSGTYPE = "RichText/Media_CallRecording"
_SHARE_HREF_RE = re.compile(r'<a\s+href="(https://[^"]*sharepoint\.com[^"]+)"', re.IGNORECASE)
_TITLE_RE = re.compile(r'<Title>([^<]*)</Title>')
_ORIGINAL_NAME_RE = re.compile(r'<OriginalName\s+v="([^"]*)"\s*/>')
_CONTENT_TYPES_RE = re.compile(r'<RecordingContent[^>]*contentTypes="([^"]*)"')


@dataclass
class RecordingInfo:
    drive_id: str
    item_id: str
    title: str
    original_name: str
    has_transcript: bool
    share_url: str
    web_url: str
    created_at: str = ""


def _load_skype():
    spec = importlib.util.spec_from_file_location(
        "_tx_read_chats", str(_SCRIPTS / "read_chats.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_tx_read_chats"] = mod
    spec.loader.exec_module(mod)
    return mod


def _encode_share_id(share_url: str) -> str:
    """Convert a SharePoint share URL to a Graph share ID (u! + b64url, no padding)."""
    b64 = base64.urlsafe_b64encode(share_url.encode("utf-8")).decode("ascii").rstrip("=")
    return "u!" + b64


def _parse_recording_message(content: str) -> tuple[str, str, str, bool] | None:
    """Return (share_url, title, original_name, has_transcript) from URIObject XML."""
    m = _SHARE_HREF_RE.search(content or "")
    if not m:
        return None
    share_url = m.group(1)
    title = (_TITLE_RE.search(content) or [None, ""])[1]
    name = (_ORIGINAL_NAME_RE.search(content) or [None, ""])[1]
    ctypes = (_CONTENT_TYPES_RE.search(content) or [None, ""])[1]
    has_tx = "transcript" in (ctypes or "").lower()
    return share_url, title, name, has_tx


def _scan_chat_for_recordings(chat_id: str, limit: int = 50) -> list[tuple[str, str, str, bool, str]]:
    """Read the chat via Skype FOCI and return all recording attachments, newest first.

    Each tuple is (share_url, title, original_name, has_transcript, composetime).
    """
    rc = _load_skype()
    skype_token, messaging_service = rc.get_auth()
    encoded = urllib.parse.quote(chat_id, safe="")
    url = (
        f"{messaging_service}/users/ME/conversations/{encoded}/messages"
        f"?pageSize={limit}&view=msnp24Equivalent|supportsMessageProperties"
    )
    data = rc._get(url, skype_token)
    msgs = data.get("messages", []) or []
    msgs.sort(key=lambda m: m.get("composetime", ""), reverse=True)
    out: list[tuple[str, str, str, bool, str]] = []
    for m in msgs:
        if m.get("messagetype") != _RECORDING_MSGTYPE:
            continue
        parsed = _parse_recording_message(m.get("content", ""))
        if parsed:
            out.append((*parsed, m.get("composetime", "")))
    return out


def _scan_chat_for_recording(chat_id: str, limit: int = 50) -> tuple[str, str, str, bool] | None:
    """Newest recording attachment in the chat, or None. Back-compat wrapper."""
    found = _scan_chat_for_recordings(chat_id, limit)
    if not found:
        return None
    share_url, title, original_name, has_tx, _ct = found[0]
    return share_url, title, original_name, has_tx


def _resolve_share_to_drive_item(share_url: str) -> tuple[str, str, str]:
    """Return (drive_id, item_id, web_url) from a SharePoint share URL."""
    gc = get_graph_client()
    share_id = _encode_share_id(share_url)
    # `!` is meaningful in the share id; keep it unescaped in the path.
    item = gc.get(f"/shares/{urllib.parse.quote(share_id, safe='!')}/driveItem")
    parent = (item or {}).get("parentReference") or {}
    return parent.get("driveId", ""), item.get("id", ""), item.get("webUrl", "")


def resolve_recording_from_chat(chat_id: str) -> RecordingInfo | None:
    """Find the newest recording for a Teams meeting chat. None if none posted."""
    recs = resolve_recordings_from_chat(chat_id)
    return recs[0] if recs else None


def resolve_recordings_from_chat(chat_id: str) -> list[RecordingInfo]:
    """All recordings posted in a Teams meeting chat, newest first."""
    found = _scan_chat_for_recordings(chat_id)
    if not found:
        return []
    out: list[RecordingInfo] = []
    for share_url, title, original_name, has_transcript, composetime in found:
        drive_id, item_id, web_url = _resolve_share_to_drive_item(share_url)
        if not (drive_id and item_id):
            continue
        out.append(RecordingInfo(
            drive_id=drive_id,
            item_id=item_id,
            title=title,
            original_name=original_name,
            has_transcript=has_transcript,
            share_url=share_url,
            web_url=web_url,
            created_at=composetime,
        ))
    return out


_MEETING_THREAD_RE = re.compile(r"(19[%:]meeting_[^/?@]+(?:[%@]thread\.v2))")


def chat_id_from_join_url(join_url: str) -> str | None:
    """Extract the meeting chat id (19:meeting_...@thread.v2) from a Teams join URL."""
    if not join_url:
        return None
    m = _MEETING_THREAD_RE.search(join_url)
    if not m:
        return None
    return urllib.parse.unquote(m.group(1))


def resolve_recording_from_event(event_id: str) -> RecordingInfo | None:
    """Calendar event → joinUrl → meeting chat id → recording."""
    gc = get_graph_client()
    ev = gc.get(f"/me/events/{urllib.parse.quote(event_id, safe='')}")
    join_url = ((ev or {}).get("onlineMeeting") or {}).get("joinUrl", "")
    chat_id = chat_id_from_join_url(join_url)
    if not chat_id:
        return None
    return resolve_recording_from_chat(chat_id)
