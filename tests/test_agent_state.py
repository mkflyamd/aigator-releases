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
    "SessionStart": "idle",
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
    assert all("CRUSH_SESSION_ID" in ln for ln in lines if ln.startswith("hook add ") and "SessionEnd" not in ln)


def run_crush_hook(event, env):
    """Run one generated hook command the way Crush's shell would, if a POSIX shell is here."""
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("no POSIX shell on this machine")
    line = next(ln for ln in agent_state.crush_hook_lines() if ln.startswith(f"hook add {event} "))
    command = line.split(" --command '", 1)[1].rsplit("'", 1)[0]
    base = {**os.environ, "GATOR_AGENT_STATE_DIR": agent_state.STATE_DIR.as_posix(), "GATOR_PTY_ID": PTY}
    subprocess.run([sh, "-c", command], env={**base, **env}, check=True)  # noqa: S603


def test_a_crush_hook_leaves_its_session_id_beside_the_state():
    run_crush_hook("TurnStart", {"CRUSH_SESSION_ID": "sess-1"})
    assert agent_state.read_states([PTY])[PTY]["state"] == "working"
    assert (agent_state.STATE_DIR / f"{PTY}.session").read_text(encoding="utf-8") == "sess-1"
    assert agent_state.read_session(PTY) == "sess-1"


def test_a_crush_hook_without_a_session_id_keeps_the_one_already_recorded():
    run_crush_hook("TurnStart", {"CRUSH_SESSION_ID": "sess-1"})
    run_crush_hook("TurnEnd", {"CRUSH_SESSION_ID": ""})
    assert agent_state.read_states([PTY])[PTY]["state"] == "idle"
    assert agent_state.read_session(PTY) == "sess-1"


def test_a_crush_hook_outside_gator_writes_nothing():
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("no POSIX shell on this machine")
    line = next(ln for ln in agent_state.crush_hook_lines() if ln.startswith("hook add TurnEnd "))
    command = line.split(" --command '", 1)[1].rsplit("'", 1)[0]
    env = {k: v for k, v in os.environ.items() if k != "GATOR_PTY_ID"}
    subprocess.run([sh, "-c", command], env={**env, "GATOR_AGENT_STATE_DIR": agent_state.STATE_DIR.as_posix()})  # noqa: S603
    assert list(agent_state.STATE_DIR.iterdir()) == []


def test_loading_the_crushrc_marks_a_crush_terminal_ready():
    ready = agent_state.crush_hook_lines()[0]
    assert ready.startswith("if ") and "printf idle" in ready and "GATOR_PTY_ID" in ready
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("no POSIX shell on this machine")
    base = {**os.environ, "GATOR_AGENT_STATE_DIR": agent_state.STATE_DIR.as_posix(), "GATOR_PTY_ID": PTY}
    subprocess.run([sh, "-c", ready], env=base, check=True)  # noqa: S603
    assert agent_state.read_states([PTY])[PTY]["state"] == "idle"
    assert subprocess.run([sh, "-c", ready], env={k: v for k, v in base.items() if k != "GATOR_PTY_ID"}).returncode == 0  # noqa: S603


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
    rc = generic_agent._build_crushrc(profile, ["claude-sonnet"])
    assert "hook add TurnEnd " in rc and "hook add SessionStart " in rc
    assert 'mcp add gator --type http --url http://127.0.0.1:' in rc
    assert '--header Authorization "Bearer $GATOR_AGENT_TOKEN"' in rc
    monkeypatch.setattr(agent_state, "crush_supports_hooks", lambda exe: False)
    rc = generic_agent._build_crushrc(profile, ["claude-sonnet"])
    assert "hook add" not in rc and "mcp add gator" not in rc and "GATOR_PTY_ID" not in rc


@pytest.mark.parametrize(
    ("version_output", "expected"),
    [("opencode v2.3.0", True), ("2.0.0", True), ("opencode v10.1.0", True), ("opencode v1.14.2", False), ("", False)],
)
def test_opencode_plugins_need_opencode_2(monkeypatch, version_output, expected):
    agent_state._opencode_plugin_cache.clear()
    monkeypatch.setattr(agent_state, "_run_version", lambda exe: version_output)
    assert agent_state.opencode_supports_plugin("opencode.cmd") is expected
    assert agent_state.hooks_supported("opencode-bare", "opencode.cmd") is expected


def test_no_opencode_binary_means_no_plugin_support():
    assert not agent_state.opencode_supports_plugin(None)
    assert not agent_state.hooks_supported("opencode-bare", None)


def test_crush_keeps_its_own_version_check(monkeypatch):
    monkeypatch.setattr(agent_state, "crush_supports_hooks", lambda exe: exe == "crush.exe")
    monkeypatch.setattr(agent_state, "opencode_supports_plugin", lambda exe: False)
    assert agent_state.hooks_supported("crush", "crush.exe")
    assert not agent_state.hooks_supported("opencode-bare", "crush.exe")


def test_the_opencode_plugin_is_written_once_and_rewritten_when_it_changes(dirs, monkeypatch):
    monkeypatch.setattr(agent_state, "OPENCODE_DIR", dirs / "relay-plugin")
    folder = agent_state.opencode_plugin_dir()
    plugin = agent_state.OPENCODE_DIR / "index.js"
    assert folder == plugin.parent.as_posix() and plugin.read_text(encoding="utf-8") == agent_state._OPENCODE_PLUGIN
    plugin.write_text("tampered", encoding="utf-8")
    agent_state.opencode_plugin_dir()
    assert plugin.read_text(encoding="utf-8") == agent_state._OPENCODE_PLUGIN


_PLUGIN_DRIVER = """
import { existsSync, readFileSync } from "node:fs"
import { pathToFileURL } from "node:url"
const [, , pluginPath, eventsJson] = process.argv
const dir = process.env.GATOR_AGENT_STATE_DIR
const pty = process.env.GATOR_PTY_ID || "none"
const read = (p) => (existsSync(p) ? readFileSync(p, "utf8") : null)
const snaps = []
const snap = () => snaps.push([read(`${dir}/${pty}`), read(`${dir}/${pty}.session`)])
async function* stream() {
  snap()
  for (const event of JSON.parse(eventsJson)) {
    yield event
    snap()
  }
}
const plugin = (await import(pathToFileURL(pluginPath).href)).default
const dispose = plugin.setup({ event: { subscribe: () => stream() } })
await new Promise((resolve) => setTimeout(resolve, 300))
if (dispose) dispose()
snap()
console.log(JSON.stringify(snaps))
"""


def _run_opencode_plugin(tmp_path, events, with_pty=True):
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on this machine")
    plugin = tmp_path / "plugin.mjs"
    plugin.write_text(agent_state._OPENCODE_PLUGIN, encoding="utf-8")
    driver = tmp_path / "driver.mjs"
    driver.write_text(_PLUGIN_DRIVER, encoding="utf-8")
    env = {**os.environ, "GATOR_AGENT_STATE_DIR": agent_state.STATE_DIR.as_posix()}
    env.pop("GATOR_PTY_ID", None)
    if with_pty:
        env["GATOR_PTY_ID"] = PTY
    out = subprocess.run([node, str(driver), str(plugin), json.dumps(events)], env=env, capture_output=True, text=True, check=True)  # noqa: S603
    return json.loads(out.stdout)


def _ev(kind, session="ses_main"):
    return {"type": kind, "data": {"sessionID": session}}


def test_the_opencode_plugin_reports_ready_working_idle_and_the_main_session(tmp_path):
    snaps = _run_opencode_plugin(
        tmp_path,
        [_ev("session.execution.started"), _ev("session.execution.succeeded")],
    )
    assert snaps[0] == ["idle", None]
    assert snaps[1] == ["working", "ses_main"]
    assert snaps[2] == ["idle", "ses_main"]
    assert agent_state.read_session(PTY) == "ses_main"


def test_the_opencode_plugin_stays_working_until_the_child_session_ends_and_keeps_the_main_id(tmp_path):
    snaps = _run_opencode_plugin(
        tmp_path,
        [
            _ev("session.execution.started"),
            _ev("session.execution.started", "ses_child"),
            _ev("session.execution.succeeded", "ses_child"),
            _ev("session.execution.interrupted"),
        ],
    )
    assert [s[0] for s in snaps[1:5]] == ["working", "working", "working", "idle"]
    assert {s[1] for s in snaps[1:5]} == {"ses_main"}


@pytest.mark.parametrize("ending", ["session.execution.failed", "session.execution.interrupted"])
def test_the_opencode_plugin_goes_idle_when_a_run_fails_or_is_interrupted(tmp_path, ending):
    snaps = _run_opencode_plugin(tmp_path, [_ev("session.execution.started"), _ev(ending)])
    assert snaps[2][0] == "idle"


def test_the_opencode_plugin_reports_asking_during_a_permission_and_working_after(tmp_path):
    snaps = _run_opencode_plugin(
        tmp_path,
        [_ev("session.execution.started"), _ev("permission.asked"), _ev("permission.replied"), _ev("session.execution.succeeded")],
    )
    assert [s[0] for s in snaps[1:5]] == ["working", "asking", "working", "idle"]


def test_the_opencode_plugin_does_not_claim_working_for_a_permission_answered_while_idle(tmp_path):
    snaps = _run_opencode_plugin(tmp_path, [_ev("permission.replied")])
    assert snaps[1][0] == "idle"


def test_the_opencode_plugin_follows_a_new_session_started_after_the_last_one_ended(tmp_path):
    snaps = _run_opencode_plugin(
        tmp_path,
        [_ev("session.execution.started"), _ev("session.execution.succeeded"), _ev("session.execution.started", "ses_next")],
    )
    assert snaps[3] == ["working", "ses_next"]


def test_the_opencode_plugin_removes_its_state_but_keeps_the_session_when_it_is_disposed(tmp_path):
    snaps = _run_opencode_plugin(tmp_path, [_ev("session.execution.started")])
    assert snaps[-1] == [None, "ses_main"]


def test_the_opencode_plugin_writes_nothing_outside_gator(tmp_path):
    _run_opencode_plugin(tmp_path, [_ev("session.execution.started")], with_pty=False)
    assert list(agent_state.STATE_DIR.iterdir()) == []


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
