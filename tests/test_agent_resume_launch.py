import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_mcp
import agent_sessions as ags
import agent_state
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
    monkeypatch.setattr(generic_agent, "_linked_sessions", {})
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
    assert spawn["command"] == [
        "C:\\bin\\claude.exe",
        "--resume",
        "abc-1",
        "--settings",
        agent_state.claude_settings_path(),
        "--mcp-config",
        agent_mcp.mcp_config_path(),
    ]
    assert spawn["cwd"] == "C:\\work\\app"
    token = spawn["env"].pop(agent_mcp.TOKEN_ENV)
    assert agent_mcp.caller_for(token)["pty_id"] == r.json()["pty_session_id"]
    assert spawn["env"] == {"K": "v", **agent_state.launch_env(r.json()["pty_session_id"])}
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
    assert c.post("/api/generic-agent/terminal", json={**BODY, "agent": "aider"}).status_code == 400
    assert c.post("/api/generic-agent/terminal", json={**BODY, "resume_id": "bad id"}).status_code == 400
    assert c.post("/api/generic-agent/terminal", json={**BODY, "handoff_id": "f" * 32}).status_code == 400
    assert c.post("/api/generic-agent/terminal", json={**BODY, "resume_id": "missing"}).status_code == 404
    assert env["spawn"] == []


def test_resume_that_cannot_run_here_is_409(env, monkeypatch):
    monkeypatch.setattr(generic_agent, "build_resume_command", lambda *a, **kw: None)
    r = client().post("/api/generic-agent/terminal", json=BODY)
    assert r.status_code == 409
    assert env["spawn"] == []


def test_resuming_a_session_that_is_already_live_reuses_its_terminal(env, monkeypatch):
    import routes.terminal as terminal
    from types import SimpleNamespace

    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: SimpleNamespace(done=False))
    c = client()
    first = c.post("/api/generic-agent/terminal", json=BODY).json()
    second = c.post("/api/generic-agent/terminal", json=BODY).json()
    assert first["created"] is True
    assert second == {"pty_session_id": first["pty_session_id"], "created": False}
    assert len(env["spawn"]) == 1


def test_resuming_after_the_terminal_exited_spawns_again(env, monkeypatch):
    import routes.terminal as terminal
    from types import SimpleNamespace

    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: SimpleNamespace(done=True))
    c = client()
    c.post("/api/generic-agent/terminal", json=BODY)
    assert c.post("/api/generic-agent/terminal", json=BODY).json()["created"] is True
    assert len(env["spawn"]) == 2


def test_a_resumed_crush_terminal_keeps_the_gateway_env_and_links_its_session(env, monkeypatch):
    monkeypatch.setattr(generic_agent, "build_crush_env", lambda: {"CRUSH_GLOBAL_CONFIG": "cfg"})
    monkeypatch.setattr(agent_state, "crush_supports_hooks", lambda exe: True)
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda agent: f"C:\\bin\\{agent}.exe")
    r = client().post("/api/generic-agent/terminal", json={**BODY, "agent": "crush"})
    assert r.status_code == 200
    assert env["resume"][-1]["agent"] == "crush" and env["resume"][-1]["id"] == "abc-1"
    spawn = env["spawn"][-1]
    assert spawn["command"] == ["C:\\bin\\crush.exe", "--resume", "abc-1"]
    pty = r.json()["pty_session_id"]
    token = spawn["env"].pop(agent_mcp.TOKEN_ENV)
    assert agent_mcp.caller_for(token) == {"pty_id": pty, "project_id": "demo", "agent": "crush"}
    assert spawn["env"] == {"CRUSH_GLOBAL_CONFIG": "cfg", **agent_state.launch_env(pty)}
    assert generic_agent.linked_session_id(pty) == "abc-1"


def test_a_crush_terminal_gets_no_token_when_its_hooks_cannot_be_confirmed(env, monkeypatch):
    monkeypatch.setattr(generic_agent, "build_crush_env", lambda: {"CRUSH_GLOBAL_CONFIG": "cfg"})
    monkeypatch.setattr(agent_state, "crush_supports_hooks", lambda exe: False)
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda agent: f"C:\\bin\\{agent}.exe")
    r = client().post("/api/generic-agent/terminal", json={**BODY, "agent": "crush"})
    assert r.status_code == 200
    assert agent_mcp.TOKEN_ENV not in env["spawn"][-1]["env"]
    assert not agent_mcp.holds_token(r.json()["pty_session_id"])


def test_a_resumed_opencode_terminal_passes_the_session_to_the_bare_command(env, monkeypatch):
    seen = []

    def fake_bare(repo_path, session_id=None):
        seen.append((repo_path, session_id))
        return ["C:\\bin\\opencode.exe", "--session", session_id, repo_path]

    monkeypatch.setattr(generic_agent, "build_opencode_bare_command", fake_bare)
    monkeypatch.setattr(generic_agent, "build_opencode_bare_env", lambda: {"OPENCODE_CONFIG_CONTENT": "{}"})
    r = client().post("/api/generic-agent/terminal", json={**BODY, "agent": "opencode-bare"})
    assert r.status_code == 200
    assert seen == [("C:\\work\\app", "abc-1")]
    assert env["spawn"][-1]["env"] == {"OPENCODE_CONFIG_CONTENT": "{}", **agent_state.launch_env(r.json()["pty_session_id"])}
    assert generic_agent.linked_session_id(r.json()["pty_session_id"]) == "abc-1"


def test_a_resumed_codex_terminal_is_linked_to_its_session(env, monkeypatch):
    monkeypatch.setattr(
        ags, "find_session",
        lambda repo, agent, sid, **kw: {"id": sid, "agent": agent, "source": "windows", "cwd": repo},
    )
    r = client().post("/api/generic-agent/terminal", json={**BODY, "agent": "codex", "resume_id": "x1"})
    pty = r.json()["pty_session_id"]
    assert generic_agent.linked_session_id(pty) == "x1"
    assert generic_agent.pinned_session_id(pty) is None


async def test_a_wake_resumes_under_the_old_terminal_id_and_marks_who_woke_it(env, monkeypatch):
    cleared = []
    monkeypatch.setattr(agent_state, "clear", cleared.append)
    req = generic_agent_routes.GenericAgentTerminalRequest(**BODY)
    old = "11111111-2222-3333-4444-555555555555"
    result = await generic_agent_routes.resume_suspended(req, old, "Turn issues", "please look")
    assert result == {"pty_session_id": old, "created": True}
    spawn = env["spawn"][-1]
    assert spawn["sid"] == old
    assert spawn["meta"]["woken_by"] == "Turn issues" and spawn["meta"]["woken_preview"] == "please look"
    assert spawn["meta"]["woken_at"].isdigit()
    assert spawn["meta"]["project_id"] == "demo" and spawn["meta"]["agent"] == "claude"
    assert cleared == [old]
    assert generic_agent.pinned_session_id(old) == "abc-1"
    assert agent_mcp.caller_for(spawn["env"][agent_mcp.TOKEN_ENV])["pty_id"] == old


def test_an_ordinary_resume_takes_a_new_terminal_id_and_is_not_marked_as_woken(env):
    r = client().post("/api/generic-agent/terminal", json=BODY)
    spawn = env["spawn"][-1]
    assert spawn["sid"] == r.json()["pty_session_id"]
    assert "woken_by" not in spawn["meta"]


async def test_a_wake_of_a_session_that_is_already_running_returns_that_terminal(env, monkeypatch):
    import routes.terminal as terminal
    from types import SimpleNamespace

    monkeypatch.setattr(generic_agent, "ptys_for_session", lambda agent, sid: ["live-1"])
    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: SimpleNamespace(done=False))
    req = generic_agent_routes.GenericAgentTerminalRequest(**BODY)
    result = await generic_agent_routes.resume_suspended(req, "old-pty", "Turn issues")
    assert result == {"pty_session_id": "live-1", "created": False}
    assert env["spawn"] == []
