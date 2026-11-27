"""Which agents the relay can wake and message, and the Crush entry in particular."""

import asyncio
import json
import time
import uuid

import pytest

import agent_capabilities
import agent_mcp
import agent_state
import agent_suspend
import agent_wake
import generic_agent
from routes import terminal

SESSION = "7a1c2d3e-aaaa-4bbb-8ccc-0123456789ab"


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = {"live": {}, "hooks": True}
    monkeypatch.setattr(agent_state, "STATE_DIR", tmp_path / "agent-state")
    agent_state.STATE_DIR.mkdir()
    monkeypatch.setattr(agent_suspend, "STATE_FILE", tmp_path / "suspended-agents.json")
    monkeypatch.setattr(agent_mcp, "_tokens", {})
    monkeypatch.setattr(generic_agent, "_linked_sessions", {})
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda agent: f"C:/bin/{agent}.exe")
    monkeypatch.setattr(agent_state, "crush_supports_hooks", lambda exe: w["hooks"])
    monkeypatch.setattr(terminal, "_list_host_sessions", lambda: [{"id": i, "meta": m} for i, m in w["live"].items()])
    monkeypatch.setattr(terminal, "_pty_sessions", {})
    monkeypatch.setattr(agent_wake, "title_of", lambda project, agent, session: "Crushy" if agent == "crush" else "Design head")
    return w


def pty_id():
    return str(uuid.uuid4())


def suspend(agent, session=SESSION):
    pid = pty_id()
    now = time.time()
    agent_suspend._remember(
        pid, {"agent": agent, "project_id": "demo", "session_id": session, "title": "Crushy", "at": now}, now
    )
    return pid


def record_session(pty, session=SESSION):
    (agent_state.STATE_DIR / f"{pty}.session").write_text(session, encoding="utf-8")


def go_live(world, agent="crush", session=SESSION, token=True):
    pid = pty_id()
    world["live"][pid] = {"agent": agent, "project_id": "demo", **({"session_id": session} if session else {})}
    if token:
        agent_mcp.issue(pid, "demo", agent)
    return pid


# --- the table -----------------------------------------------------------------


def test_claude_and_crush_are_relayable_and_nothing_else_is(world):
    assert agent_capabilities.relayable("claude") and agent_capabilities.relayable("crush")
    assert not any(agent_capabilities.relayable(a) for a in ("codex", "opencode-bare", "terminal", "", None))


def test_crush_is_only_relayable_when_its_hooks_are_confirmed(world):
    world["hooks"] = False
    assert not agent_capabilities.relayable("crush")
    assert agent_capabilities.relayable("claude")


def test_a_running_crush_needs_its_token_but_a_running_claude_does_not(world):
    assert not agent_capabilities.live_target_ok("crush", pty_id())
    assert agent_capabilities.live_target_ok("claude", pty_id())
    pid = go_live(world)
    assert agent_capabilities.live_target_ok("crush", pid)


def test_only_crush_learns_its_session_from_a_hook():
    assert agent_capabilities.session_from_hook("crush")
    assert not agent_capabilities.session_from_hook("claude")


# --- the session id a hook leaves behind ---------------------------------------


def test_read_session_returns_what_a_hook_wrote_and_nothing_else(world):
    pid = pty_id()
    assert agent_state.read_session(pid) is None
    record_session(pid)
    assert agent_state.read_session(pid) == SESSION
    record_session(pid, "rm -rf /; echo")
    assert agent_state.read_session(pid) is None
    record_session(pid, "")
    assert agent_state.read_session(pid) is None
    assert agent_state.read_session("../../etc/passwd") is None


def test_clear_drops_the_recorded_session_too(world):
    pid = pty_id()
    record_session(pid)
    agent_state.clear(pid)
    assert agent_state.read_session(pid) is None


def test_a_fresh_crush_terminal_gets_its_session_id_from_the_hook_file(world):
    pid = go_live(world, session=None)
    assert "session_id" not in terminal.live_pty_labels()[pid]
    record_session(pid)
    assert terminal.live_pty_labels()[pid]["session_id"] == SESSION


def test_a_session_id_already_on_the_terminal_wins_over_the_hook_file(world):
    pid = go_live(world, session="pinned-1")
    record_session(pid)
    assert terminal.live_pty_labels()[pid]["session_id"] == "pinned-1"


def test_a_hook_cannot_claim_the_session_of_a_running_terminal(world):
    owner = go_live(world, session="peer-session")
    generic_agent.relink_session("crush", owner, "peer-session")
    thief = go_live(world, session=None)
    record_session(thief, "peer-session")
    labels = terminal.live_pty_labels()
    assert labels[owner]["session_id"] == "peer-session"
    assert "session_id" not in labels[thief]
    sender = asyncio.run(agent_mcp._sender({"pty_id": thief, "project_id": "demo", "agent": "crush"}))
    assert sender["session_id"] == ""


def test_a_hook_cannot_claim_the_session_of_a_suspended_terminal(world):
    suspend("crush", session="sleeper-1")
    thief = go_live(world, session=None)
    record_session(thief, "sleeper-1")
    assert "session_id" not in terminal.live_pty_labels()[thief]


def test_a_hook_cannot_claim_the_session_a_terminal_was_launched_into(world):
    owner = pty_id()
    generic_agent.relink_session("crush", owner, "resumed-1")
    thief = go_live(world, session=None)
    record_session(thief, "resumed-1")
    assert "session_id" not in terminal.live_pty_labels()[thief]
    assert agent_mcp.recorded_session(thief, "crush") is None


def test_two_terminals_that_record_the_same_session_are_both_refused(world):
    first, second = go_live(world, session=None), go_live(world, session=None)
    record_session(first)
    record_session(second)
    labels = terminal.live_pty_labels()
    assert "session_id" not in labels[first] and "session_id" not in labels[second]


def test_a_closed_terminals_leftover_file_does_not_block_a_resume(world):
    closed = pty_id()
    record_session(closed)
    resumed = go_live(world, session=None)
    record_session(resumed)
    assert terminal.live_pty_labels()[resumed]["session_id"] == SESSION
    sender = asyncio.run(agent_mcp._sender({"pty_id": resumed, "project_id": "demo", "agent": "crush"}))
    assert sender["session_id"] == SESSION


def test_a_terminal_can_move_to_a_new_session_that_nobody_else_holds(world):
    pid = go_live(world, session=None)
    record_session(pid, "first-1")
    assert terminal.live_pty_labels()[pid]["session_id"] == "first-1"
    record_session(pid, "second-2")
    assert terminal.live_pty_labels()[pid]["session_id"] == "second-2"


def test_the_hook_file_is_not_used_for_claude(world):
    pid = go_live(world, agent="claude", session=None)
    record_session(pid)
    assert "session_id" not in terminal.live_pty_labels()[pid]


# --- finding Crush targets -----------------------------------------------------


def test_a_suspended_crush_is_found_by_name_and_listed_for_peers(world):
    pid = suspend("crush")
    found = agent_wake.find_targets("crushy", "demo")
    assert [(m["pty_id"], m["agent"]) for m in found] == [(pid, "crush")]
    assert [e["pty_id"] for e in agent_wake.list_entries()] == [pid]
    assert agent_wake.find_by_pty(pid)["agent"] == "crush"
    agent_suspend._save(agent_suspend.all_records())
    listed = json.loads(agent_suspend.targets_file().read_text(encoding="utf-8"))
    assert [(t["session_id"], t["agent"]) for t in listed] == [(SESSION, "crush")]


def test_a_suspended_crush_is_not_a_target_when_its_hooks_cannot_be_confirmed(world):
    pid = suspend("crush")
    world["hooks"] = False
    assert agent_wake.find_targets("crushy", "demo") == []
    assert agent_wake.list_entries() == []
    assert agent_wake.find_by_pty(pid) is None
    agent_suspend._save(agent_suspend.all_records())
    assert json.loads(agent_suspend.targets_file().read_text(encoding="utf-8")) == []


def test_a_running_crush_with_a_recorded_session_and_a_token_is_a_target(world):
    pid = go_live(world, session=None)
    record_session(pid)
    found = agent_wake.find_targets(SESSION, "demo")
    assert [(m["pty_id"], m["state"], m["agent"], m["title"]) for m in found] == [(pid, "live", "crush", "Crushy")]
    assert [e["pty_id"] for e in agent_wake.list_entries()] == [pid]
    assert agent_wake.find_by_pty(pid)["session_id"] == SESSION


def test_a_running_crush_is_not_a_target_without_a_session_id(world):
    pid = go_live(world, session=None)
    assert agent_wake.find_targets(SESSION, "demo") == []
    assert agent_wake.list_entries() == [] and agent_wake.find_by_pty(pid) is None


def test_a_running_crush_is_not_a_target_without_its_token(world):
    pid = go_live(world, token=False)
    assert agent_wake.find_targets(SESSION, "demo") == []
    assert agent_wake.list_entries() == [] and agent_wake.find_by_pty(pid) is None


def test_a_running_crush_is_not_a_target_when_its_hooks_cannot_be_confirmed(world):
    pid = go_live(world)
    world["hooks"] = False
    assert agent_wake.find_targets(SESSION, "demo") == []
    assert agent_wake.list_entries() == [] and agent_wake.find_by_pty(pid) is None


def test_a_running_claude_is_still_a_target_with_no_token(world):
    pid = go_live(world, agent="claude", token=False)
    assert [m["pty_id"] for m in agent_wake.find_targets("design head", "demo")] == [pid]


def test_other_agents_are_never_targets(world):
    suspend("codex")
    go_live(world, agent="codex")
    assert agent_wake.find_targets(SESSION, "demo") == [] and agent_wake.list_entries() == []


# --- the message tool for Crush ------------------------------------------------

CRUSH = ["C:/bin/crush.exe"]


def test_the_message_tool_is_served_to_crush_but_not_to_others_or_wsl(world):
    assert agent_mcp.serves("crush", CRUSH)
    assert agent_mcp.serves("claude", ["claude"])
    assert not agent_mcp.serves("codex", ["codex"])
    assert not agent_mcp.serves("crush", None)
    assert not agent_mcp.serves("crush", ["wsl.exe", "-d", "Ubuntu", "--", "crush"])


def test_the_message_tool_is_not_served_to_crush_when_its_hooks_cannot_be_confirmed(world):
    world["hooks"] = False
    assert not agent_mcp.serves("crush", CRUSH)
    assert agent_mcp.launch_env("crush", CRUSH, pty_id(), "demo") == {}


def test_a_crush_launch_gets_a_token_that_names_its_terminal_and_agent(world):
    pid = pty_id()
    env = agent_mcp.launch_env("crush", CRUSH, pid, "demo")
    assert agent_mcp.caller_for(env[agent_mcp.TOKEN_ENV]) == {"pty_id": pid, "project_id": "demo", "agent": "crush"}
    assert agent_mcp.holds_token(pid) and not agent_mcp.holds_token(pty_id())


def test_crush_is_given_its_door_through_the_crushrc_not_a_command_flag(world):
    assert agent_mcp.with_gator_mcp("crush", CRUSH) == CRUSH
    assert agent_mcp.with_gator_mcp("claude", ["claude"])[-2] == "--mcp-config"


def test_the_crushrc_line_reads_the_token_from_the_environment(world, monkeypatch):
    monkeypatch.setattr(agent_mcp, "backend_port", lambda: "8123")
    assert agent_mcp.crush_mcp_line() == (
        'mcp add gator --type http --url http://127.0.0.1:8123/agent-mcp/ --header Authorization "Bearer $GATOR_AGENT_TOKEN"'
    )


def test_a_crush_sender_cannot_take_the_session_of_a_live_claude_terminal(world):
    go_live(world, agent="claude", session="claude-sess", token=False)
    thief = go_live(world, session=None)
    record_session(thief, "claude-sess")
    sender = asyncio.run(agent_mcp._sender({"pty_id": thief, "project_id": "demo", "agent": "crush"}))
    assert sender["session_id"] == ""


def test_a_crush_sender_is_named_from_its_recorded_session(world):
    pid = go_live(world, session=None)
    record_session(pid)
    sender = asyncio.run(agent_mcp._sender({"pty_id": pid, "project_id": "demo", "agent": "crush"}))
    assert sender == {"name": "Crushy", "session_id": SESSION, "project_id": "demo", "pty_id": pid}


def test_a_token_without_an_agent_is_a_claude_sender(world, monkeypatch):
    pid = pty_id()
    monkeypatch.setattr(generic_agent, "linked_session_id", lambda p: "claude-sess")
    sender = asyncio.run(agent_mcp._sender({"pty_id": pid, "project_id": "demo"}))
    assert sender["name"] == "Design head" and sender["session_id"] == "claude-sess"
