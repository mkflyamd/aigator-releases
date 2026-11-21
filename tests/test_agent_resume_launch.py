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
    r = client().post("/api/generic-agent/terminal", json={**BODY, "agent": "crush"})
    assert r.status_code == 200
    assert env["resume"][-1]["agent"] == "crush" and env["resume"][-1]["id"] == "abc-1"
    spawn = env["spawn"][-1]
    assert spawn["command"] == ["C:\\bin\\crush.exe", "--resume", "abc-1"]
    assert spawn["env"] == {"CRUSH_GLOBAL_CONFIG": "cfg"}
    assert generic_agent.linked_session_id(r.json()["pty_session_id"]) == "abc-1"


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
    assert env["spawn"][-1]["env"] == {"OPENCODE_CONFIG_CONTENT": "{}"}
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


LIVE_PROC = {"pid": 4242, "session_id": "abc-1", "name": "work", "started_at": 1.0, "source": "claude-registry"}


def test_resume_of_a_session_open_in_another_window_is_a_409_with_the_process(env, monkeypatch):
    import agent_liveness

    monkeypatch.setattr(agent_liveness, "live_processes", lambda agent, sid=None: [LIVE_PROC])
    r = client().post("/api/generic-agent/terminal", json=BODY)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "session_live" and detail["processes"] == [LIVE_PROC]
    assert env["spawn"] == []


def test_a_duplicate_of_a_session_open_elsewhere_cannot_be_forced(env, monkeypatch):
    import agent_liveness

    monkeypatch.setattr(agent_liveness, "live_processes", lambda agent, sid=None: [LIVE_PROC])
    r = client().post("/api/generic-agent/terminal", json={**BODY, "allow_duplicate": True})
    assert r.status_code == 409
    assert env["spawn"] == []


def test_the_409_names_where_the_session_is_open(env, monkeypatch):
    import agent_liveness

    monkeypatch.setattr(agent_liveness, "live_processes", lambda agent, sid=None: [LIVE_PROC])
    monkeypatch.setattr(agent_liveness, "location_label", lambda pid: "Orca")
    r = client().post("/api/generic-agent/terminal", json=BODY)
    assert r.json()["detail"]["where"] == {"app": "Orca", "pid": 4242}


def test_resume_of_a_session_a_gator_terminal_runs_reattaches_instead_of_duplicating(env, monkeypatch):
    import agent_liveness
    import routes.terminal as terminal

    class _Live:
        done = False

    monkeypatch.setattr(agent_liveness, "live_processes", lambda agent, sid=None: [LIVE_PROC])
    monkeypatch.setattr(terminal, "pty_pid_map", lambda strict=False: {1: "p-owner"})
    monkeypatch.setattr(agent_liveness, "owning_pty", lambda pid, owners: "p-owner" if pid == 4242 else None)
    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: _Live() if sid == "p-owner" else None)
    r = client().post("/api/generic-agent/terminal", json=BODY)
    assert r.status_code == 200
    assert r.json() == {"pty_session_id": "p-owner", "created": False}
    assert env["spawn"] == []


def test_resume_still_409s_when_the_owning_terminal_is_gone(env, monkeypatch):
    import agent_liveness
    import routes.terminal as terminal

    monkeypatch.setattr(agent_liveness, "live_processes", lambda agent, sid=None: [LIVE_PROC])
    monkeypatch.setattr(terminal, "pty_pid_map", lambda strict=False: {1: "p-owner"})
    monkeypatch.setattr(agent_liveness, "owning_pty", lambda pid, owners: "p-owner")
    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: None)
    r = client().post("/api/generic-agent/terminal", json=BODY)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "session_live"


def test_pty_pid_map_keeps_local_owners_and_logs_when_the_host_list_fails(monkeypatch, caplog):
    import routes.terminal as terminal
    from types import SimpleNamespace

    local = SimpleNamespace(pid=77, done=False)
    monkeypatch.setattr(terminal, "_pty_sessions", {"p-local": local})
    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(terminal.pty_client, "find_host", lambda key: {"port": 1})
    monkeypatch.setattr(terminal.pty_client, "instance_key", lambda: "k")

    def boom(info, msg):
        raise terminal.pty_client.HostError("down")

    monkeypatch.setattr(terminal.pty_client, "host_request", boom)
    with caplog.at_level("WARNING"):
        assert terminal.pty_pid_map() == {77: "p-local"}
    assert "PTY host list failed" in caplog.text


def test_resume_refuses_to_spawn_when_the_owner_lookup_fails(env, monkeypatch):
    import agent_liveness
    import routes.terminal as terminal

    def boom(info, msg):
        raise terminal.pty_client.HostError("down")

    monkeypatch.setattr(agent_liveness, "live_processes", lambda agent, sid=None: [LIVE_PROC])
    monkeypatch.setattr(terminal, "_pty_sessions", {})
    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(terminal.pty_client, "find_host", lambda key: {"port": 1})
    monkeypatch.setattr(terminal.pty_client, "instance_key", lambda: "k")
    monkeypatch.setattr(terminal.pty_client, "host_request", boom)
    r = client().post("/api/generic-agent/terminal", json=BODY)
    assert r.status_code == 503
    assert env["spawn"] == []


def test_pty_pid_map_strict_raises_when_the_host_list_fails(monkeypatch):
    import routes.terminal as terminal

    monkeypatch.setattr(terminal, "_pty_sessions", {})
    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(terminal.pty_client, "find_host", lambda key: {"port": 1})
    monkeypatch.setattr(terminal.pty_client, "instance_key", lambda: "k")

    def boom(info, msg):
        raise terminal.pty_client.HostError("down")

    monkeypatch.setattr(terminal.pty_client, "host_request", boom)
    with pytest.raises(terminal.pty_client.HostError):
        terminal.pty_pid_map(strict=True)


TAKEOVER = {"agent": "claude", "repo_path": "C:\work\app", "resume_id": "abc-1"}


@pytest.fixture
def takeover_env(env, monkeypatch):
    import agent_liveness
    import routes.terminal as terminal

    calls = []
    monkeypatch.setattr(terminal, "pty_pid_map", lambda strict=False: {1: "p-owner"})

    def fake_takeover(agent, session_id, owners):
        calls.append((agent, session_id, owners))
        return [4242]

    monkeypatch.setattr(agent_liveness, "takeover", fake_takeover)
    return calls


def test_takeover_ends_the_outside_process_and_does_not_spawn(takeover_env, env):
    r = client().post("/api/generic-agent/takeover", json=TAKEOVER)
    assert r.status_code == 200 and r.json() == {"terminated": [4242]}
    assert takeover_env == [("claude", "abc-1", {1: "p-owner"})]
    assert env["spawn"] == []


def test_takeover_rejects_an_unknown_session_without_ending_anything(takeover_env):
    r = client().post("/api/generic-agent/takeover", json={**TAKEOVER, "resume_id": "nope"})
    assert r.status_code == 404
    assert takeover_env == []


def test_takeover_rejects_a_malformed_id_and_an_unsupported_agent(takeover_env):
    assert client().post("/api/generic-agent/takeover", json={**TAKEOVER, "resume_id": "../x"}).status_code == 400
    assert client().post("/api/generic-agent/takeover", json={**TAKEOVER, "agent": "bogus"}).status_code == 400
    assert takeover_env == []


def test_takeover_that_cannot_end_the_process_is_a_409_and_never_duplicates(takeover_env, env, monkeypatch):
    import agent_liveness

    def refuse(agent, session_id, owners):
        raise agent_liveness.TakeoverError("Gator could not close it (access denied).")

    monkeypatch.setattr(agent_liveness, "takeover", refuse)
    r = client().post("/api/generic-agent/takeover", json=TAKEOVER)
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": "takeover_failed", "message": "Gator could not close it (access denied)."}
    assert env["spawn"] == []


def test_takeover_refuses_when_the_owner_lookup_fails(takeover_env, monkeypatch):
    import routes.terminal as terminal

    def boom(strict=False):
        raise terminal.pty_client.HostError("down")

    monkeypatch.setattr(terminal, "pty_pid_map", boom)
    r = client().post("/api/generic-agent/takeover", json=TAKEOVER)
    assert r.status_code == 503
    assert takeover_env == []


def _host_file_with(tmp_path, monkeypatch, content):
    import pty_client

    path = tmp_path / "host.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(pty_client, "host_file", lambda key: path)
    return pty_client


def test_a_live_host_process_that_does_not_answer_counts_as_unreachable(tmp_path, monkeypatch):
    import os

    pty_client = _host_file_with(tmp_path, monkeypatch, '{"pid": %d, "port": 1}' % os.getpid())
    assert pty_client.host_alive_but_unreachable("k") is True


@pytest.mark.parametrize("content", [None, "not json", "{}", '{"pid": 2147480000}'])
def test_no_host_a_garbled_host_file_or_a_dead_host_is_not_unreachable(tmp_path, monkeypatch, content):
    pty_client = _host_file_with(tmp_path, monkeypatch, content)
    assert pty_client.host_alive_but_unreachable("k") is False


def test_pty_pid_map_strict_raises_when_a_live_host_does_not_answer(monkeypatch):
    import routes.terminal as terminal

    monkeypatch.setattr(terminal, "_pty_sessions", {})
    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(terminal.pty_client, "find_host", lambda key: None)
    monkeypatch.setattr(terminal.pty_client, "host_alive_but_unreachable", lambda key: True)
    monkeypatch.setattr(terminal.pty_client, "instance_key", lambda: "k")
    with pytest.raises(terminal.pty_client.HostError):
        terminal.pty_pid_map(strict=True)
    assert terminal.pty_pid_map() == {}


def test_pty_pid_map_strict_allows_no_host_at_all(monkeypatch):
    import routes.terminal as terminal

    monkeypatch.setattr(terminal, "_pty_sessions", {})
    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(terminal.pty_client, "find_host", lambda key: None)
    monkeypatch.setattr(terminal.pty_client, "host_alive_but_unreachable", lambda key: False)
    monkeypatch.setattr(terminal.pty_client, "instance_key", lambda: "k")
    assert terminal.pty_pid_map(strict=True) == {}


def test_takeover_ends_nothing_when_the_pty_host_is_alive_but_silent(env, monkeypatch):
    import agent_liveness
    import routes.terminal as terminal

    ended = []
    monkeypatch.setattr(agent_liveness, "takeover", lambda *a: ended.append(a) or [1])
    monkeypatch.setattr(terminal, "_pty_sessions", {})
    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(terminal.pty_client, "find_host", lambda key: None)
    monkeypatch.setattr(terminal.pty_client, "host_alive_but_unreachable", lambda key: True)
    monkeypatch.setattr(terminal.pty_client, "instance_key", lambda: "k")
    r = client().post("/api/generic-agent/takeover", json=TAKEOVER)
    assert r.status_code == 503
    assert ended == []
