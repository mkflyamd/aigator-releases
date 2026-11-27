import pathlib
import sys
import time
import uuid
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi.testclient import TestClient

import agent_suspend
from app import app
from relay import settings as relay_settings
from relay import service
from relay.core import Relay, write_audit
from routes import terminal
from sandbox import policy as pol


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def csrf():
    from security import get_csrf_token

    return {"X-CSRF-Token": get_csrf_token("testserver")}


@pytest.fixture
def world(tmp_path, monkeypatch):
    live: dict = {}
    monkeypatch.setattr(agent_suspend, "STATE_FILE", tmp_path / "suspended-agents.json")
    monkeypatch.setattr(terminal, "live_pty_labels", lambda: dict(live))
    monkeypatch.setattr("agent_wake.title_of", lambda project, agent, session: f"title-{session}")
    path = tmp_path / "sandbox-policy.json"
    monkeypatch.setattr(pol, "policy_path", lambda: path)
    monkeypatch.setattr(pol, "_is_posix", lambda: False)
    pol._reset_cache()
    monkeypatch.setattr(service, "_relay", Relay(audit=lambda line: None))
    return {"live": live, "policy": path}


def agent(world, session, project="demo"):
    pid = str(uuid.uuid4())
    now = time.time()
    agent_suspend._remember(
        pid, {"agent": "claude", "project_id": project, "session_id": session, "title": session, "at": now}, now
    )
    return f"pty:{pid}"


def test_state_lists_the_agents_and_the_switches(client, csrf, world):
    first = agent(world, "alpha")
    body = client.get("/api/relay", headers=csrf).json()
    assert body["admin_allows"] is True and body["enabled"] is True
    assert [a["id"] for a in body["agents"]] == [first]
    assert body["agents"][0]["name"] == "alpha" and body["agents"][0]["opted_out"] is False
    assert body["links"] == []


def test_the_admin_lock_shows_in_the_state(client, csrf, world):
    world["policy"].write_text('{"agent_messaging": "deny"}')
    pol._reset_cache()
    assert client.get("/api/relay", headers=csrf).json()["admin_allows"] is False


def test_reads_need_the_csrf_token_too(client, world):
    agent(world, "alpha")
    assert client.get("/api/relay").status_code == 403
    assert client.get("/api/relay/audit").status_code == 403


def test_every_change_needs_the_csrf_token(client, world):
    a, b = agent(world, "alpha"), agent(world, "beta")
    assert client.post("/api/relay/settings", json={"enabled": False}).status_code == 403
    assert client.post("/api/relay/links", json={"a": a, "b": b}).status_code == 403
    assert client.delete("/api/relay/links/x").status_code == 403
    assert client.post("/api/relay/stop-all").status_code == 403
    assert client.post("/api/relay/self-chat-autosend", json={"enabled": True}).status_code == 403
    assert relay_settings.user_allows_self_chat_autosend() is False
    assert client.post("/api/relay/opt-out", json={"endpoint_id": a, "opted_out": True}).status_code == 403
    assert relay_settings.user_allows_messaging() is True


def test_the_user_switch_round_trips(client, csrf, world):
    assert client.post("/api/relay/settings", json={"enabled": False}, headers=csrf).json() == {"enabled": False}
    assert client.get("/api/relay", headers=csrf).json()["enabled"] is False
    client.post("/api/relay/settings", json={"enabled": True}, headers=csrf)
    assert client.get("/api/relay", headers=csrf).json()["enabled"] is True


def test_the_self_chat_switch_round_trips_and_shows_the_admin_lock(client, csrf, world):
    state = client.get("/api/relay", headers=csrf).json()
    assert state["self_chat_autosend"] is False and state["self_chat_admin_allows"] is True
    assert client.post("/api/relay/self-chat-autosend", json={"enabled": True}, headers=csrf).json() == {"enabled": True}
    assert client.get("/api/relay", headers=csrf).json()["self_chat_autosend"] is True
    world["policy"].write_text('{"self_chat_autosend": "deny"}')
    pol._reset_cache()
    assert client.get("/api/relay", headers=csrf).json()["self_chat_admin_allows"] is False
    assert relay_settings.self_chat_autosend_allowed() is False


def test_a_link_is_made_between_two_known_agents_and_can_be_stopped(client, csrf, world):
    a, b = agent(world, "alpha"), agent(world, "beta", project="other")
    made = client.post("/api/relay/links", json={"a": a, "b": b, "hours": 2}, headers=csrf)
    assert made.status_code == 200
    link = made.json()
    assert {link["a"]["id"], link["b"]["id"]} == {a, b}
    assert link["b"]["project_id"] == "other" and link["active"] is True
    assert [item["id"] for item in client.get("/api/relay", headers=csrf).json()["links"]] == [link["id"]]
    assert client.delete(f"/api/relay/links/{link['id']}", headers=csrf).status_code == 200
    assert client.get("/api/relay", headers=csrf).json()["links"] == []
    assert client.delete(f"/api/relay/links/{link['id']}", headers=csrf).status_code == 200
    assert client.delete("/api/relay/links/nope", headers=csrf).status_code == 404


def test_a_link_with_no_hours_lasts_eight_hours(client, csrf, world):
    a, b = agent(world, "alpha"), agent(world, "beta")
    link = client.post("/api/relay/links", json={"a": a, "b": b}, headers=csrf).json()
    lasts = datetime.fromisoformat(link["expires_at"]).timestamp() - time.time()
    assert abs(lasts - 8 * 3600) < 60


def test_a_link_needs_two_different_agents_that_exist(client, csrf, world):
    a = agent(world, "alpha")
    assert client.post("/api/relay/links", json={"a": a, "b": a}, headers=csrf).status_code == 400
    assert client.post("/api/relay/links", json={"a": a, "b": "pty:missing"}, headers=csrf).status_code == 404
    assert client.post("/api/relay/links", json={"a": a, "b": "chat:tab"}, headers=csrf).status_code == 404


def test_a_link_cannot_outlast_the_maximum(client, csrf, world):
    a, b = agent(world, "alpha"), agent(world, "beta")
    assert client.post("/api/relay/links", json={"a": a, "b": b, "hours": 25}, headers=csrf).status_code == 422
    assert client.post("/api/relay/links", json={"a": a, "b": b, "hours": 0}, headers=csrf).status_code == 422


def test_no_link_while_messaging_is_off(client, csrf, world):
    a, b = agent(world, "alpha"), agent(world, "beta")
    client.post("/api/relay/settings", json={"enabled": False}, headers=csrf)
    assert client.post("/api/relay/links", json={"a": a, "b": b}, headers=csrf).status_code == 403
    client.post("/api/relay/settings", json={"enabled": True}, headers=csrf)
    world["policy"].write_text('{"agent_messaging": "deny"}')
    pol._reset_cache()
    assert client.post("/api/relay/links", json={"a": a, "b": b}, headers=csrf).status_code == 403


def test_a_paused_link_shows_why_and_the_user_can_resume_it(client, csrf, world):
    a, b = agent(world, "alpha"), agent(world, "beta")
    link = client.post("/api/relay/links", json={"a": a, "b": b}, headers=csrf).json()
    service._relay._links[link["id"]].paused = "limit_reached"
    shown = client.get("/api/relay", headers=csrf).json()["links"][0]
    assert shown["paused"] == "limit_reached"
    assert client.post(f"/api/relay/links/{link['id']}/resume").status_code == 403
    assert client.post(f"/api/relay/links/{link['id']}/resume", headers=csrf).json() == {"resumed": link["id"]}
    assert client.get("/api/relay", headers=csrf).json()["links"][0]["paused"] == ""
    assert client.post("/api/relay/links/nope/resume", headers=csrf).status_code == 404


def test_a_link_cannot_be_resumed_while_messaging_is_off(client, csrf, world):
    a, b = agent(world, "alpha"), agent(world, "beta")
    link = client.post("/api/relay/links", json={"a": a, "b": b}, headers=csrf).json()
    service._relay._links[link["id"]].paused = "repeated"
    client.post("/api/relay/settings", json={"enabled": False}, headers=csrf)
    assert client.post(f"/api/relay/links/{link['id']}/resume", headers=csrf).status_code == 403


def test_stop_all_ends_every_link(client, csrf, world):
    a, b, c = agent(world, "alpha"), agent(world, "beta"), agent(world, "gamma")
    client.post("/api/relay/links", json={"a": a, "b": b}, headers=csrf)
    client.post("/api/relay/links", json={"a": b, "b": c}, headers=csrf)
    assert len(client.get("/api/relay", headers=csrf).json()["links"]) == 2
    assert client.post("/api/relay/stop-all", headers=csrf).json() == {"stopped": True}
    assert client.get("/api/relay", headers=csrf).json()["links"] == []


def test_an_agent_can_opt_out_and_back_in(client, csrf, world):
    a = agent(world, "alpha")
    out = client.post("/api/relay/opt-out", json={"endpoint_id": a, "opted_out": True}, headers=csrf)
    assert out.json() == {"endpoint_id": a, "opted_out": True}
    assert client.get("/api/relay", headers=csrf).json()["agents"][0]["opted_out"] is True
    client.post("/api/relay/opt-out", json={"endpoint_id": a, "opted_out": False}, headers=csrf)
    assert client.get("/api/relay", headers=csrf).json()["agents"][0]["opted_out"] is False
    assert client.post("/api/relay/opt-out", json={"endpoint_id": "chat:x", "opted_out": True}, headers=csrf).status_code == 400


def test_the_audit_lists_newest_first(client, csrf, world):
    for n in range(3):
        write_audit({"event": "test", "n": n})
    events = client.get("/api/relay/audit?limit=2", headers=csrf).json()["events"]
    assert [e["n"] for e in events] == [2, 1]
