"""The 12 hour Remote control window: one stored deadline shared by Teams and Slack."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from remote import commands, status
from remote.guard import Guard
from remote.master import ARM_SECONDS, Master
from remote.runner import RemoteRunner
from remote.service import RemoteService
from remote.state import State
from routes import config_routes, remote_control
from security import verify_csrf
from tests.test_remote_runner import BUDGET, Clock, FakeChannel, FakeHost, World

TIMED_OUT = commands.timed_out(ARM_SECONDS)
HOUR = 3600.0


class SlackChannel(FakeChannel):
    name = "slack"


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


async def started(w, count=1):
    await w.feed(w.msg(100, "old note"))
    for i in range(count):
        await w.service.start(BUDGET, f"job {i}")


def test_the_window_is_12_hours_and_a_second_arm_does_not_extend_it(tmp_path):
    clock = Clock()
    master = Master(State(tmp_path / "s.json"), clock)
    first = master.arm()
    assert first["deadline"] - first["armed_at"] == ARM_SECONDS == 12 * HOUR
    clock.now += 5 * HOUR
    assert master.arm() == first
    clock.now += 7 * HOUR - 1
    assert master.active()
    clock.now += 2
    assert master.expired() and not master.active()


def test_a_restart_neither_extends_nor_reopens_an_expired_window(tmp_path):
    clock = Clock()
    Master(State(tmp_path / "s.json"), clock).arm()
    clock.now += 13 * HOUR
    after_restart = Master(State(tmp_path / "s.json"), clock)
    assert after_restart.expired() and not after_restart.active()


def test_a_clock_moved_backwards_counts_as_expired(tmp_path):
    clock = Clock()
    master = Master(State(tmp_path / "s.json"), clock)
    master.arm()
    clock.now -= 60
    assert master.expired() and not master.active()


def test_a_clock_set_back_after_the_window_opened_counts_as_expired(tmp_path):
    clock = Clock()
    master = Master(State(tmp_path / "s.json"), clock)
    armed_at = master.arm()["armed_at"]
    clock.now += HOUR
    assert master.active()
    clock.now = armed_at + 60
    assert master.expired() and not master.active()
    assert Master(State(tmp_path / "s.json"), clock).expired()


def test_the_window_is_closed_at_the_deadline_exactly(tmp_path):
    clock = Clock()
    master = Master(State(tmp_path / "s.json"), clock)
    clock.now = master.arm()["deadline"]
    assert master.expired() and not master.active()


def test_a_stored_deadline_beyond_12_hours_is_cut_back(tmp_path):
    clock = Clock()
    state = State(tmp_path / "s.json")
    state.set_master({"armed_at": clock.now, "deadline": clock.now + 100 * HOUR})
    assert Master(state, clock).record()["deadline"] == clock.now + 12 * HOUR


def test_an_unreadable_record_means_never_armed(tmp_path):
    state = State(tmp_path / "s.json")
    state.set_master({"armed_at": "yesterday", "deadline": True})
    assert Master(state, Clock()).record() is None


async def test_at_12_hours_sessions_are_stopped_and_the_notice_posts_once(w):
    await started(w, count=2)
    w.clock.now += 12 * HOUR + 1
    await w.runner.tick()
    await w.runner.tick()
    assert sorted(w.host.killed) == ["pty-1", "pty-2"]
    assert w.service.list() == []
    assert w.channel.posted == [TIMED_OUT]
    assert w.runner.live is False


async def test_a_session_that_will_not_stop_is_retried_and_no_notice_is_sent_until_it_is(w):
    await started(w, count=2)
    w.host.fail_kill = {"pty-2"}
    w.clock.now += 12 * HOUR + 1
    await w.runner.tick()
    assert w.host.killed == ["pty-1"]
    assert w.channel.posted == []
    await w.runner.tick()
    assert w.channel.posted == []
    w.host.fail_kill = set()
    await w.runner.tick()
    assert sorted(w.host.killed) == ["pty-1", "pty-2"]
    assert w.channel.posted == [TIMED_OUT]


async def test_after_the_deadline_nothing_runs_and_a_command_is_told_so_once(w):
    await started(w)
    w.clock.now += 12 * HOUR + 1
    await w.runner.tick()
    posted = list(w.channel.posted)
    await w.feed(w.msg(101, "@gator late"))
    w.host.states["pty-1"] = {"state": "asking", "at": w.clock.now}
    await w.runner.tick()
    assert w.host.delivered == [("pty-1", "job 0")]
    assert w.channel.posted == posted + [commands.timed_out_reply(ARM_SECONDS)]


async def test_the_notice_is_not_repeated_after_a_backend_restart(w):
    await started(w)
    w.clock.now += 12 * HOUR + 1
    await w.runner.tick()
    w.restart()
    await w.runner.tick()
    assert w.channel.posted == []


async def test_a_backend_that_was_down_at_the_deadline_stops_the_sessions_when_it_returns(w):
    w.clock.now += 20 * HOUR
    w.restart()
    await w.service.start(BUDGET, "still running from before")
    await w.runner.tick()
    assert w.host.killed == ["pty-1"]
    assert w.channel.posted == [TIMED_OUT]


async def test_idle_sessions_are_still_stopped_after_the_window_closes(w):
    await started(w)
    Master(w.state, w.clock).disarm()
    w.service._idle = 60
    w.clock.now += 120
    await w.runner.tick()
    assert w.host.killed == ["pty-1"]


async def test_a_window_armed_while_the_sessions_are_stopping_gets_no_timed_out_notice(w):
    await started(w)
    w.clock.now += 12 * HOUR + 1
    real_stop_all = w.service.stop_all

    async def stop_all_then_rearm():
        result = await real_stop_all()
        Master(w.state, w.clock).arm()
        return result

    w.service.stop_all = stop_all_then_rearm
    await w.runner.tick()
    assert w.channel.posted == []
    assert Master(w.state, w.clock).active()


async def test_one_window_closes_both_channels(tmp_path):
    clock = Clock()
    state = State(tmp_path / "s.json")
    Master(state, clock).arm()
    worlds = []
    for channel in (FakeChannel(state), SlackChannel(state)):
        host = FakeHost()
        service = RemoteService(host, default_project=lambda: BUDGET, clock=clock)
        runner = RemoteRunner(channel, service, Guard(clock=clock), state, clock=clock)
        runner.sync_enabled(True)
        await service.start(BUDGET, "job")
        worlds.append((runner, host, channel))
    clock.now += 12 * HOUR + 1
    for runner, host, channel in worlds:
        await runner.tick()
        assert host.killed == ["pty-1"]
        assert channel.posted == [TIMED_OUT]


async def test_one_warning_goes_out_15_minutes_before_the_deadline(w):
    w.clock.now += 12 * HOUR - 16 * 60
    await w.runner.tick()
    assert w.channel.posted == []
    w.clock.now += 2 * 60
    await w.runner.tick()
    await w.runner.tick()
    assert len(w.channel.posted) == 1
    assert w.channel.posted == [commands.turns_off_soon(15 * 60)]
    assert "turns off in 15 minutes" in w.channel.posted[0]
    w.restart()
    await w.runner.tick()
    assert w.channel.posted == []


async def test_turning_the_switch_off_and_on_does_not_open_a_new_window(w):
    w.clock.now += 12 * HOUR + 1
    w.runner.sync_enabled(False)
    w.runner.sync_enabled(True)
    assert w.runner.live is False


@pytest.fixture
def rc_config(monkeypatch):
    cfg = {"teams_remote_control_enabled": True}
    monkeypatch.setattr(status, "load_config", lambda: cfg)
    monkeypatch.setattr(status.relay_settings, "admin_allows_self_chat_autosend", lambda: True)
    monkeypatch.setattr(status.relay_settings, "user_allows_self_chat_autosend", lambda: True)
    return cfg


def test_the_status_walks_off_on_warnings_and_expired(tmp_path, rc_config):
    clock = Clock()
    state = State(tmp_path / "s.json")
    assert status.compute(state, clock)["state"] == "off"
    assert status.arm(state, clock) is None
    snap = status.compute(state, clock)
    assert snap["state"] == "on" and snap["reason"] is None
    assert snap["expires_at"] - snap["armed_at"] == 12 * HOUR and snap["now"] == clock.now
    assert snap["channels"] == [
        {"name": "teams", "enabled": True, "armed": True},
        {"name": "slack", "enabled": False, "armed": False},
    ]
    clock.now += 11 * HOUR + 1
    assert status.compute(state, clock)["state"] == "warn_1h"
    clock.now += 46 * 60
    assert status.compute(state, clock)["state"] == "warn_15m"
    clock.now += 14 * 60
    assert status.compute(state, clock)["state"] == "expiring"
    state.set_channel_value("teams", "expiry_handled", Master(state, clock).record()["deadline"])
    expired = status.compute(state, clock)
    assert expired["state"] == "expired" and expired["armed_at"] is None and "12 hour" in expired["reason"]


def test_the_status_says_why_it_cannot_start(tmp_path, rc_config, monkeypatch):
    state = State(tmp_path / "s.json")
    monkeypatch.setattr(status.relay_settings, "user_allows_self_chat_autosend", lambda: False)
    assert status.compute(state)["state"] == "replies_off"
    monkeypatch.setattr(status.relay_settings, "admin_allows_self_chat_autosend", lambda: False)
    assert status.compute(state)["state"] == "replies_blocked_admin"
    rc_config["teams_remote_control_enabled"] = False
    assert status.compute(state)["state"] == "not_set_up"


def test_stop_all_from_chat_shows_as_stopped(tmp_path, rc_config):
    state = State(tmp_path / "s.json")
    status.arm(state)
    state.set_disarmed("teams", True)
    assert status.compute(state)["state"] == "stopped_from_chat"


@pytest.fixture
def client(monkeypatch, rc_config):
    from remote.state import shared

    monkeypatch.setattr(config_routes, "_update_config", lambda mutator: (mutator(rc_config), rc_config)[1])
    app = FastAPI()
    app.include_router(remote_control.router)
    app.include_router(config_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app), rc_config, shared()


def test_the_arm_and_disarm_routes_return_the_status(client):
    c, _, _ = client
    assert c.get("/api/remote/status").json()["state"] == "off"
    armed = c.post("/api/remote/arm")
    assert armed.status_code == 200 and armed.json()["state"] == "on"
    assert set(armed.json()) == {"state", "reason", "channels", "armed_at", "expires_at", "now"}
    off = c.post("/api/remote/disarm").json()
    assert off["state"] == "off" and off["expires_at"] is None


def test_arming_is_refused_while_replies_are_off(client, monkeypatch):
    c, _, _ = client
    monkeypatch.setattr(status.relay_settings, "user_allows_self_chat_autosend", lambda: False)
    refused = c.post("/api/remote/arm")
    assert refused.status_code == 409 and "Replies" in refused.json()["detail"]
    assert c.get("/api/remote/status").json()["state"] == "replies_off"


def test_arming_while_refused_opens_no_window(client, monkeypatch):
    c, _, state = client
    monkeypatch.setattr(status.relay_settings, "user_allows_self_chat_autosend", lambda: False)
    assert c.post("/api/remote/arm").status_code == 409
    assert state.master() is None


def test_restart_gives_a_running_window_a_fresh_12_hours(client):
    import time

    c, _, state = client
    now = time.time()
    state.set_master({"armed_at": now - 5 * HOUR, "deadline": now + 7 * HOUR})
    restarted = c.post("/api/remote/restart")
    body = restarted.json()
    assert restarted.status_code == 200 and body["state"] == "on"
    assert set(body) == {"state", "reason", "channels", "armed_at", "expires_at", "now"}
    assert body["armed_at"] >= now
    assert body["expires_at"] - body["armed_at"] == ARM_SECONDS


def test_restart_after_the_window_ran_out_opens_a_new_one_and_re_arms_a_stopped_channel(client):
    import time

    c, _, state = client
    now = time.time()
    state.set_master({"armed_at": now - 13 * HOUR, "deadline": now - HOUR})
    state.set_channel_value("teams", "expiry_handled", now - HOUR)
    state.set_disarmed("teams", True)
    assert c.get("/api/remote/status").json()["state"] == "expired"
    assert c.post("/api/remote/restart").json()["state"] == "on"
    assert state.disarmed("teams") is False


def test_restart_when_replies_are_off_is_refused_and_keeps_the_current_window(client, monkeypatch):
    import time

    c, _, state = client
    now = time.time()
    window = {"armed_at": now - 2 * HOUR, "deadline": now + 10 * HOUR}
    state.set_master(dict(window))
    monkeypatch.setattr(status.relay_settings, "user_allows_self_chat_autosend", lambda: False)
    refused = c.post("/api/remote/restart")
    assert refused.status_code == 409 and "Replies" in refused.json()["detail"]
    assert state.master() == window


def test_restart_with_nothing_set_up_is_refused_and_opens_no_window(client):
    c, cfg, state = client
    cfg["teams_remote_control_enabled"] = False
    cfg["slack_remote_control_enabled"] = False
    assert c.post("/api/remote/restart").status_code == 409
    assert state.master() is None


def test_the_arm_and_disarm_routes_need_the_csrf_token():
    app = FastAPI()
    app.include_router(remote_control.router)
    plain = TestClient(app)
    assert plain.post("/api/remote/arm").status_code in (401, 403)
    assert plain.post("/api/remote/disarm").status_code in (401, 403)
    assert plain.post("/api/remote/restart").status_code in (401, 403)


def test_switching_a_channel_on_opens_the_window_and_the_last_one_off_closes_it(client):
    c, cfg, _ = client
    cfg["teams_remote_control_enabled"] = False
    assert c.get("/api/remote/status").json()["state"] == "not_set_up"
    assert c.patch("/api/config", json={"teams_remote_control_enabled": True}).status_code == 200
    assert c.get("/api/remote/status").json()["state"] == "on"
    c.patch("/api/config", json={"teams_remote_control_enabled": False})
    assert c.get("/api/remote/status").json()["expires_at"] is None


def test_a_switch_on_with_no_window_says_how_to_turn_remote_control_on(tmp_path, rc_config):
    state = State(tmp_path / "s.json")
    snap = status.compute(state, Clock())
    assert snap["state"] == "off"
    assert snap["reason"] == "Remote control is not turned on. Arm it in Settings."
    assert set(snap) == {"state", "reason", "channels", "armed_at", "expires_at", "now"}
