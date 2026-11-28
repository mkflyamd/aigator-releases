"""Messages queued behind a busy session are typed by a task of its own. It never drops them silently."""

import asyncio

import pytest

from remote import commands
from tests.test_remote_chat_window import opened, say
from tests.test_remote_runner import World


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def gate_deliveries(w):
    gate = asyncio.Event()
    real = w.host.deliver

    async def deliver(pty_id, text, proceed=None):
        await gate.wait()
        await real(pty_id, text, proceed)

    w.host.deliver = deliver
    return gate


async def settle(w):
    await asyncio.gather(*list(w.runner._wakes), return_exceptions=True)


async def test_queued_messages_say_so_when_the_session_fell_asleep_and_the_wake_is_refused(w):
    await opened(w)
    await say(w, "run the tests")
    session = w.service.list()[0]
    gate = gate_deliveries(w)
    await say(w, "one")
    await say(w, "two")
    w.host.suspend_on_deliver = True
    session.last_wake_at = w.clock.now
    w.channel.posted.clear()
    gate.set()
    await settle(w)
    assert any("Could not be woken a moment ago" in p for p in w.channel.posted)
    assert w.channel.posted[-1] == commands.queued_not_sent("budget", 2, project="Budget")
    assert w.runner._outbox == {}
    assert w.host.delivered == [("pty-1", "run the tests")]


def turn_off(w):
    w.state.set_disarmed("teams", True)


def turn_on(w):
    w.state.set_disarmed("teams", False)


async def queued_behind_a_busy_session(w, *messages):
    await opened(w)
    await say(w, "run the tests")
    gate = gate_deliveries(w)
    for message in messages:
        await say(w, message)
    w.channel.posted.clear()
    return gate


async def test_turning_remote_control_off_stops_the_queue_and_says_how_many_were_not_sent(w):
    gate = await queued_behind_a_busy_session(w, "one", "two")
    turn_off(w)
    await w.runner.tick()
    gate.set()
    await settle(w)
    await w.runner.tick()
    assert w.host.delivered == [("pty-1", "run the tests")]
    assert w.channel.posted.count(commands.messages_not_sent(2)) == 1
    assert w.runner._outbox == {} and w.runner._drains == {}


async def test_a_message_that_reaches_the_typing_step_after_the_switch_is_off_is_not_typed(w):
    gate = await queued_behind_a_busy_session(w, "one")
    turn_off(w)
    w.guard.disarm()
    gate.set()
    await settle(w)
    await w.runner.tick()
    assert w.host.delivered == [("pty-1", "run the tests")]
    assert w.channel.posted == [commands.messages_not_sent(1)]


async def test_turning_it_off_and_on_again_during_the_wait_does_not_let_the_old_messages_out(w):
    gate = await queued_behind_a_busy_session(w, "one", "two")
    turn_off(w)
    await w.runner.tick()
    turn_on(w)
    await w.runner.tick()
    gate.set()
    await settle(w)
    assert w.guard.armed
    assert w.host.delivered == [("pty-1", "run the tests")]
    assert w.channel.posted == [commands.messages_not_sent(2)]


async def test_a_message_sent_after_it_is_back_on_is_typed(w):
    gate = await queued_behind_a_busy_session(w, "one")
    turn_off(w)
    await w.runner.tick()
    turn_on(w)
    await w.runner.tick()
    gate.set()
    await say(w, "fresh")
    await settle(w)
    assert w.host.delivered == [("pty-1", "run the tests"), ("pty-1", "fresh")]


async def test_a_wake_in_progress_and_its_queue_are_counted_when_remote_control_turns_off(w):
    await opened(w)
    await say(w, "run the tests")
    w.host.suspend("pty-1")
    gate = w.host.wake_gate = asyncio.Event()
    await say(w, "wake up")
    await say(w, "and this")
    w.channel.posted.clear()
    turn_off(w)
    await w.runner.tick()
    gate.set()
    await settle(w)
    await w.runner.tick()
    assert w.host.delivered == [("pty-1", "run the tests")]
    assert w.channel.posted == [commands.messages_not_sent(1), commands.messages_not_sent(1)]


async def test_a_switch_that_is_off_says_nothing_about_dropped_messages(w):
    await queued_behind_a_busy_session(w, "one")
    w.runner.sync_enabled(False)
    await w.runner.tick()
    assert w.channel.posted == []
    assert w.runner._abandoned == 0


async def test_a_shutdown_that_cancels_the_queue_puts_the_count_in_the_restart_line(w):
    await queued_behind_a_busy_session(w, "one", "two")
    await w.runner.shutdown()
    w.restart()
    w.host.restorable = []
    w.channel.posted.clear()
    await w.runner.restore()
    assert w.channel.posted == [commands.restarted(1, 0, 2)]
    assert "2 queued messages were not sent" in w.channel.posted[0]
