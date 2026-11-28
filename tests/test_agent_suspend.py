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
CAP_IDLE = agent_suspend.CAP_MIN_IDLE_SECONDS


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
    # Idle past the cap's minimum but under the idle limit: only the cap acts.
    states = {p: idle_for(CAP_IDLE + 60 * (i + 1)) for i, p in enumerate(ids)}
    assert pick(live, states, unwatched_for=0) == [ids[-1], ids[-2]]


def test_the_cap_leaves_alone_a_terminal_that_only_just_went_idle():
    ids = [pty_id() for _ in range(MAX_LIVE + 2)]
    live = {p: labels() for p in ids}
    states = {p: idle_for(CAP_IDLE + 60 * (6 - i)) for i, p in enumerate(ids)}
    states[ids[0]] = idle_for(CAP_IDLE - 1)
    states[ids[1]] = idle_for(5)
    assert pick(live, states, unwatched_for=0) == [ids[2], ids[3]]


def test_at_the_cap_nothing_is_suspended_for_the_cap():
    ids = [pty_id() for _ in range(MAX_LIVE)]
    live = {p: labels() for p in ids}
    states = {p: idle_for(60) for p in ids}
    assert pick(live, states, unwatched_for=0) == []


def test_the_cap_skips_terminals_that_must_not_be_suspended():
    busy, viewed, *rest = [pty_id() for _ in range(MAX_LIVE + 1)]
    live = {p: labels() for p in [busy, viewed, *rest]}
    states = {busy: {"state": "working", "at": NOW - 9999}, viewed: idle_for(9999)}
    states.update({p: idle_for(CAP_IDLE + 60 * (i + 1)) for i, p in enumerate(rest)})
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
    w = {"live": {}, "states": {}, "watched": set(), "closed": [], "close_fails": False, "transcript_ok": True}
    monkeypatch.setattr(agent_suspend, "STATE_FILE", tmp_path / "suspended-agents.json")
    monkeypatch.setattr(agent_suspend, "_unwatched_since", {})
    monkeypatch.setattr(terminal, "live_pty_labels", lambda: dict(w["live"]))
    monkeypatch.setattr(terminal, "has_viewer", lambda pid, grace_seconds=90.0, visible_only=True: pid in w["watched"])
    monkeypatch.setattr(
        agent_suspend, "_current_session", lambda meta, at: {"title": "Design head"} if w["transcript_ok"] else None
    )
    monkeypatch.setattr(agent_suspend.agent_state, "read_states", lambda ids: {i: w["states"][i] for i in ids if i in w["states"]})

    def close(pid):
        if w["close_fails"]:
            return False
        w["closed"].append(pid)
        return True

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


def test_the_record_keeps_the_session_title_so_a_peer_can_be_named(world):
    a = pty_id()
    world["live"][a] = labels(session="claude-sess-9")
    world["states"][a] = idle_for(IDLE * 4)
    agent_suspend.sweep(NOW)
    agent_suspend.sweep(NOW + IDLE)
    assert agent_suspend.suspended_record(a)["title"] == "Design head"


def test_a_remote_lane_terminal_keeps_its_remote_labels_in_the_record_and_a_plain_one_does_not(world):
    lane, plain = pty_id(), pty_id()
    world["live"][lane] = {**labels(session="claude-sess-9"), "remote_pinned": "1", "remote_channel": "teams", "remote_project": "Budget"}
    world["live"][plain] = labels(session="claude-sess-10")
    world["states"][lane] = world["states"][plain] = idle_for(IDLE * 4)
    agent_suspend.sweep(NOW)
    agent_suspend.sweep(NOW + IDLE)
    assert agent_suspend.suspended_record(lane)["labels"] == {"remote_channel": "teams", "remote_project": "Budget"}
    assert "labels" not in agent_suspend.suspended_record(plain)


def test_suspended_claude_agents_are_listed_for_other_agents_to_find(world):
    a, b = pty_id(), pty_id()
    world["live"][a] = labels(session="claude-sess-9")
    world["live"][b] = labels(session="claude-sess-10")
    world["states"][a] = world["states"][b] = idle_for(IDLE * 4)
    agent_suspend.sweep(NOW)
    agent_suspend.sweep(NOW + IDLE)
    listed = json.loads(agent_suspend.targets_file().read_text(encoding="utf-8"))
    assert {t["session_id"] for t in listed} == {"claude-sess-9", "claude-sess-10"}
    assert listed[0]["name"] == "Design head" and listed[0]["project_id"] == "demo" and listed[0]["agent"] == "claude"
    assert listed[0]["suspended_since"].endswith("+00:00")
    agent_suspend.forget(a)
    listed = json.loads(agent_suspend.targets_file().read_text(encoding="utf-8"))
    assert [t["session_id"] for t in listed] == ["claude-sess-10"]


def test_a_record_whose_wake_failed_is_kept_with_why_and_is_not_listed_as_a_target(world):
    a = pty_id()
    world["live"][a] = labels(session="claude-sess-9")
    world["states"][a] = idle_for(IDLE * 4)
    agent_suspend.sweep(NOW)
    agent_suspend.sweep(NOW + IDLE)
    agent_suspend.mark_failed(a, {"reason": "transcript missing", "message": "hi", "sender": "Turn issues", "at": NOW})
    assert agent_suspend.suspended_record(a)["failed"]["reason"] == "transcript missing"
    assert json.loads(agent_suspend.targets_file().read_text(encoding="utf-8")) == []
    agent_suspend.clear_failed(a)
    assert "failed" not in agent_suspend.suspended_record(a)
    assert len(json.loads(agent_suspend.targets_file().read_text(encoding="utf-8"))) == 1


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
        lambda strict=False: [{"id": "h1", "done": False, "meta": {"agent": "claude"}}, {"id": "h2", "done": True, "meta": {}}],
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


# ── a close that fails, and a terminal that changes its mind mid-suspend ─────


def test_a_failed_close_keeps_the_terminal_pinned_and_active(world):
    a = pty_id()
    world["live"][a] = labels()
    world["states"][a] = idle_for(IDLE * 4)
    generic_agent.set_active_session("demo", "claude", a)
    generic_agent.relink_session("claude", a, "sess-1")
    world["close_fails"] = True
    agent_suspend.sweep(NOW)
    assert agent_suspend.sweep(NOW + IDLE) == []
    assert agent_suspend.suspended_record(a) is None
    assert generic_agent.get_active_session("demo", "claude") == a
    assert generic_agent.linked_session_id(a) == "sess-1"


def _suspend_after(monkeypatch, change):
    """Run a sweep that would suspend `a`, with `change` happening during the lookup
    that precedes the kill."""
    def lookup(meta, at):
        change()
        return {"title": "Design head"}

    agent_suspend.sweep(NOW)
    monkeypatch.setattr(agent_suspend, "_current_session", lookup)
    return agent_suspend.sweep(NOW + IDLE)


@pytest.fixture
def one_idle(world):
    a = pty_id()
    world["live"][a] = labels()
    world["states"][a] = idle_for(IDLE * 4)
    return a


def test_an_agent_that_went_back_to_work_just_before_the_kill_is_left_running(world, monkeypatch, one_idle):
    a = one_idle
    done = _suspend_after(monkeypatch, lambda: world["states"].update({a: {"state": "working", "at": NOW + IDLE}}))
    assert done == []
    assert world["closed"] == []
    assert agent_suspend.suspended_record(a) is None


def test_an_agent_that_finished_another_turn_just_before_the_kill_is_left_running(world, monkeypatch, one_idle):
    a = one_idle
    done = _suspend_after(monkeypatch, lambda: world["states"].update({a: {"state": "idle", "at": NOW + IDLE - 5}}))
    assert done == []
    assert world["closed"] == []


def test_a_terminal_looked_at_just_before_the_kill_is_left_running(world, monkeypatch, one_idle):
    a = one_idle
    done = _suspend_after(monkeypatch, lambda: world["watched"].add(a))
    assert done == []
    assert world["closed"] == []


def test_a_stored_session_that_is_missing_or_stale_blocks_the_suspend(world):
    a = pty_id()
    world["live"][a] = labels()
    world["states"][a] = idle_for(IDLE * 4)
    world["transcript_ok"] = False
    agent_suspend.sweep(NOW)
    assert agent_suspend.sweep(NOW + IDLE) == []
    assert world["closed"] == []
    assert agent_suspend.suspended_record(a) is None


def _stored(monkeypatch, record, repo="C:/repo"):
    import agent_sessions
    from skills.code_agent import projects

    monkeypatch.setattr(projects, "get_project", lambda name: {"name": name, "repo_path": repo} if name == "demo" else None)
    monkeypatch.setattr(agent_sessions, "find_session", lambda repo_path, agent, sid: record if repo_path == repo else None)


def test_the_stored_session_must_exist_and_be_at_least_as_recent_as_the_idle_state(monkeypatch):
    meta = labels(session="sess-1")
    _stored(monkeypatch, {"id": "sess-1", "last_active_at": NOW})
    assert agent_suspend._current_session(meta, NOW)["id"] == "sess-1"
    # The Stop hook stamps idle just after the last transcript write.
    assert agent_suspend._current_session(meta, NOW + 1) is not None
    stale = NOW + agent_suspend.TRANSCRIPT_SLACK_SECONDS + 1
    assert agent_suspend._current_session(meta, stale) is None


def test_no_stored_session_or_no_project_means_it_is_not_current(monkeypatch):
    _stored(monkeypatch, None)
    assert agent_suspend._current_session(labels(session="sess-1"), NOW) is None
    _stored(monkeypatch, {"id": "sess-1", "last_active_at": NOW})
    assert agent_suspend._current_session({**labels(session="sess-1"), "project_id": "gone"}, NOW) is None


def test_the_cap_only_suspends_terminals_that_have_been_idle_a_while(world):
    ids = [pty_id() for _ in range(MAX_LIVE + 1)]
    for i, p in enumerate(ids):
        world["live"][p] = labels()
        world["states"][p] = idle_for(5 if i == 0 else CAP_IDLE + 60 * i)
    agent_suspend.sweep(NOW)
    done = agent_suspend.sweep(NOW + 1)
    assert done == [ids[-1]]


# ── the record file and the close route ──────────────────────────────────────


def test_the_record_file_is_written_through_a_per_process_temp_name(world, monkeypatch):
    replaced = []
    real = agent_suspend.os.replace
    monkeypatch.setattr(agent_suspend.os, "replace", lambda src, dst: replaced.append(src.name) or real(src, dst))
    agent_suspend._remember("p", {"session_id": "s", "at": NOW}, NOW)
    assert replaced[0] == f"suspended-agents.json.{agent_suspend.os.getpid()}.tmp"


def test_a_record_file_error_cannot_turn_a_closed_tab_into_a_500(world, monkeypatch):
    def broken(pty_id):
        raise OSError("disk full")

    monkeypatch.setattr(agent_suspend, "forget", broken)
    app = FastAPI()
    app.include_router(generic_agent_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    r = TestClient(app).request(
        "DELETE",
        "/api/generic-agent/terminal",
        json={"agent": "claude", "project_id": "demo", "pty_session_id": pty_id()},
    )
    assert r.status_code == 200


# ── close_pty_session says whether the process is really gone ────────────────


def test_close_closes_a_session_the_host_holds_that_this_backend_never_adopted(monkeypatch):
    sent = []
    monkeypatch.setattr(terminal, "_pty_sessions", {})
    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(terminal.pty_client, "find_host", lambda key: {"port": 1, "token": "t"})
    monkeypatch.setattr(terminal.pty_client, "host_request", lambda info, msg, *a: sent.append(msg) or {"ok": True, "existed": True})
    assert terminal.close_pty_session("held-by-host") is True
    assert sent == [{"op": "close", "id": "held-by-host"}]


def test_close_reports_failure_when_the_host_cannot_be_reached(monkeypatch):
    def down(info, msg, *a):
        raise terminal.pty_client.HostError("down")

    monkeypatch.setattr(terminal, "_pty_sessions", {})
    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(terminal.pty_client, "find_host", lambda key: {"port": 1, "token": "t"})
    monkeypatch.setattr(terminal.pty_client, "host_request", down)
    assert terminal.close_pty_session("held-by-host") is False


def test_close_reports_failure_when_an_adopted_session_will_not_close(monkeypatch):
    from types import SimpleNamespace

    def refuse():
        raise OSError("stuck")

    monkeypatch.setattr(terminal, "_pty_sessions", {"x": SimpleNamespace(close=refuse)})
    assert terminal.close_pty_session("x") is False


def test_close_of_a_session_nobody_holds_is_a_success(monkeypatch):
    monkeypatch.setattr(terminal, "_pty_sessions", {})
    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: False)
    assert terminal.close_pty_session("nothing") is True
