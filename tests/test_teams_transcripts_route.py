# tests/test_teams_transcripts_route.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from routes import teams as teams_route


def make_app():
    app = FastAPI()
    app.include_router(teams_route.router)
    return app


SAMPLE_VTT = """WEBVTT

00:00:00.000 --> 00:00:05.000
<v Alice>Hello.</v>

00:00:05.000 --> 00:00:10.000
<v Bob>Hi.</v>
"""

DRIVE = "b!testdrive"
ITEM = "01ITEMID"
TID = "tx-1"


def test_list_recording_transcripts(monkeypatch):
    monkeypatch.setattr(teams_route, "_tx_list_transcripts",
        lambda d, i: [{"id": TID, "createdDateTime": "2026-05-18T14:00:00Z",
                       "languageTag": "en-US", "displayName": "meeting.json"}])
    client = TestClient(make_app())
    r = client.get(f"/api/recordings/{DRIVE}/{ITEM}/transcripts")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["transcripts"][0]["id"] == TID


def test_header_endpoint(monkeypatch):
    monkeypatch.setattr(teams_route._tx_cache, "read", lambda tid: None)
    monkeypatch.setattr(teams_route._tx_cache, "write", lambda tid, text: None)
    monkeypatch.setattr(teams_route, "_tx_fetch_content", lambda d, i, tid: SAMPLE_VTT)
    client = TestClient(make_app())
    r = client.get(f"/api/recordings/{DRIVE}/{ITEM}/transcripts/{TID}/header")
    assert r.status_code == 200
    body = r.json()
    assert body["cue_count"] == 2
    assert "Alice" in body["speakers"]


def test_range_endpoint(monkeypatch):
    monkeypatch.setattr(teams_route._tx_cache, "read", lambda tid: None)
    monkeypatch.setattr(teams_route._tx_cache, "write", lambda tid, text: None)
    monkeypatch.setattr(teams_route, "_tx_fetch_content", lambda d, i, tid: SAMPLE_VTT)
    client = TestClient(make_app())
    r = client.get(f"/api/recordings/{DRIVE}/{ITEM}/transcripts/{TID}/range",
                   params={"start_min": 0, "end_min": 1})
    assert r.status_code == 200
    assert "Hello" in r.json()["text"]


def test_search_endpoint(monkeypatch):
    monkeypatch.setattr(teams_route._tx_cache, "read", lambda tid: None)
    monkeypatch.setattr(teams_route._tx_cache, "write", lambda tid, text: None)
    monkeypatch.setattr(teams_route, "_tx_fetch_content", lambda d, i, tid: SAMPLE_VTT)
    client = TestClient(make_app())
    r = client.get(f"/api/recordings/{DRIVE}/{ITEM}/transcripts/{TID}/search", params={"q": "hello"})
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_config_endpoint():
    client = TestClient(make_app())
    r = client.get("/api/teams/meetings/config")
    assert r.status_code == 200
    body = r.json()
    assert body["recurring_occurrences_cap"] == 5
    assert body["full_fetch_token_threshold"] == 50_000


def test_chat_recording_resolver_none(monkeypatch):
    monkeypatch.setattr(teams_route, "_tx_resolve_chat", lambda chat_id: None)
    client = TestClient(make_app())
    r = client.get("/api/teams/chats/19:meeting_xxx@thread.v2/recording")
    assert r.status_code == 200
    assert r.json() == {"recording": None}


def test_chat_recording_resolver_swallows_errors(monkeypatch):
    def _boom(chat_id):
        raise RuntimeError("no skype token")
    monkeypatch.setattr(teams_route, "_tx_resolve_chat", _boom)
    client = TestClient(make_app())
    r = client.get("/api/teams/chats/19:meeting_xxx@thread.v2/recording")
    assert r.status_code == 200
    assert r.json() == {"recording": None}


def test_chat_recording_resolver_returns_drive_item(monkeypatch):
    from types import SimpleNamespace
    info = SimpleNamespace(
        drive_id=DRIVE, item_id=ITEM, title="Topic",
        original_name="Topic-Meeting Recording.mp4", has_transcript=True,
        web_url="https://example.sharepoint.com/...", share_url="https://example.sharepoint.com/:v:/...",
        created_at="2026-05-20T14:00:00Z",
    )
    monkeypatch.setattr(teams_route, "_tx_resolve_chat", lambda chat_id: info)
    client = TestClient(make_app())
    r = client.get("/api/teams/chats/19:meeting_xxx@thread.v2/recording")
    assert r.status_code == 200
    body = r.json()["recording"]
    assert body["drive_id"] == DRIVE
    assert body["item_id"] == ITEM
    assert body["has_transcript"] is True
    assert body["created_at"] == "2026-05-20T14:00:00Z"


def test_chat_recordings_plural_returns_list(monkeypatch):
    from types import SimpleNamespace
    recs = [
        SimpleNamespace(
            drive_id=DRIVE, item_id=ITEM, title="Weekly Sync",
            original_name="Weekly Sync-Meeting Recording.mp4", has_transcript=True,
            web_url="https://example.sharepoint.com/a", share_url="https://example.sharepoint.com/:v:/a",
            created_at="2026-05-20T14:00:00Z",
        ),
        SimpleNamespace(
            drive_id=DRIVE, item_id="01OTHER", title="Weekly Sync",
            original_name="Weekly Sync-Meeting Recording.mp4", has_transcript=False,
            web_url="https://example.sharepoint.com/b", share_url="https://example.sharepoint.com/:v:/b",
            created_at="2026-05-13T14:00:00Z",
        ),
    ]
    monkeypatch.setattr(teams_route, "_tx_resolve_chat_all", lambda chat_id: recs)
    client = TestClient(make_app())
    r = client.get("/api/teams/chats/19:meeting_xxx@thread.v2/recordings")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["recordings"][0]["created_at"] == "2026-05-20T14:00:00Z"
    assert body["recordings"][1]["has_transcript"] is False


def test_chat_recordings_plural_swallows_errors(monkeypatch):
    def _boom(chat_id):
        raise RuntimeError("no skype token")
    monkeypatch.setattr(teams_route, "_tx_resolve_chat_all", _boom)
    client = TestClient(make_app())
    r = client.get("/api/teams/chats/19:meeting_xxx@thread.v2/recordings")
    assert r.status_code == 200
    assert r.json() == {"total": 0, "recordings": []}
