"""Suspending idle agent terminals: which ones, how, and how the tab comes back."""

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_suspend
import generic_agent
from routes import generic_agent_routes
from routes import terminal
from security import verify_csrf

NOW = 1_000_000.0
IDLE = agent_suspend.IDLE_SUSPEND_SECONDS
MAX_LIVE = agent_suspend.MAX_LIVE_AGENT_TERMINALS


def pty_id():
    return str(uuid.uuid4())


def labels(agent="claude", session="sess-1"):
    meta = {"project_id": "demo", "agent": agent}
    if session:
        meta["session_id"] = session
    return meta


def idle_for(seconds):
    return {"state": "idle", "at": NOW - seconds}


def pick(live, states, watched=(), unwatched_for=None):
    since = {p: NOW - (unwatched_for if unwatched_for is not None else IDLE + 60) for p in live}
    return agent_suspend.choose(live, states, set(watched), since, NOW)


def test_defaults_are_thirty_minutes_and_four_terminals():
    assert IDLE == 1800
    assert MAX_LIVE == 4


def test_idle_and_unwatched_past_the_limit_is_suspended():
    a = pty_id()
    assert pick({a: labels()}, {a: idle_for(IDLE + 1)}) == [a]


def test_idle_for_less_than_the_limit_is_kept():
    a = pty_id()
    assert pick({a: labels()}, {a: idle_for(IDLE - 60)}) == []


def test_idle_agent_that_was_watched_recently_is_kept():
    a = pty_id()
    assert pick({a: labels()}, {a: idle_for(IDLE * 3)}, unwatched_for=IDLE - 60) == []


@pytest.mark.parametrize("word", ["working", "asking"])
def test_working_or_asking_agents_are_never_suspended(word):
    a = pty_id()
    assert pick({a: labels()}, {a: {"state": word, "at": NOW - IDLE * 5}}) == []


def test_unknown_state_is_never_suspended():
    a = pty_id()
    assert pick({a: labels()}, {}) == []


def test_a_viewed_terminal_is_never_suspended():
    a = pty_id()
    assert pick({a: labels()}, {a: idle_for(IDLE * 5)}, watched=[a]) == []


def test_the_plain_terminal_and_agents_without_a_resume_id_are_never_suspended():
    shell, fresh = pty_id(), pty_id()
    live = {shell: labels("terminal"), fresh: labels("claude", session=None)}
    states = {shell: idle_for(IDLE * 5), fresh: idle_for(IDLE * 5)}
    assert pick(live, states) == []


def test_over_the_cap_the_least_recently_active_idle_terminals_go_first():
    ids = [pty_id() for _ in range(MAX_LIVE + 2)]
    live = {p: labels() for p in ids}
    # Idle for 1..N minutes, so every one is under the idle limit: only the cap acts.
    states = {p: idle_for(60 * (i + 1)) for i, p in enumerate(ids)}
    assert pick(live, states, unwatched_for=0) == [ids[-1], ids[-2]]


def test_at_the_cap_nothing_is_suspended_for_the_cap():
    ids = [pty_id() for _ in range(MAX_LIVE)]
    live = {p: labels() for p in ids}
    states = {p: idle_for(60) for p in ids}
    assert pick(live, states, unwatched_for=0) == []


def test_the_cap_skips_terminals_that_must_not_be_suspended():
    busy, viewed, *rest = [pty_id() for _ in range(MAX_LIVE + 1)]
    live = {p: labels() for p in [busy, viewed, *rest]}
    states = {busy: {"state": "working", "at": NOW - 9999}, viewed: idle_for(9999)}
    states.update({p: idle_for(60 * (i + 1)) for i, p in enumerate(rest)})
    assert pick(live, states, watched=[viewed], unwatched_for=0) == [rest[-1]]


def test_the_cap_counts_the_plain_terminal_out_and_unlabelled_ptys_out():
    ids = [pty_id() for _ in range(MAX_LIVE)]
    live = {p: labels() for p in ids}
    live[pty_id()] = labels("terminal")
    live[pty_id()] = {}
    states = {p: idle_for(60) for p in ids}
    assert pick(live, states, unwatched_for=0) == []


def test_a_timed_out_terminal_counts_toward_the_cap_only_once():
    ids = [pty_id() for _ in range(MAX_LIVE + 1)]
    live = {p: labels() for p in ids}
    states = {p: idle_for(60) for p in ids}
    states[ids[0]] = idle_for(IDLE + 600)
    assert pick(live, states) == [ids[0]]


# ── sweep: gathers state, suspends, records, forgets ─────────────────────────


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = {"live": {}, "states": {}, "watched": set(), "closed": [], "close_fails": False}
    monkeypatch.setattr(agent_suspend, "STATE_FILE", tmp_path / "suspended-agents.json")
    monkeypatch.setattr(agent_suspend, "_unwatched_since", {})
    monkeypatch.setattr(terminal, "live_pty_labels", lambda: dict(w["live"]))
    monkeypatch.setattr(terminal, "has_viewer", lambda pid, grace_seconds=90.0: pid in w["watched"])
    monkeypatch.setattr(agent_suspend.agent_state, "read_states", lambda ids: {i: w["states"][i] for i in ids if i in w["states"]})

    def close(pid):
        if w["close_fails"]:
            raise OSError("host unreachable")
        w["closed"].append(pid)

    monkeypatch.setattr(terminal, "close_pty_session", close)
    monkeypatch.setattr(generic_agent, "_active_sessions", {})
    monkeypatch.setattr(generic_agent, "_pinned_sessions", {})
    monkeypatch.setattr(generic_agent, "_linked_sessions", {})
    return w


def test_sweep_waits_for_the_terminal_to_stay_unwatched_for_the_whole_limit(world):
    a = pty_id()
    world["live"][a] = labels()
    world["states"][a] = idle_for(IDLE * 4)
    assert agent_suspend.sweep(NOW) == []
    assert agent_suspend.sweep(NOW + IDLE - 1) == []
    assert agent_suspend.sweep(NOW + IDLE) == [a]
    assert world["closed"] == [a]


def test_sweep_restarts_the_clock_when_the_terminal_is_viewed_again(world):
    a = pty_id()
    world["live"][a] = labels()
    world["states"][a] = idle_for(IDLE * 4)
    agent_suspend.sweep(NOW)
    world["watched"].add(a)
    agent_suspend.sweep(NOW + IDLE - 10)
    world["watched"].clear()
    assert agent_suspend.sweep(NOW + IDLE + 10) == []
    assert agent_suspend.sweep(NOW + IDLE * 2 + 10) == [a]


def test_suspending_records_how_to_resume_and_drops_the_terminal_bookkeeping(world):
    a = pty_id()
    world["live"][a] = labels(session="claude-sess-9")
    world["states"][a] = idle_for(IDLE * 4)
    generic_agent.set_active_session("demo", "claude", a)
    generic_agent.relink_session("claude", a, "claude-sess-9")
    agent_suspend.sweep(NOW)
    agent_suspend.sweep(NOW + IDLE)
    record = agent_suspend.suspended_record(a)
    assert {k: record[k] for k in ("agent", "project_id", "session_id")} == {
        "agent": "claude",
        "project_id": "demo",
        "session_id": "claude-sess-9",
    }
    assert record["at"] == NOW + IDLE
    assert generic_agent.get_active_session("demo", "claude") is None
    assert generic_agent.linked_session_id(a) is None


def test_the_record_survives_a_backend_restart(world):
    a = pty_id()
    world["live"][a] = labels(session="claude-sess-9")
    world["states"][a] = idle_for(IDLE * 4)
    agent_suspend.sweep(NOW)
    agent_suspend.sweep(NOW + IDLE)
    on_disk = json.loads(agent_suspend.STATE_FILE.read_text(encoding="utf-8"))
    assert on_disk[a]["session_id"] == "claude-sess-9"


def test_a_failed_close_leaves_no_record_and_does_not_raise(world):
    a = pty_id()
    world["live"][a] = labels()
    world["states"][a] = idle_for(IDLE * 4)
    world["close_fails"] = True
    agent_suspend.sweep(NOW)
    assert agent_suspend.sweep(NOW + IDLE) == []
    assert agent_suspend.suspended_record(a) is None


def test_records_older_than_the_retention_are_dropped(world):
    a, b = pty_id(), pty_id()
    for p in (a, b):
        world["live"][p] = labels()
        world["states"][p] = idle_for(IDLE * 4)
    agent_suspend.sweep(NOW)
    agent_suspend.sweep(NOW + IDLE)
    later = NOW + IDLE + agent_suspend.RECORD_RETENTION_SECONDS + 1
    c = pty_id()
    world["live"] = {c: labels()}
    world["states"][c] = idle_for(IDLE * 4)
    agent_suspend.sweep(later)
    agent_suspend.sweep(later + IDLE)
    assert agent_suspend.suspended_record(a) is None
    assert agent_suspend.suspended_record(c) is not None


def test_forget_removes_the_record(world):
    a = pty_id()
    world["live"][a] = labels()
    world["states"][a] = idle_for(IDLE * 4)
    agent_suspend.sweep(NOW)
    agent_suspend.sweep(NOW + IDLE)
    agent_suspend.forget(a)
    assert agent_suspend.suspended_record(a) is None


def test_a_terminal_that_is_gone_stops_being_tracked(world):
    a = pty_id()
    world["live"][a] = labels()
    world["states"][a] = idle_for(IDLE * 4)
    agent_suspend.sweep(NOW)
    world["live"].clear()
    agent_suspend.sweep(NOW + 1)
    assert agent_suspend._unwatched_since == {}


# ── the routes: the tab learns it was suspended, and cleanup forgets it ──────


def test_ws_tells_the_tab_the_terminal_was_suspended_and_how_to_resume(world, monkeypatch):
    a = pty_id()
    world["live"][a] = labels(session="claude-sess-9")
    world["states"][a] = idle_for(IDLE * 4)
    agent_suspend.sweep(NOW)
    agent_suspend.sweep(NOW + IDLE)
    app = FastAPI()
    app.include_router(terminal.router)
    with TestClient(app).websocket_connect(f"/api/terminal/agent?session_id={a}") as ws:
        msg = json.loads(ws.receive_text())
    assert msg == {"type": "suspended", "data": "Suspended - click to resume", "session_id": "claude-sess-9"}


def test_ws_for_an_unknown_terminal_is_still_notready(world):
    app = FastAPI()
    app.include_router(terminal.router)
    with TestClient(app).websocket_connect(f"/api/terminal/agent?session_id={pty_id()}") as ws:
        assert json.loads(ws.receive_text())["type"] == "notready"


def test_closing_the_tab_forgets_the_suspended_record(world, monkeypatch):
    a = pty_id()
    world["live"][a] = labels()
    world["states"][a] = idle_for(IDLE * 4)
    agent_suspend.sweep(NOW)
    agent_suspend.sweep(NOW + IDLE)
    app = FastAPI()
    app.include_router(generic_agent_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    r = TestClient(app).request(
        "DELETE",
        "/api/generic-agent/terminal",
        json={"agent": "claude", "project_id": "demo", "pty_session_id": a},
    )
    assert r.status_code == 200
    assert agent_suspend.suspended_record(a) is None


# ── terminal helpers ─────────────────────────────────────────────────────────


def test_close_of_a_session_this_backend_never_adopted_closes_it_on_the_host(monkeypatch):
    sent = []
    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(terminal.pty_client, "find_host", lambda key: {"port": 1, "token": "t"})
    monkeypatch.setattr(terminal.pty_client, "host_request", lambda info, msg, *a: sent.append(msg) or {"ok": True})
    terminal.close_pty_session("not-adopted")
    assert sent == [{"op": "close", "id": "not-adopted"}]


def test_live_pty_labels_merges_host_and_in_process_sessions(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        terminal,
        "_list_host_sessions",
        lambda: [{"id": "h1", "done": False, "meta": {"agent": "claude"}}, {"id": "h2", "done": True, "meta": {}}],
    )
    monkeypatch.setattr(
        terminal,
        "_pty_sessions",
        {"l1": SimpleNamespace(done=False, meta={"agent": "codex"}), "l2": SimpleNamespace(done=True, meta=None)},
    )
    assert terminal.live_pty_labels() == {"h1": {"agent": "claude"}, "l1": {"agent": "codex"}}


def test_has_viewer_never_adopts_a_host_session(monkeypatch):
    monkeypatch.setattr(terminal, "_adopt_pty_session", lambda sid: pytest.fail("adopted"))
    assert terminal.has_viewer("unknown") is False
