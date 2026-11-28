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
        await real(pty_id, text)

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
