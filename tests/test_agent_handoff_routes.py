"""Handoff routes: prepare, launch with handoff_id, gateway env, CSRF."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_handoff as ah
import generic_agent
from routes import generic_agent_routes
from security import verify_csrf

FAKE = "aigator-fake-api-key"
BODY = {"agent": "claude", "project_id": "demo", "repo_path": "/r", "pty_session_id": "s1"}


def _app(override_csrf=True):
    app = FastAPI()
    app.include_router(generic_agent_routes.router)
    if override_csrf:
        app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)


@pytest.fixture
def handoff_env(tmp_path, monkeypatch):
    monkeypatch.setattr(ah, "HANDOFF_DIR", tmp_path / "h")
    monkeypatch.setattr(ah, "_active_api_key", lambda: FAKE)
    monkeypatch.setattr(ah, "find_transcript", lambda agent, cwd, home=None: None)
    monkeypatch.setattr(ah, "capture_pane", lambda sid: f"pane output {FAKE}")


@pytest.fixture
def spawned(monkeypatch):
    calls = []

    def fake_create(session_id, **kwargs):
        calls.append({"session_id": session_id, **kwargs})

    import routes.terminal as terminal
    monkeypatch.setattr(terminal, "create_pty_session", fake_create)
    monkeypatch.setattr(generic_agent, "build_opencode_bare_command", lambda repo: ["opencode"])
    monkeypatch.setattr(
        generic_agent, "build_opencode_bare_env",
        lambda: {"OPENCODE_CONFIG_CONTENT": "{}", "GATOR_OPENCODE_KEY": FAKE},
    )
    monkeypatch.setattr(generic_agent, "build_command", lambda agent: [agent])
    monkeypatch.setattr(generic_agent, "build_crush_env", lambda: {"CRUSH_GLOBAL_CONFIG": "/c", "GATOR_CRUSH_KEY": FAKE})
    return calls


def test_prepare_returns_preview_and_targets(handoff_env):
    r = _app().post("/api/generic-agent/handoff/prepare", json=BODY)
    assert r.status_code == 200
    data = r.json()
    assert len(data["handoff_id"]) == 32 and data["source_kind"] == "capture"
    routed = {t["agent"]: t["gateway_routed"] for t in data["targets"]}
    assert routed == {"claude": False, "codex": False, "crush": True, "opencode-bare": True}


def test_prepare_nothing_to_hand_off_is_422(handoff_env, monkeypatch):
    monkeypatch.setattr(ah, "capture_pane", lambda sid: "")
    r = _app().post("/api/generic-agent/handoff/prepare", json=BODY)
    assert r.status_code == 422
    assert r.json()["detail"] == "Nothing to hand off from this session."


def test_prepare_requires_csrf(handoff_env):
    assert _app(override_csrf=False).post("/api/generic-agent/handoff/prepare", json=BODY).status_code == 403


def test_launch_with_handoff_returns_prompt_and_gateway_env(handoff_env, spawned):
    client = _app()
    hid = client.post("/api/generic-agent/handoff/prepare", json=BODY).json()["handoff_id"]
    r = client.post("/api/generic-agent/terminal", json={
        "agent": "opencode-bare", "project_id": "demo", "repo_path": "/r", "handoff_id": hid,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["created"] is True and "Continue work from a prior Claude Code session" in data["handoff_prompt"]
    assert FAKE not in data["handoff_prompt"]
    env = spawned[-1]["env"]
    assert "OPENCODE_CONFIG_CONTENT" in env and "GATOR_OPENCODE_KEY" in env


def test_launch_with_handoff_crush_gets_crush_env(handoff_env, spawned):
    client = _app()
    hid = client.post("/api/generic-agent/handoff/prepare", json=BODY).json()["handoff_id"]
    client.post("/api/generic-agent/terminal", json={
        "agent": "crush", "project_id": "demo", "repo_path": "/r", "handoff_id": hid,
    })
    assert "CRUSH_GLOBAL_CONFIG" in spawned[-1]["env"]


def test_handoff_always_spawns_new_process(handoff_env, spawned, monkeypatch):
    client = _app()
    hid = client.post("/api/generic-agent/handoff/prepare", json=BODY).json()["handoff_id"]
    generic_agent.set_active_session("demo", "opencode-bare", "existing")
    r = client.post("/api/generic-agent/terminal", json={
        "agent": "opencode-bare", "project_id": "demo", "repo_path": "/r",
        "handoff_id": hid, "force_new": False,
    })
    assert r.json()["created"] is True and spawned[-1]["session_id"] != "existing"


def test_unknown_handoff_is_404_and_spawns_nothing(handoff_env, spawned):
    r = _app().post("/api/generic-agent/terminal", json={
        "agent": "opencode-bare", "project_id": "demo", "repo_path": "/r", "handoff_id": "0" * 32,
    })
    assert r.status_code == 404 and spawned == []


def test_launch_logs_target_and_gateway_flag(handoff_env, spawned, caplog):
    client = _app()
    hid = client.post("/api/generic-agent/handoff/prepare", json=BODY).json()["handoff_id"]
    with caplog.at_level(logging.INFO, logger="agent_handoff"):
        client.post("/api/generic-agent/terminal", json={
            "agent": "opencode-bare", "project_id": "demo", "repo_path": "/r", "handoff_id": hid,
        })
    lines = [r.getMessage() for r in caplog.records if "stage=launched" in r.getMessage()]
    assert len(lines) == 1
    assert "source=claude target=opencode-bare" in lines[0] and "gateway_routed=true" in lines[0]
    assert FAKE not in lines[0] and "pane output" not in lines[0]
