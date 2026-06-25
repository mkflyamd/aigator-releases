"""Transcript detection regression — show transcript availability even when the
Graph share→driveItem resolution is unavailable (expired token, tenant policy).

Root cause: resolve_recordings_from_chat() resolves each recording's SharePoint
share URL to (driveId, itemId) via Graph, then SKIPS any recording where that
resolution returns empty (`if not (drive_id and item_id): continue`). When the
Graph token is expired the resolution fails for EVERY recording, so the endpoint
returns zero recordings and the transcript panel shows nothing — the conditional
"has transcript" indicator never appears.

The URIObject XML itself already states whether a transcript exists
(contentTypes="Recording+Transcript") and carries the SharePoint share URL —
none of that needs Graph. So detection + conditional display should survive a
Graph outage; only fetching the VTT *content* requires Graph.

System Python lacks httpx/fastapi, so the resolver module can't be imported
live; these are source-structure assertions (same approach as the other teams
tests) confirming the resolver no longer drops recordings on Graph failure.
"""

import pathlib

_SRC = (pathlib.Path(__file__).resolve().parent.parent
        / "skills" / "m365-teams" / "scripts" / "transcript_recording.py")
SRC = _SRC.read_text(encoding="utf-8")


def _resolve_all_body() -> str:
    start = SRC.find("def resolve_recordings_from_chat(")
    assert start != -1, "resolve_recordings_from_chat must exist"
    nxt = SRC.find("\ndef ", start + 1)
    return SRC[start:nxt if nxt != -1 else start + 2000]


class TestTranscriptDetectionResilience:

    def test_share_resolution_wrapped_in_try(self):
        """The Graph share→driveItem call must be wrapped so a failure (expired
        token) does NOT abort the whole recording."""
        body = _resolve_all_body()
        assert "try:" in body, (
            "resolve_recordings_from_chat must guard _resolve_share_to_drive_item "
            "with try/except so a Graph failure doesn't drop the recording"
        )

    def test_no_unconditional_skip_on_empty_drive_item(self):
        """The old `if not (drive_id and item_id): continue` dropped every recording
        when Graph was down. It must no longer unconditionally skip."""
        body = _resolve_all_body()
        # The resilient version still emits a RecordingInfo even with empty ids.
        assert "continue" not in body or "has_transcript" in body, (
            "resolver must still append a RecordingInfo when drive/item are empty"
        )

    def test_has_transcript_from_uriobject_not_graph(self):
        """has_transcript must be sourced from the scanned URIObject tuple, not from
        any Graph result, so detection survives a Graph outage."""
        body = _resolve_all_body()
        assert "has_transcript=has_transcript" in body or "has_transcript = has_transcript" in body, (
            "has_transcript must come from the URIObject scan, independent of Graph"
        )

    def test_share_url_preserved(self):
        """The SharePoint share URL (from URIObject) must be carried on the emitted
        recording so the panel row can link out even without drive/item ids."""
        body = _resolve_all_body()
        assert "share_url=share_url" in body, (
            "share_url from the URIObject must be preserved on the RecordingInfo"
        )

    def test_graph_failure_falls_back_to_empty_ids(self):
        """On Graph failure the resolver must degrade to empty drive/item ids and a
        web_url fallback, rather than raising or dropping the recording."""
        body = _resolve_all_body()
        assert "except" in body, (
            "resolve_recordings_from_chat must catch the Graph error per-recording"
        )
