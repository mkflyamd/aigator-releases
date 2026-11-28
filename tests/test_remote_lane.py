"""A project's remote session is one lane: it sleeps when the idle sweep suspends it and wakes by
its own session id on the next message. Nothing here may start a second session in its place."""

import asyncio

import pytest

from remote import commands
from remote.service import WAKE_MIN_INTERVAL, RemoteError
from remote.session_host import HostError, RestoredSession
from tests.test_remote_runner import BUDGET, OTHER, World


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


async def asleep(w, text="first task"):
    """A baselined chat with one lane that the idle sweep has since suspended."""
    await w.feed(w.msg(100, "old note"))
    await w.feed(w.msg(101, f"@gator {text}"))
    w.host.suspend("pty-1")
    return w.service.list()[0]


async def woken(w):
    await asyncio.gather(*list(w.runner._wakes))


def posted(w):
    return "\n".join(w.channel.posted)


async def test_a_started_lane_is_stored_with_its_project_session_and_state(w):
    await w.feed(w.msg(100, "old note"))
    await w.feed(w.msg(101, "@gator first task"))
    lane = w.state.lanes("teams")["budget"]
    assert (lane["project_id"], lane["pty_id"], lane["short"]) == ("budget", "pty-1", "budget")
    assert lane["vendor_session_id"] == "vendor-1"
    assert lane["state"] == "live"
    assert lane["last_activity"] == w.clock.now


async def test_a_sleeping_lane_is_not_reported_as_an_exited_process(w):
    await asleep(w)
    await w.runner.tick()
    assert "exited" not in posted(w)
    assert w.service.list()[0].state == "sleeping"
    assert w.state.lanes("teams")["budget"]["state"] == "sleeping"


async def test_list_and_status_say_sleeping(w):
    await asleep(w)
    await w.runner.tick()
    await w.feed(w.msg(102, "@gator list"))
    assert "1. budget · Budget · sleeping" in w.channel.posted[-1]
    await w.feed(w.msg(103, "@gator status budget"))
    assert w.channel.posted[-1] == commands.session_status(
        "budget", "sleeping", w.clock.now, w.clock.now, project="Budget"
    )


async def test_a_lane_that_wakes_on_its_own_is_live_again_at_the_next_tick(w):
    await asleep(w)
    await w.runner.tick()
    w.host.sleeping_ids.discard("pty-1")
    w.host.alive_ids.add("pty-1")
    await w.runner.tick()
    assert w.service.list()[0].state == "live"
    assert w.state.lanes("teams")["budget"]["state"] == "live"


async def test_a_live_lane_whose_process_vanished_still_reports_the_exit_once(w):
    await w.feed(w.msg(100, "old note"))
    await w.feed(w.msg(101, "@gator first task"))
    w.host.alive_ids.discard("pty-1")
    await w.runner.tick()
    await w.runner.tick()
    assert posted(w).count(commands.agent_exited("budget", project="Budget")) == 1
    assert w.service.list() == []
    assert w.state.lanes("teams") == {}


async def test_a_sleeping_lane_whose_save_vanished_says_it_is_gone_and_is_dropped(w):
    await asleep(w)
    await w.runner.tick()
    w.host.sleeping_ids.discard("pty-1")
    await w.runner.tick()
    assert commands.lane_lost("budget", project="Budget") in w.channel.posted
    assert "exited" not in posted(w)
    assert w.service.list() == []
    assert w.state.lanes("teams") == {}


async def test_the_next_message_acks_at_once_and_wakes_the_same_session_in_the_background(w):
    gate = w.host.wake_gate = asyncio.Event()
    await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    assert w.channel.posted[-1] == commands.waking("budget", project="Budget")
    assert w.host.delivered == [("pty-1", "first task")]
    assert w.service.list()[0].waking is True
    gate.set()
    await woken(w)
    assert w.host.delivered[-1] == ("pty-1", "second task")
    assert w.host.n == 1
    lane = w.service.list()[0]
    assert (lane.state, lane.waking) == ("live", False)
    assert w.state.lanes("teams")["budget"]["state"] == "live"


async def test_the_polling_loop_keeps_running_while_a_lane_wakes(w):
    w.host.wake_gate = asyncio.Event()
    await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    await w.feed(w.msg(103, "@gator list"))
    await w.runner.tick()
    assert "budget" in w.channel.posted[-1]
    assert w.host.woken[0][0] == "pty-1"
    w.host.wake_gate.set()
    await woken(w)


async def test_the_wake_resumes_with_the_lane_labels_so_it_stays_pinned(w):
    await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    await woken(w)
    pty_id, project_id, labels = w.host.woken[0]
    assert (pty_id, project_id) == ("pty-1", "budget")
    assert labels["remote_channel"] == "teams"
    assert labels["remote_short"] == "budget"


async def test_a_second_message_while_the_lane_wakes_does_not_wake_it_twice(w):
    gate = w.host.wake_gate = asyncio.Event()
    await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    await w.feed(w.msg(103, "@gator third task"))
    assert "already waking" in w.channel.posted[-1]
    gate.set()
    await woken(w)
    assert len(w.host.woken) == 1
    assert w.host.delivered == [("pty-1", "first task"), ("pty-1", "second task")]


async def test_a_wake_that_failed_is_reported_and_no_fresh_session_is_started(w):
    w.host.wake_error = HostError("The session could not be woken.")
    await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    await woken(w)
    assert w.channel.posted[-1] == commands.wake_failed("budget", "The session could not be woken.", project="Budget")
    assert w.host.n == 1
    assert w.host.delivered == [("pty-1", "first task")]
    lane = w.service.list()[0]
    assert (lane.state, lane.waking) == ("sleeping", False)


async def test_an_unexpected_wake_error_is_reported_too(w):
    w.host.wake_error = RuntimeError("boom")
    await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    await woken(w)
    assert "could not be woken" in w.channel.posted[-1]
    assert w.host.n == 1
    assert w.service.list()[0].waking is False


async def test_a_lane_that_just_failed_to_wake_is_not_retried_in_a_burst(w):
    w.host.wake_error = HostError("The session could not be woken.")
    await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    await woken(w)
    await w.feed(w.msg(103, "@gator third task"))
    assert "Try again in" in w.channel.posted[-1]
    assert len(w.host.woken) == 1
    w.clock.now += WAKE_MIN_INTERVAL + 1
    w.host.wake_error = None
    await w.feed(w.msg(104, "@gator fourth task"))
    await woken(w)
    assert len(w.host.woken) == 2
    assert w.host.delivered[-1] == ("pty-1", "fourth task")


async def test_a_wake_that_cannot_ever_work_fails_the_lane_until_it_is_stopped(w):
    w.host.wake_error = HostError("The saved session is gone, so it cannot be woken.", True)
    await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    await woken(w)
    assert w.service.list()[0].state == "failed"
    assert w.state.lanes("teams")["budget"]["state"] == "failed"
    w.clock.now += WAKE_MIN_INTERVAL + 1
    await w.feed(w.msg(103, "@gator third task"))
    assert "stop budget" in w.channel.posted[-1]
    assert len(w.host.woken) == 1
    assert w.host.n == 1


async def test_a_failed_lane_shows_in_status_and_starts_fresh_only_after_stop(w):
    w.host.wake_error = HostError("The saved session is gone.", True)
    await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    await woken(w)
    await w.feed(w.msg(103, "@gator status budget"))
    assert "Could not be woken" in w.channel.posted[-1]
    await w.feed(w.msg(104, "@gator stop budget"))
    assert w.service.list() == []
    await w.feed(w.msg(105, "@gator a new beginning"))
    assert w.host.n == 2
    assert w.host.delivered[-1] == ("pty-2", "a new beginning")


async def test_a_second_start_in_a_project_with_a_sleeping_lane_is_refused(w):
    await asleep(w)
    with pytest.raises(RemoteError, match="already has a session"):
        await w.service.start(BUDGET, "again")
    assert w.host.n == 1


async def test_turning_remote_control_off_while_a_lane_wakes_sends_nothing(w):
    gate = w.host.wake_gate = asyncio.Event()
    await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    w.guard.disarm()
    gate.set()
    await woken(w)
    assert w.host.delivered == [("pty-1", "first task")]
    assert "turned off" in w.channel.posted[-1]
    assert w.service.list()[0].waking is False


async def test_nothing_wakes_once_remote_control_has_expired(w):
    await asleep(w)
    w.guard.disarm()
    await w.feed(w.msg(102, "@gator second task"))
    assert w.host.woken == []
    assert w.runner._wakes == set()


async def test_an_idle_sleeping_lane_expires_and_is_closed_cleanly(tmp_path):
    w = World(tmp_path)
    w.service._idle = 3600
    await asleep(w)
    await w.runner.tick()
    w.clock.now += 3600
    w.guard.arm()
    await w.service.tick()
    assert w.host.killed == ["pty-1"]
    assert w.service.list() == []
    assert w.state.lanes("teams") == {}


async def test_stop_all_closes_a_sleeping_lane_and_drops_what_was_saved(w):
    await asleep(w)
    await w.runner.tick()
    await w.feed(w.msg(102, "@gator stop all"))
    assert w.host.killed == ["pty-1"]
    assert w.host.sleeping_ids == set()
    assert w.service.list() == []
    assert w.state.lanes("teams") == {}


async def test_stop_of_a_sleeping_lane_by_name_closes_it(w):
    await asleep(w)
    await w.feed(w.msg(102, "@gator stop budget"))
    assert w.host.killed == ["pty-1"]
    assert w.state.lanes("teams") == {}


async def test_a_sleeping_lane_survives_a_backend_restart_and_wakes_there(w):
    await asleep(w)
    await w.runner.tick()
    w.restart()
    await w.runner.restore()
    lane = w.service.list()[0]
    assert (lane.short, lane.pty_id, lane.vendor_session_id, lane.state) == ("budget", "pty-1", "vendor-1", "sleeping")
    await w.feed(w.msg(103, "@gator list"))
    assert "sleeping" in w.channel.posted[-1]
    await w.feed(w.msg(104, "@gator second task"))
    await woken(w)
    assert w.host.delivered[-1] == ("pty-1", "second task")
    assert w.host.n == 1


async def test_a_failed_lane_survives_a_restart_as_failed(w):
    w.host.wake_error = HostError("The saved session is gone.", True)
    await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    await woken(w)
    w.restart()
    await w.runner.restore()
    assert w.service.list()[0].state == "failed"


async def test_a_stored_lane_with_neither_process_nor_save_is_dropped_on_restart(w):
    await asleep(w)
    w.host.sleeping_ids.clear()
    w.restart()
    await w.runner.restore()
    assert w.service.list() == []
    assert w.state.lanes("teams") == {}


async def test_a_live_session_found_after_a_restart_replaces_a_stale_lane_for_its_project(w):
    await asleep(w)
    w.host.restorable = [
        RestoredSession(
            pty_id="pty-5", project=BUDGET, short="budget", vendor_session_id="vendor-5", created_at=w.clock.now
        )
    ]
    w.host.alive_ids.add("pty-5")
    w.restart()
    await w.runner.restore()
    sessions = w.service.list()
    assert [(s.pty_id, s.state) for s in sessions] == [("pty-5", "live")]
    assert [lane["pty_id"] for lane in w.state.lanes("teams").values()] == ["pty-5"]


async def test_lanes_of_different_projects_sleep_and_wake_independently(w):
    await asleep(w)
    other = await w.service.start(OTHER, "other task")
    assert other.state == "live"
    await w.runner.tick()
    await w.feed(w.msg(102, "@gator other more"))
    assert w.host.woken == []
    assert w.host.delivered[-1] == ("pty-2", "more")
    await w.feed(w.msg(103, "@gator budget second task"))
    await woken(w)
    assert [p for p, _, _ in w.host.woken] == ["pty-1"]


async def test_a_message_to_a_lane_the_sweep_suspended_since_the_last_tick_still_wakes_it(w):
    await w.feed(w.msg(100, "old note"))
    await w.feed(w.msg(101, "@gator first task"))
    w.host.suspend("pty-1")
    await w.feed(w.msg(102, "@gator second task"))
    await woken(w)
    assert w.host.woken[0][0] == "pty-1"
    assert w.host.delivered[-1] == ("pty-1", "second task")


async def test_a_stop_during_the_wake_sends_nothing(tmp_path):
    w = World(tmp_path)
    gate = w.host.wake_gate = asyncio.Event()
    session = await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    session.stopping = True
    gate.set()
    await woken(w)
    assert w.host.delivered == [("pty-1", "first task")]
    assert "stopped while it woke" in w.channel.posted[-1]
