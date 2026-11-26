from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_handoff as ah
import agent_sessions as ags
import generic_agent
from routes import generic_agent_routes
from security import verify_csrf

FAKE = "aigator-fake-api-key"
STORED = {"agent": "claude", "project_id": "demo", "repo_path": "C:\\work\\app", "session_id": "abc-1"}


def client():
    app = FastAPI()
    app.include_router(generic_agent_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(ah, "HANDOFF_DIR", tmp_path / "h")
    monkeypatch.setattr(ah, "_configured_api_keys", lambda: [FAKE])
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: (None, {}))
    monkeypatch.setattr(generic_agent, "is_installed", lambda a: True)
    transcript = tmp_path / "abc-1.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        ags, "find_session",
        lambda repo, agent, sid, **kw: {"id": sid, "agent": agent, "path": str(transcript)} if sid == "abc-1" else None,
    )
    monkeypatch.setattr(
        ah, "render_transcript",
        lambda agent, path, red=None: (f"user: hi\nassistant: key {FAKE}", "hi", "done"),
    )
    return transcript


def test_prepare_from_transcript_saves_a_redacted_snapshot(env):
    record = ah.prepare_handoff_from_transcript("claude", "demo", "C:\\work\\app", env)
    assert record["source_kind"] == "transcript" and record["source_agent"] == "claude"
    snap = (ah.HANDOFF_DIR / f"{record['handoff_id']}.txt").read_text(encoding="utf-8")
    assert FAKE not in snap and "[REDACTED]" in snap
    assert record["redactions"] >= 1


def test_prepare_from_transcript_with_nothing_to_render_raises(env, monkeypatch):
    monkeypatch.setattr(ah, "render_transcript", lambda agent, path, red=None: ("  ", "", ""))
    with pytest.raises(ah.NothingToHandOff):
        ah.prepare_handoff_from_transcript("claude", "demo", "C:\\work\\app", env)


def test_prepare_from_transcript_unreadable_raises_nothing_to_hand_off(env, monkeypatch):
    def boom(agent, path, red=None):
        raise OSError("gone")

    monkeypatch.setattr(ah, "render_transcript", boom)
    with pytest.raises(ah.NothingToHandOff):
        ah.prepare_handoff_from_transcript("claude", "demo", "C:\\work\\app", env)


def test_route_prepares_from_a_stored_session(env):
    r = client().post("/api/generic-agent/handoff/prepare", json=STORED)
    assert r.status_code == 200
    data = r.json()
    assert data["source_kind"] == "transcript" and len(data["handoff_id"]) == 32
    assert isinstance(data["targets"], list)


def test_route_needs_exactly_one_source(env):
    c = client()
    both = {**STORED, "pty_session_id": "p1"}
    neither = {k: v for k, v in STORED.items() if k != "session_id"}
    assert c.post("/api/generic-agent/handoff/prepare", json=both).status_code == 400
    assert c.post("/api/generic-agent/handoff/prepare", json=neither).status_code == 400


def test_route_rejects_bad_stored_requests(env):
    c = client()
    assert c.post("/api/generic-agent/handoff/prepare", json={**STORED, "agent": "crush"}).status_code == 400
    assert c.post("/api/generic-agent/handoff/prepare", json={**STORED, "session_id": "bad id"}).status_code == 400
    assert c.post("/api/generic-agent/handoff/prepare", json={**STORED, "session_id": "missing"}).status_code == 404


def test_route_empty_stored_session_is_422(env, monkeypatch):
    monkeypatch.setattr(ah, "render_transcript", lambda agent, path, red=None: ("", "", ""))
    assert client().post("/api/generic-agent/handoff/prepare", json=STORED).status_code == 422


def test_existing_live_prepare_still_requires_a_pty_id(env, monkeypatch):
    monkeypatch.setattr(ah, "find_transcript", lambda agent, cwd, home=None, **kw: None)
    monkeypatch.setattr(ah, "_session_started_at", lambda sid: None)
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: "pane")
    monkeypatch.setattr(ah, "verify_session_owner", lambda agent, project_id, sid: None)
    live = {"agent": "claude", "project_id": "demo", "repo_path": "C:\\work\\app", "pty_session_id": "p1"}
    assert client().post("/api/generic-agent/handoff/prepare", json=live).status_code == 200
