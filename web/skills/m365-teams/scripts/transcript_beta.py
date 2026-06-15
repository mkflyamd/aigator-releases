"""Graph beta drive-item transcript endpoints.

Replaces the /me/onlineMeetings/{id}/transcripts path (which requires
OnlineMeetingTranscript.Read.All — often disabled by tenant admins) with the
/beta/drives/{driveId}/items/{itemId}/media/transcripts path, which works with
the Files.ReadWrite.All scope already on the token.

Teams Premium attaches transcripts directly to the recording's drive item.
Resolve (driveId, itemId) for a recording first via transcript_recording, then
call these functions.
"""
from __future__ import annotations

import sys
from pathlib import Path

_M365 = Path(__file__).resolve().parents[2] / "_m365"
if str(_M365) not in sys.path:
    sys.path.insert(0, str(_M365))
from helpers import get_graph_client  # type: ignore

_BETA = "https://graph.microsoft.com/beta"


def list_transcripts(drive_id: str, item_id: str) -> list[dict]:
    """Return raw transcript metadata for a recording (newest first if dated)."""
    gc = get_graph_client()
    data = gc.get(
        f"/drives/{drive_id}/items/{item_id}/media/transcripts",
        base_url=_BETA,
    )
    items = data.get("value", []) if isinstance(data, dict) else []
    items.sort(key=lambda x: x.get("createdDateTime", ""), reverse=True)
    return items


def fetch_transcript_content(drive_id: str, item_id: str, transcript_id: str) -> str:
    """Fetch raw WebVTT for a transcript via the beta drive-item endpoint."""
    gc = get_graph_client()
    return gc.get_text(
        f"/drives/{drive_id}/items/{item_id}/media/transcripts/{transcript_id}/content",
        extra_headers={"Accept": "text/vtt"},
        base_url=_BETA,
    )
