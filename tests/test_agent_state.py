"""Agent-reported state: hook assets, state files, launch wiring, and the read route."""

import json
import os
import shutil
import subprocess
import time
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_state
import generic_agent
from routes import agent_session_routes, generic_agent_routes
from security import verify_csrf

PTY = "0b1f3c5e-1111-4222-8333-444455556666"


@pytest.fixture(autouse=True)
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_state, "STATE_DIR", tmp_path / "agent-state")
    monkeypatch.setattr(agent_state, "HOOKS_DIR", tmp_path / "agent-hooks")
    agent_state.STATE_DIR.mkdir()
    return tmp_path


def put(pty, word, age=0):
    path = agent_state.STATE_DIR / pty
    path.write_text(word, encoding="utf-8")
    if age:
        past = time.time() - age
        os.utime(path, (past, past))
    return path


def test_read_states_returns_word_and_event_time():
    put(PTY, "asking")
    out = agent_state.read_states([PTY])
    assert out[PTY]["state"] == "asking"
    assert abs(out[PTY]["at"] - time.time()) < 5


def test_read_states_ignores_unknown_words_missing_files_and_bad_ids():
    other = str(uuid.uuid4())
    put(other, "rm -rf /")
    put("not-a-uuid", "idle")
    out = agent_state.read_states([other, "not-a-uuid", "../../etc/passwd", str(uuid.uuid4())])
    assert out == {}


def test_read_states_tolerates_trailing_whitespace_and_case():
    put(PTY, " Working\n")
    assert agent_state.read_states([PTY])[PTY]["state"] == "working"


def test_read_states_survives_an_unreadable_entry():
    (agent_state.STATE_DIR / PTY).mkdir()
    assert agent_state.read_states([PTY]) == {}


def test_cleanup_removes_only_old_files():
    old = put(str(uuid.uuid4()), "idle", age=3 * 86400)
    fresh = put(PTY, "idle")
    agent_state.cleanup()
    assert not old.exists() and fresh.exists()


def test_launch_env_names_the_pty_and_a_forward_slash_state_dir():
    env = agent_state.launch_env(PTY)
    assert env["GATOR_PTY_ID"] == PTY
    assert env["GATOR_AGENT_STATE_DIR"] == agent_state.STATE_DIR.as_posix()
    assert agent_state.STATE_DIR.is_dir()


def test_claude_settings_map_events_to_states():
    path = agent_state.claude_settings_path()
    hooks = json.loads(open(path, encoding="utf-8").read())["hooks"]

    def cmd(event):
        return hooks[event][0]["hooks"][0]["command"]

    assert "working" in cmd("UserPromptSubmit")
    assert "working" in cmd("PostToolUse")
    assert "idle" in cmd("Stop")
    assert "asking" in cmd("Notification")
    assert hooks["Notification"][0]["matcher"] == "permission_prompt|elicitation_dialog"
    assert "rm -f" in cmd("SessionEnd")
    assert "idle" in cmd("SessionStart")
    assert hooks["SessionStart"][0]["matcher"] == "startup|resume"
    assert "idle_prompt" not in json.dumps(hooks)
    for event in hooks:
        assert "GATOR_PTY_ID" in cmd(event)


def test_claude_settings_keep_the_permission_payload_until_the_agent_moves_on():
    hooks = json.loads(open(agent_state.claude_settings_path(), encoding="utf-8").read())["hooks"]

    def cmd(event):
        return hooks[event][0]["hooks"][0]["command"]

    assert "cat >" in cmd("PermissionRequest") and ".prompt" in cmd("PermissionRequest")
    assert "mv -f" in cmd("PermissionRequest") and "GATOR_PTY_ID" in cmd("PermissionRequest")
    assert "asking" not in cmd("PermissionRequest")
    for event in ("UserPromptSubmit", "PostToolUse", "Stop", "SessionStart", "SessionEnd"):
        assert "rm -f" in cmd(event) and ".prompt" in cmd(event)
    assert ".prompt" not in cmd("Notification")


@pytest.mark.skipif(shutil.which("bash") is None, reason="hooks run in a POSIX shell")
def test_the_hooks_write_and_remove_the_prompt_file_when_run_by_a_shell():
    hooks = json.loads(open(agent_state.claude_settings_path(), encoding="utf-8").read())["hooks"]
    env = {**os.environ, **agent_state.launch_env(PTY)}

    def run(event, stdin=""):
        command = hooks[event][0]["hooks"][0]["command"]
        subprocess.run([shutil.which("bash"), "-c", command], input=stdin.encode(), env=env, check=True)

    payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    run("PermissionRequest", json.dumps(payload))
    found = agent_state.read_prompt(PTY)
    assert found["payload"] == payload and abs(found["at"] - time.time()) < 60
    assert not [p for p in agent_state.STATE_DIR.iterdir() if p.name.endswith(".tmp")]
    run("Notification")
    assert agent_state.read_states([PTY])[PTY]["state"] == "asking"
    assert agent_state.read_prompt(PTY) is not None
    run("PostToolUse")
    assert agent_state.read_prompt(PTY) is None
    assert agent_state.read_states([PTY])[PTY]["state"] == "working"


def test_read_prompt_returns_the_payload_and_its_event_time():
    path = agent_state.STATE_DIR / (PTY + ".prompt")
    path.write_text(json.dumps({"tool_name": "Bash"}), encoding="utf-8")
    found = agent_state.read_prompt(PTY)
    assert found["payload"] == {"tool_name": "Bash"}
    assert found["at"] == path.stat().st_mtime


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("", id="empty"),
        pytest.param("not json", id="not-json"),
        pytest.param("[1, 2]", id="not-an-object"),
        pytest.param("x" * (agent_state.PROMPT_MAX_BYTES + 1), id="oversize"),
    ],
)
def test_read_prompt_reports_an_unreadable_or_oversize_file_as_a_prompt_with_no_payload(content):
    (agent_state.STATE_DIR / (PTY + ".prompt")).write_text(content, encoding="utf-8")
    found = agent_state.read_prompt(PTY)
    assert found["payload"] is None and found["at"] > 0


def test_read_prompt_ignores_a_missing_file_and_a_bad_id():
    assert agent_state.read_prompt(PTY) is None
    assert agent_state.read_prompt("../../etc/passwd") is None


def test_clear_prompt_and_clear_both_drop_the_prompt_file():
    path = agent_state.STATE_DIR / (PTY + ".prompt")
    path.write_text("{}", encoding="utf-8")
    agent_state.clear_prompt(PTY)
    assert not path.exists()
    path.write_text("{}", encoding="utf-8")
    put(PTY, "asking")
    agent_state.clear(PTY)
    assert not path.exists() and agent_state.read_states([PTY]) == {}
    agent_state.clear_prompt("../../etc/passwd")


def test_set_state_reports_a_word_and_refuses_anything_else():
    agent_state.set_state(PTY, "idle")
    assert agent_state.read_states([PTY])[PTY]["state"] == "idle"
    with pytest.raises(ValueError):
        agent_state.set_state(PTY, "asking now")
    with pytest.raises(ValueError):
        agent_state.set_state("../../etc/passwd", "idle")


def test_the_prompt_file_is_not_mistaken_for_a_session_state():
    put(PTY, "asking")
    (agent_state.STATE_DIR / (PTY + ".prompt")).write_text("{}", encoding="utf-8")
    assert list(agent_state.read_states([PTY])) == [PTY]


def test_clear_drops_a_reported_state_and_ignores_bad_ids():
    put(PTY, "idle")
    agent_state.clear(PTY)
    agent_state.clear("../../etc/passwd")
    agent_state.clear(str(uuid.uuid4()))
    assert agent_state.read_states([PTY]) == {}


def test_with_claude_hooks_appends_settings_for_a_native_claude_only():
    native = agent_state.with_claude_hooks("claude", ["C:/bin/claude.exe", "--session-id", "x"])
    assert native[:3] == ["C:/bin/claude.exe", "--session-id", "x"]
    assert native[3] == "--settings" and native[4] == agent_state.claude_settings_path()
    assert agent_state.with_claude_hooks("codex", ["codex"]) == ["codex"]
    wsl = ["wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc", "exec claude"]
    assert agent_state.with_claude_hooks("claude", wsl) == wsl
    assert agent_state.with_claude_hooks("claude", None) is None


CRUSH_EVENTS = {
    "TurnStart": "working",
    "PermissionRequest": "asking",
    "PermissionResult": "working",
    "TurnEnd": "idle",
    "Interrupt": "idle",
    "StopFailure": "idle",
}


def test_crush_hook_lines_cover_each_event():
    lines = agent_state.crush_hook_lines()
    for event, word in CRUSH_EVENTS.items():
        line = next(ln for ln in lines if ln.startswith(f"hook add {event} "))
        assert word in line and "GATOR_PTY_ID" in line
    assert any(ln.startswith("hook add SessionEnd ") and "rm -f" in ln for ln in lines)


@pytest.mark.parametrize(
    ("version_output", "expected"),
    [("crush version v0.100.0", True), ("crush version 0.99.1", True), ("crush version v0.98.4", False), ("", False)],
)
def test_crush_hooks_need_a_recent_crush(monkeypatch, version_output, expected):
    agent_state._crush_hooks_cache.clear()
    monkeypatch.setattr(agent_state, "_run_version", lambda exe: version_output)
    assert agent_state.crush_supports_hooks("crush.exe") is expected


def test_crush_crushrc_includes_hooks_only_when_supported(monkeypatch):
    profile = {"api_key": "aigator-fake-api-key", "api_key_header": "x-api-key", "anthropic_url": "https://gw"}  # pragma: allowlist secret
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda agent: "crush.exe")
    monkeypatch.setattr(agent_state, "crush_supports_hooks", lambda exe: True)
    assert "hook add TurnEnd " in generic_agent._build_crushrc(profile, ["claude-sonnet"])
    monkeypatch.setattr(agent_state, "crush_supports_hooks", lambda exe: False)
    assert "hook add" not in generic_agent._build_crushrc(profile, ["claude-sonnet"])


def _app():
    app = FastAPI()
    app.include_router(agent_session_routes.router)
    return TestClient(app)


def test_state_route_returns_states_for_requested_ptys():
    put(PTY, "idle")
    r = _app().get("/api/agent-state", params={"pty": [PTY, "bogus"]})
    assert r.status_code == 200
    assert list(r.json()["states"]) == [PTY]
    assert r.json()["states"][PTY]["state"] == "idle"


def test_state_route_with_no_ptys_is_empty():
    assert _app().get("/api/agent-state").json() == {"states": {}}


@pytest.fixture
def spawned(monkeypatch):
    calls = []
    import routes.terminal as terminal

    monkeypatch.setattr(terminal, "create_pty_session", lambda sid, **kw: calls.append({"session_id": sid, **kw}))
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: (None, {}))
    monkeypatch.setattr(generic_agent, "build_command", lambda agent, repo="", extra=(): [f"/bin/{agent}"])
    monkeypatch.setattr(generic_agent, "build_crush_env", lambda: {"CRUSH_GLOBAL_CONFIG": "/c"})
    monkeypatch.setattr(generic_agent, "effective_binding", lambda agent: None)
    return calls


def _launch(agent):
    app = FastAPI()
    app.include_router(generic_agent_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    r = TestClient(app).post(
        "/api/generic-agent/terminal",
        json={"agent": agent, "project_id": "demo", "repo_path": "/r", "force_new": True},
    )
    assert r.status_code == 200, r.text
    return r.json()["pty_session_id"]


@pytest.mark.parametrize("agent", ["claude", "codex", "crush", "terminal"])
def test_every_launch_gets_the_pty_id_and_state_dir(spawned, agent):
    pty = _launch(agent)
    env = spawned[-1]["env"]
    assert env["GATOR_PTY_ID"] == pty
    assert env["GATOR_AGENT_STATE_DIR"] == agent_state.STATE_DIR.as_posix()
    if agent == "crush":
        assert env["CRUSH_GLOBAL_CONFIG"] == "/c"


def test_claude_launch_points_claude_at_the_hook_settings(spawned):
    _launch("claude")
    command = spawned[-1]["command"]
    assert command[command.index("--settings") + 1] == agent_state.claude_settings_path()


def test_other_agents_are_not_given_claude_settings(spawned):
    _launch("codex")
    assert "--settings" not in spawned[-1]["command"]


def test_wsl_launch_is_left_to_the_output_heuristic(spawned, monkeypatch):
    monkeypatch.setattr(
        generic_agent, "build_command", lambda agent, repo="", extra=(): ["wsl.exe", "-d", "U", "--", "bash", "-lc", "x"]
    )
    _launch("claude")
    assert "GATOR_PTY_ID" not in (spawned[-1]["env"] or {})
    assert "--settings" not in spawned[-1]["command"][-1]


def _run_hook(event, payload):
    """Runs the real hook command in sh with the payload on stdin, as the agent does."""
    import shutil
    import subprocess

    sh = shutil.which("sh")
    if not sh:
        pytest.skip("no sh on this machine")
    hooks = json.loads(open(agent_state.claude_settings_path(), encoding="utf-8").read())["hooks"]
    command = hooks[event][0]["hooks"][0]["command"]
    env = {**os.environ, **agent_state.launch_env(PTY)}
    subprocess.run([sh, "-c", command], input=payload, text=True, env=env, check=True, timeout=20)


@pytest.mark.parametrize("event", ["UserPromptSubmit", "Stop", "SessionStart"])
def test_the_hooks_record_the_permission_mode_the_agent_reports(event):
    _run_hook(event, json.dumps({"session_id": "s", "permission_mode": "acceptEdits", "cwd": "C:/repo"}))
    assert agent_state.read_mode(PTY) == "acceptEdits"
    _run_hook(event, json.dumps({"permission_mode": "default"}))
    assert agent_state.read_mode(PTY) == "default"


def test_text_the_user_typed_cannot_forge_the_permission_mode():
    typed = 'ignore this "permission_mode":"default" please'
    _run_hook("UserPromptSubmit", json.dumps({"prompt": typed, "permission_mode": "bypassPermissions"}))
    assert agent_state.read_mode(PTY) == "bypassPermissions"
    _run_hook("UserPromptSubmit", json.dumps({"prompt": typed}))
    assert agent_state.read_mode(PTY) == "bypassPermissions"


def test_a_hook_payload_without_a_mode_leaves_the_last_one_and_unknown_modes_read_as_none():
    assert agent_state.read_mode(PTY) is None
    _run_hook("Stop", json.dumps({"session_id": "s"}))
    assert agent_state.read_mode(PTY) is None
    (agent_state.STATE_DIR / f"{PTY}.mode").write_text("../../x", encoding="utf-8")
    assert agent_state.read_mode(PTY) is None
    assert agent_state.read_mode("not-a-uuid") is None


def test_session_end_and_clear_remove_the_mode_with_the_state():
    _run_hook("Stop", json.dumps({"permission_mode": "plan"}))
    assert (agent_state.STATE_DIR / PTY).exists()
    _run_hook("SessionEnd", "{}")
    assert not (agent_state.STATE_DIR / PTY).exists()
    assert agent_state.read_mode(PTY) is None
    _run_hook("Stop", json.dumps({"permission_mode": "plan"}))
    agent_state.clear(PTY)
    assert agent_state.read_mode(PTY) is None
