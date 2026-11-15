import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_sessions as ags
import generic_agent
from routes import generic_agent_routes
from security import verify_csrf

BODY = {"agent": "claude", "project_id": "demo", "repo_path": "C:\\work\\app", "resume_id": "abc-1"}


def client():
    app = FastAPI()
    app.include_router(generic_agent_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)


@pytest.fixture
def env(monkeypatch):
    calls = {"spawn": [], "resume": []}

    import routes.terminal as terminal

    monkeypatch.setattr(terminal, "create_pty_session", lambda sid, **kw: calls["spawn"].append({"sid": sid, **kw}))
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: (None, {}))
    monkeypatch.setattr(generic_agent, "effective_binding", lambda agent: (("-c", "x=1"), {"K": "v"}))
    monkeypatch.setattr(generic_agent, "_pinned_sessions", {})
    monkeypatch.setattr(generic_agent, "_active_sessions", {})
    monkeypatch.setattr(
        ags, "find_session",
        lambda repo, agent, sid, **kw: {"id": sid, "agent": agent, "source": "windows", "cwd": repo} if sid == "abc-1" else None,
    )

    def fake_resume(agent, repo_path, session_id, source="windows", extra_args=()):
        calls["resume"].append({"agent": agent, "repo_path": repo_path, "id": session_id, "source": source, "extra": extra_args})
        return [f"C:\\bin\\{agent}.exe", "--resume", session_id]

    monkeypatch.setattr(generic_agent, "build_resume_command", fake_resume)
    return calls


def test_resume_spawns_the_resume_command_and_pins_the_session(env):
    r = client().post("/api/generic-agent/terminal", json=BODY)
    assert r.status_code == 200 and r.json()["created"] is True
    assert env["resume"] == [
        {"agent": "claude", "repo_path": "C:\\work\\app", "id": "abc-1", "source": "windows", "extra": ("-c", "x=1")}
    ]
    spawn = env["spawn"][-1]
    assert spawn["command"] == ["C:\\bin\\claude.exe", "--resume", "abc-1"]
    assert spawn["cwd"] == "C:\\work\\app"
    assert spawn["env"] == {"K": "v"}
    assert generic_agent.pinned_session_id(r.json()["pty_session_id"]) == "abc-1"


def test_resume_of_a_worktree_session_spawns_in_that_worktree(env, monkeypatch, tmp_path):
    rec = {"id": "abc-1", "agent": "claude", "source": "windows", "cwd": str(tmp_path)}
    monkeypatch.setattr(ags, "find_session", lambda repo, agent, sid, **kw: rec)
    client().post("/api/generic-agent/terminal", json=BODY)
    assert env["spawn"][-1]["cwd"] == str(tmp_path)


def test_resume_always_spawns_even_when_a_live_session_exists(env, monkeypatch):
    import routes.terminal as terminal
    from types import SimpleNamespace

    monkeypatch.setattr(generic_agent, "_active_sessions", {("demo", "claude"): "existing"})
    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: SimpleNamespace(done=False))
    r = client().post("/api/generic-agent/terminal", json=BODY)
    assert r.json()["created"] is True and r.json()["pty_session_id"] != "existing"
    assert len(env["spawn"]) == 1


def test_resume_of_a_wsl_session_runs_in_its_distro_with_the_linux_path(env, monkeypatch):
    wsl = {"id": "abc-1", "agent": "claude", "source": "wsl:Ubuntu", "cwd": "/mnt/c/work/app"}
    monkeypatch.setattr(ags, "find_session", lambda repo, agent, sid, **kw: wsl)
    client().post("/api/generic-agent/terminal", json=BODY)
    assert env["resume"][-1]["repo_path"] == "/mnt/c/work/app"
    assert env["resume"][-1]["source"] == "wsl:Ubuntu"
    assert env["spawn"][-1]["cwd"] == "C:\\work\\app"


def test_resume_rejects_bad_requests(env):
    c = client()
    assert c.post("/api/generic-agent/terminal", json={**BODY, "agent": "crush"}).status_code == 400
    assert c.post("/api/generic-agent/terminal", json={**BODY, "resume_id": "bad id"}).status_code == 400
    assert c.post("/api/generic-agent/terminal", json={**BODY, "handoff_id": "f" * 32}).status_code == 400
    assert c.post("/api/generic-agent/terminal", json={**BODY, "resume_id": "missing"}).status_code == 404
    assert env["spawn"] == []


def test_resume_that_cannot_run_here_is_409(env, monkeypatch):
    monkeypatch.setattr(generic_agent, "build_resume_command", lambda *a, **kw: None)
    r = client().post("/api/generic-agent/terminal", json=BODY)
    assert r.status_code == 409
    assert env["spawn"] == []
