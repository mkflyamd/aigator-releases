"""Teams meeting transcript tools: find a meeting's transcript and save the original VTT to OneDrive."""

import importlib.util as _txi
import re
import sys as _txsys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TX_SCRIPTS = Path(__file__).parent.parent / "m365-teams" / "scripts"
_TX_ROOT_FOLDER = "Gator Meeting Transcripts"


def _tx_load(name: str):
    mod = _txsys.modules.get(f"_tx_{name}")
    if mod is not None:
        return mod
    spec = _txi.spec_from_file_location(f"_tx_{name}", str(_TX_SCRIPTS / f"{name}.py"))
    mod = _txi.module_from_spec(spec)
    # Register before exec so dataclasses resolve cls.__module__ correctly (Py 3.12+)
    _txsys.modules[f"_tx_{name}"] = mod
    # Also put scripts dir on sys.path so transcript_cache's `from transcript_config import ...` resolves
    if str(_TX_SCRIPTS) not in _txsys.path:
        _txsys.path.insert(0, str(_TX_SCRIPTS))
    spec.loader.exec_module(mod)
    return mod


_IDS = {
    "drive_id": {
        "type": "string",
        "description": "OneDrive driveId where the recording lives.",
    },
    "item_id": {"type": "string", "description": "DriveItem id of the recording .mp4."},
    "transcript_id": {
        "type": "string",
        "description": "Transcript id from find_meeting_transcripts.",
    },
}

MEETING_TOOL_DEFS = [
    {
        "name": "find_meeting_transcripts",
        "description": "Find the recording and transcripts of a Teams calendar meeting from its calendar event id (from read_calendar). Returns the recordings of that meeting's chat, best match for the event first, each with its transcript ids, ready for get_meeting_transcript_* or save_meeting_transcript. An empty list means the meeting has no transcript (not a Teams meeting, no chat, or transcription was off); say so instead of guessing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Calendar event id.",
                }
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "save_meeting_transcript",
        "description": "Save the original, unmodified transcript (.vtt) of a meeting into the user's own OneDrive under Documents/Gator Meeting Transcripts/<year>-W<week>/ and return its link plus transcripts_folder_web_url, the link to the Gator Meeting Transcripts folder that holds every week. Never overwrites: saving the same transcript again returns status=exists. The file is private to the user; do not share it. Report it as saved only when status=saved or exists.",
        "input_schema": {
            "type": "object",
            "properties": {
                **_IDS,
                "meeting_title": {"type": "string"},
                "meeting_start": {
                    "type": "string",
                    "description": "Meeting start, ISO 8601 (used for the file name and week folder, in the user's local time). Pass the start from find_meeting_transcripts unchanged.",
                },
                "folder": {
                    "type": "string",
                    "description": "Optional OneDrive folder path to use instead of the default week folder.",
                },
            },
            "required": [
                "drive_id",
                "item_id",
                "transcript_id",
                "meeting_title",
                "meeting_start",
            ],
        },
    },
]

MEETING_TOOL_STATUS = {
    "find_meeting_transcripts": "\U0001f4dd Finding meeting transcript...",
    "save_meeting_transcript": "\U0001f4be Saving meeting transcript to OneDrive...",
}


def _graph():
    from .._m365.helpers import get_graph_client

    return get_graph_client()


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _tx_local_iso(value) -> str:
    dt = _tx_parse_dt(value)
    if dt is None:
        return (value or {}).get("dateTime", "") if isinstance(value, dict) else ""
    return dt.astimezone(_local_tz()).isoformat(timespec="seconds")


def _tx_parse_dt(value) -> datetime | None:
    text = (
        (value or {}).get("dateTime", "") if isinstance(value, dict) else (value or "")
    )
    text = str(text).strip().replace("Z", "+00:00")
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(.*)$", text)
    if m:
        text = m.group(1) + (m.group(2) or "")[:7] + m.group(3)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _tool_find_meeting_transcripts(event_id: str) -> dict:
    import urllib.parse

    tx_rec = _tx_load("transcript_recording")
    tx_beta = _tx_load("transcript_beta")
    ev = _graph().get(f"/me/events/{urllib.parse.quote(event_id, safe='')}") or {}
    start, end = _tx_parse_dt(ev.get("start")), _tx_parse_dt(ev.get("end"))
    out = {
        "event": {
            "subject": ev.get("subject", ""),
            "start": _tx_local_iso(ev.get("start")),
            "end": _tx_local_iso(ev.get("end")),
        },
        "recordings": [],
    }
    join_url = (ev.get("onlineMeeting") or {}).get("joinUrl", "")
    chat_id = tx_rec.chat_id_from_join_url(join_url)
    if not chat_id:
        out["status"] = "no_transcript: not a Teams meeting"
        return out
    rows = []
    for r in tx_rec.resolve_recordings_from_chat(chat_id):
        made = _tx_parse_dt(getattr(r, "created_at", ""))
        matches = bool(
            made
            and start
            and end
            and start - timedelta(hours=1) <= made <= end + timedelta(hours=12)
        )
        distance = abs((made - end).total_seconds()) if made and end else float("inf")
        transcripts = []
        if r.has_transcript and r.drive_id and r.item_id:
            try:
                transcripts = [
                    {
                        "id": t.get("id"),
                        "created": t.get("createdDateTime"),
                        "language": t.get("languageTag"),
                    }
                    for t in tx_beta.list_transcripts(r.drive_id, r.item_id)
                ]
            except Exception:
                transcripts = []
        rows.append(
            (
                not matches,
                distance,
                {
                    "drive_id": r.drive_id,
                    "item_id": r.item_id,
                    "title": r.title,
                    "created_at": getattr(r, "created_at", ""),
                    "web_url": r.web_url,
                    "matches_event": matches,
                    "transcripts": transcripts,
                },
            )
        )
    rows.sort(key=lambda x: (x[0], x[1]))
    out["recordings"] = [r[2] for r in rows]
    if not any(r["transcripts"] for r in out["recordings"]):
        out["status"] = "no_transcript: no transcript found for this meeting"
    return out


def _tool_save_meeting_transcript(
    drive_id: str,
    item_id: str,
    transcript_id: str,
    meeting_title: str,
    meeting_start: str,
    folder: str = "",
) -> dict:
    import hashlib
    from .._m365 import file_transfer

    when = _tx_parse_dt(meeting_start)
    if when is None:
        return {"status": "error", "error": "bad_meeting_start"}
    when = when.astimezone(_local_tz())
    data = _tx_load("transcript_beta").fetch_transcript_bytes(
        drive_id, item_id, transcript_id
    )
    if not data:
        return {"status": "error", "error": "empty_transcript"}
    iso = when.isocalendar()
    folder = folder.strip() or (
        f"Documents/{_TX_ROOT_FOLDER}/{iso[0]}-W{iso[1]:02d}"
    )
    short = hashlib.sha256(transcript_id.encode()).hexdigest()[:8]
    title = (meeting_title or "Meeting").strip()[:80]
    name = f"{when:%Y-%m-%d} {title} [{short}].vtt"
    out = file_transfer.store(_graph(), file_transfer.bytes_source(name, data), folder)
    for f in out.get("folders") or []:
        if f["path"].endswith(_TX_ROOT_FOLDER):
            out["transcripts_folder_web_url"] = f["web_url"]
    return out


MEETING_TOOL_HANDLERS = {
    "find_meeting_transcripts": _tool_find_meeting_transcripts,
    "save_meeting_transcript": _tool_save_meeting_transcript,
}
