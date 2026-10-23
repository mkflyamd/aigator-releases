"""find_meeting_transcripts / save_meeting_transcript tools."""

import hashlib
from types import SimpleNamespace

import pytest

from skills.teams import tools, transcripts


VTT = b"WEBVTT\r\n\r\n1\r\n00:00:00.000 --> 00:00:02.000\r\n<v Ann>Budget is approved.</v>\r\n"


class FakeGC:
    def __init__(self, event=None):
        self.event = event
        self.paths = []

    def get(self, path, params=None, **kw):
        self.paths.append(path)
        return self.event


def rec(item, created, has=True):
    return SimpleNamespace(
        drive_id="d1", item_id=item, title="AMD <> Cohere", original_name="x.mp4",
        has_transcript=has, share_url="s", web_url=f"https://sp/{item}", created_at=created,
    )


def event(start="2026-10-19T15:00:00.0000000", end="2026-10-19T15:34:00.0000000"):
    return {
        "subject": "AMD <> Cohere",
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
        "onlineMeeting": {"joinUrl": "https://teams/l/meetup-join/19%3ameeting_abc%40thread.v2/0"},
    }


@pytest.fixture
def wired(monkeypatch):
    state = SimpleNamespace(recs=[], transcripts={}, gc=FakeGC(event()))

    recording = SimpleNamespace(
        chat_id_from_join_url=lambda url: "19:meeting_abc@thread.v2" if url else None,
        resolve_recordings_from_chat=lambda chat: state.recs,
    )
    beta = SimpleNamespace(
        list_transcripts=lambda d, i: state.transcripts.get(i, []),
        fetch_transcript_bytes=lambda d, i, t: VTT,
    )

    def fake_load(name):
        return {"transcript_recording": recording, "transcript_beta": beta}[name]

    monkeypatch.setattr(transcripts, "_tx_load", fake_load)
    monkeypatch.setattr(transcripts, "_graph", lambda: state.gc)
    return state


def test_find_returns_transcripts_for_the_event_occurrence(wired):
    wired.recs = [rec("old", "2026-10-12T16:00:00Z"), rec("new", "2026-10-19T15:40:00Z")]
    wired.transcripts = {
        "new": [{"id": "T-new", "createdDateTime": "2026-10-19T15:40:00Z", "languageTag": "en-US"}],
        "old": [{"id": "T-old", "createdDateTime": "2026-10-12T16:00:00Z"}],
    }
    out = transcripts._tool_find_meeting_transcripts("EV1")
    assert out["event"]["subject"] == "AMD <> Cohere"
    best = out["recordings"][0]
    assert best["item_id"] == "new" and best["matches_event"] is True
    assert best["transcripts"][0]["id"] == "T-new"
    assert [r["matches_event"] for r in out["recordings"]] == [True, False]


def test_find_without_teams_meeting_reports_no_transcript(wired):
    wired.gc.event = {"subject": "Lunch", "start": {"dateTime": "2026-10-19T15:00:00", "timeZone": "UTC"},
                      "end": {"dateTime": "2026-10-19T16:00:00", "timeZone": "UTC"}}
    out = transcripts._tool_find_meeting_transcripts("EV1")
    assert out["recordings"] == []
    assert "no_transcript" in out["status"]


def test_find_recording_without_transcript_lists_empty(wired):
    wired.recs = [rec("new", "2026-10-19T15:40:00Z", has=False)]
    out = transcripts._tool_find_meeting_transcripts("EV1")
    assert out["recordings"][0]["transcripts"] == []


class UploadGC:
    def __init__(self):
        self.files = {}
        self.folders = {"Documents"}

    def get(self, path, params=None, **kw):
        key = path.split("/root:/", 1)[1] if "/root:/" in path else ""
        if key in self.folders:
            return {"id": "f", "folder": {}}
        if key in self.files:
            return {"id": "x", "name": key.rsplit("/", 1)[-1], "size": len(self.files[key]), "webUrl": "u"}
        e = Exception("404")
        e.status_code = 404
        raise e

    def post(self, path, body):
        parent = path.split("/root:/", 1)[1].rsplit(":/children", 1)[0] if "/root:/" in path else ""
        self.folders.add(f"{parent}/{body['name']}" if parent else body["name"])
        return {}

    def put_binary(self, path, data, content_type=""):
        key = path.split("/root:/", 1)[1].split(":/content", 1)[0]
        self.files[key] = data
        return {"id": "file1", "name": key.rsplit("/", 1)[-1], "size": len(data), "webUrl": "https://od/" + key}


def test_save_stores_original_bytes_in_week_folder(wired):
    wired.gc = UploadGC()
    out = transcripts._tool_save_meeting_transcript(
        "d1", "new", "ABCDEFGH-1234", meeting_title="AMD <> Cohere", meeting_start="2026-10-19T15:00:00Z"
    )
    assert out["status"] == "saved"
    assert out["sha256"] == hashlib.sha256(VTT).hexdigest()
    short = hashlib.sha256(b"ABCDEFGH-1234").hexdigest()[:8]
    key = f"Documents/Gator Meeting Transcripts/2026-W43/2026-10-19 AMD __ Cohere [{short}].vtt"
    assert wired.gc.files[key] == VTT
    assert out["web_url"].startswith("https://od/")


def test_save_twice_does_not_duplicate_or_overwrite(wired):
    wired.gc = UploadGC()
    args = ("d1", "new", "ABCDEFGH-1234")
    kw = dict(meeting_title="AMD", meeting_start="2026-10-19T15:00:00Z")
    first = transcripts._tool_save_meeting_transcript(*args, **kw)
    second = transcripts._tool_save_meeting_transcript(*args, **kw)
    assert first["status"] == "saved" and second["status"] == "exists"
    assert len(wired.gc.files) == 1


def test_save_empty_transcript_is_error(wired, monkeypatch):
    wired.gc = UploadGC()
    beta = SimpleNamespace(fetch_transcript_bytes=lambda d, i, t: b"")
    monkeypatch.setattr(transcripts, "_tx_load", lambda name: beta)
    out = transcripts._tool_save_meeting_transcript(
        "d1", "new", "T1", meeting_title="AMD", meeting_start="2026-10-19T15:00:00Z"
    )
    assert out["status"] == "error" and out["error"] == "empty_transcript"
    assert wired.gc.files == {}


def test_tools_registered():
    names = {d["name"] for d in tools.TOOL_DEFS}
    assert {"find_meeting_transcripts", "save_meeting_transcript"} <= names
    assert tools.TOOL_HANDLERS["find_meeting_transcripts"]
    assert tools.TOOL_HANDLERS["save_meeting_transcript"]
    assert "find_meeting_transcripts" in tools.TOOL_STATUS
    assert "save_meeting_transcript" in tools.TOOL_STATUS


def test_bytes_fetch_returns_raw_content_without_decoding(monkeypatch):
    import importlib.util, sys
    from pathlib import Path

    scripts = Path(tools.__file__).parent.parent / "m365-teams" / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("_tb_test", scripts / "transcript_beta.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    seen = {}

    class GC:
        def _headers(self):
            return {"Authorization": "Bearer t"}

        def _request(self, method, url, headers=None, content=None, label=""):
            seen.update(method=method, url=url, headers=headers)
            return SimpleNamespace(content=VTT)

    monkeypatch.setattr(mod, "get_graph_client", lambda: GC())
    assert mod.fetch_transcript_bytes("d", "i", "t") == VTT
    assert seen["url"].startswith("https://graph.microsoft.com/beta/drives/d/items/i/media/transcripts/t/content")


REAL_JOIN_URL = (
    "https://teams.microsoft.com/l/meetup-join/"
    "19%3ameeting_NTY0ZTcwZTctZjNkYS00Yzg1LWIzYjctZTMwYWY4Y2U0ZTQy%40thread.v2/0"
    "?context=%7b%22Tid%22%3a%22aigator-fake-tenant%22%7d"
)


def test_chat_id_from_calendar_join_url_as_graph_returns_it():
    rec = transcripts._tx_load("transcript_recording")
    assert (
        rec.chat_id_from_join_url(REAL_JOIN_URL)
        == "19:meeting_NTY0ZTcwZTctZjNkYS00Yzg1LWIzYjctZTMwYWY4Y2U0ZTQy@thread.v2"
    )


def test_chat_id_from_join_url_unencoded_and_empty():
    rec = transcripts._tx_load("transcript_recording")
    assert (
        rec.chat_id_from_join_url("https://teams.microsoft.com/l/meetup-join/19:meeting_abc@thread.v2/0?x=1")
        == "19:meeting_abc@thread.v2"
    )
    assert rec.chat_id_from_join_url("") is None
    assert rec.chat_id_from_join_url("https://example.com/none") is None
