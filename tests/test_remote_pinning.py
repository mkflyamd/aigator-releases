"""Remote sessions are pinned: the idle-suspend sweep never takes them."""

import uuid

import agent_suspend
import generic_agent
from routes import generic_agent_routes

NOW = 1_000_000.0
IDLE = agent_suspend.IDLE_SUSPEND_SECONDS


async def test_open_pinned_terminal_labels_the_pty_as_remote_pinned(monkeypatch):
    import routes.terminal as terminal

    spawned = []
    monkeypatch.setattr(terminal, "create_pty_session", lambda sid, **kw: spawned.append({"sid": sid, **kw}))
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: (None, {}))
    monkeypatch.setattr(generic_agent, "effective_binding", lambda agent: None)
    monkeypatch.setattr(generic_agent, "build_command", lambda agent, repo, extra=(): ["C:\\bin\\claude.exe"])
    monkeypatch.setattr(generic_agent, "_pinned_sessions", {})
    monkeypatch.setattr(generic_agent, "_linked_sessions", {})
    monkeypatch.setattr(generic_agent, "_active_sessions", {})

    req = generic_agent_routes.GenericAgentTerminalRequest(
        agent="claude", project_id="demo", repo_path="C:\\work\\app", force_new=True
    )
    result = await generic_agent_routes.open_pinned_terminal(req)

    assert result["created"] is True
    assert spawned[-1]["meta"]["remote_pinned"] == "1"
    assert spawned[-1]["meta"]["project_id"] == "demo"


def test_pinned_idle_terminal_is_never_chosen_for_suspend():
    pinned, normal = str(uuid.uuid4()), str(uuid.uuid4())
    live = {
        pinned: {"project_id": "demo", "agent": "claude", "session_id": "s1", "remote_pinned": "1"},
        normal: {"project_id": "demo", "agent": "claude", "session_id": "s2"},
    }
    states = {p: {"state": "idle", "at": NOW - IDLE - 1} for p in live}
    since = {p: NOW - IDLE - 60 for p in live}
    assert agent_suspend.choose(live, states, set(), since, NOW) == [normal]


class _Registered:
    def __init__(self, meta):
        self.meta = meta


def _close_fakes(monkeypatch, meta, host_labels=None):
    import routes.terminal as terminal

    closed, unpinned = [], []
    monkeypatch.setattr(terminal, "_pty_sessions", {"pty-9": _Registered(meta)} if meta is not None else {})
    monkeypatch.setattr(terminal, "host_session_labels", lambda sid: host_labels or {})
    monkeypatch.setattr(terminal, "close_pty_session", lambda sid: closed.append(sid) or True)
    monkeypatch.setattr(generic_agent, "unpin_session", lambda sid: unpinned.append(sid))
    monkeypatch.setattr(agent_suspend, "forget", lambda sid: None)
    monkeypatch.setattr(generic_agent, "_active_sessions", {})
    return closed, unpinned


async def test_closing_a_code_tab_does_not_end_a_remote_pinned_session(monkeypatch):
    closed, unpinned = _close_fakes(monkeypatch, {"remote_pinned": "1"})
    req = generic_agent_routes.GenericAgentTerminalCloseRequest(agent="claude", project_id="demo", pty_session_id="pty-9")
    result = await generic_agent_routes.close_generic_agent_terminal(req)
    assert result["ok"] is True
    assert closed == [] and unpinned == []


async def test_closing_a_code_tab_still_ends_an_ordinary_session(monkeypatch):
    closed, unpinned = _close_fakes(monkeypatch, {"project_id": "demo"})
    req = generic_agent_routes.GenericAgentTerminalCloseRequest(agent="claude", project_id="demo", pty_session_id="pty-9")
    await generic_agent_routes.close_generic_agent_terminal(req)
    assert closed == ["pty-9"] and unpinned == ["pty-9"]


async def test_closing_a_code_tab_does_not_end_a_pinned_session_adopted_after_a_restart(monkeypatch):
    # After a backend restart the PTY is adopted with no meta; the pin lives in the host's labels.
    closed, unpinned = _close_fakes(monkeypatch, None, host_labels={"project_id": "demo", "remote_pinned": "1"})
    req = generic_agent_routes.GenericAgentTerminalCloseRequest(agent="claude", project_id="demo", pty_session_id="pty-9")
    result = await generic_agent_routes.close_generic_agent_terminal(req)
    assert result["ok"] is True
    assert closed == [] and unpinned == []


async def test_closing_an_adopted_ordinary_session_still_ends_it(monkeypatch):
    closed, unpinned = _close_fakes(monkeypatch, None, host_labels={"project_id": "demo"})
    req = generic_agent_routes.GenericAgentTerminalCloseRequest(agent="claude", project_id="demo", pty_session_id="pty-9")
    await generic_agent_routes.close_generic_agent_terminal(req)
    assert closed == ["pty-9"] and unpinned == ["pty-9"]
