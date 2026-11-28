"""The chat stays up: it is held while work or a question is pending, answers always get through, every dropped
command says it was not sent, and a restart or a lost connection is said out loud."""

import pytest

from remote import commands, prompts
from remote import status
from tests.test_remote_chat_window import MINUTE, WINDOW, opened, say, window_of
from tests.test_remote_needs_you import quote_reply
from tests.test_remote_prompt_flow import routed, show
from tests.test_remote_prompts import BASH_PERMISSION
from tests.test_remote_restart import Restartable
from tests.test_remote_runner import World, _finish


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


@pytest.fixture
def r(tmp_path):
    return Restartable(tmp_path)


async def test_a_running_turn_holds_the_window_and_it_closes_30_minutes_after_the_result(w):
    await opened(w)
    await say(w, "run the tests")
    for _ in range(6):
        w.clock.now += WINDOW / 2
        await w.runner.tick()
    assert window_of(w) is not None and window_of(w)[1] > w.clock.now
    assert commands.chat_closed_quiet() not in w.channel.posted
    await _finish(w, "All green.")
    w.channel.posted.clear()
    w.clock.now += WINDOW - MINUTE
    await w.runner.tick()
    assert window_of(w) is not None
    w.clock.now += 2 * MINUTE
    await w.runner.tick()
    assert commands.chat_closed_quiet() in w.channel.posted
    assert window_of(w) is None


async def test_allow_still_works_as_a_quote_reply_once_the_chat_is_closed(w):
    await opened(w)
    await say(w, "run the tests")
    w.channel.posted.clear()
    await show(w, "pty-1", BASH_PERMISSION)
    message_id = routed(w)[0]["message_id"]
    w.state.clear_window("teams")
    await quote_reply(w, message_id, "allow")
    assert w.host.typed == [("pty-1", (prompts.ENTER,))]


async def test_answers_are_never_held_back_by_the_rate_limit(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    for _ in range(25):
        w.guard.allow_command()
    w.channel.posted.clear()
    await say(w, "allow")
    assert w.host.typed == [("pty-1", (prompts.ENTER,))]
    assert not any("Not sent" in p for p in w.channel.posted)


async def test_a_new_request_over_the_limit_says_it_was_not_sent(w):
    await opened(w)
    for _ in range(25):
        w.guard.allow_command()
    w.channel.posted.clear()
    await say(w, "run the tests")
    assert w.host.delivered == []
    assert len(w.channel.posted) == 1 and w.channel.posted[0].startswith("[\U0001F40A Gator] Not sent:")


async def test_stop_is_never_held_back_by_the_rate_limit(w):
    await opened(w)
    await say(w, "run the tests")
    for _ in range(25):
        w.guard.allow_command()
    await say(w, "stop")
    assert w.host.killed == ["pty-1"]


async def test_a_long_paste_names_the_limit_and_the_way_around_it_every_time(w):
    await opened(w)
    long = "word " * 400
    for _ in range(3):
        await say(w, long)
    assert w.channel.posted.count(commands.too_long()) == 3
    assert "send up to 4096" in commands.too_long() and "1500" in commands.too_long()
    assert w.host.delivered == []


@pytest.mark.parametrize("text", ["@remote control stop", "@somebody else hi", "@team lunch?"])
async def test_an_unknown_at_name_is_not_a_command_and_stays_silent(w, text):
    await opened(w)
    w.channel.posted.clear()
    await say(w, text)
    assert w.channel.posted == []
    assert w.host.delivered == []


async def test_a_prompt_is_not_posted_again_after_a_restart(r):
    await opened(r)
    await say(r, "run the tests")
    await show(r, "pty-1", BASH_PERMISSION)
    assert sum("Allow" in p or "allow" in p for p in r.channel.posted) >= 1
    before = list(r.channel.posted)
    r.restart()
    await r.runner.restore()
    await r.runner.tick()
    await r.runner.tick()
    new = [p for p in r.channel.posted[len(before):] if "Gator restarted" not in p]
    assert new == []


async def test_a_restart_says_how_many_sessions_are_running_and_asleep(r):
    await opened(r)
    await say(r, "run the tests")
    r.restart()
    r.channel.posted.clear()
    await r.runner.restore()
    assert r.channel.posted == [commands.restarted(1, 0)]


async def test_a_restart_with_no_sessions_says_nothing(r):
    await opened(r)
    r.restart()
    r.channel.posted.clear()
    await r.runner.restore()
    assert r.channel.posted == []


async def test_a_result_that_finished_while_gator_was_down_is_still_delivered(r):
    await opened(r)
    await say(r, "run the tests")
    r.restart()
    await r.runner.restore()
    r.channel.posted.clear()
    r.clock.now += 5
    await _finish(r, "All green.")
    assert any("All green." in p for p in r.channel.posted)


async def test_a_lost_connection_shows_its_reason_in_the_pill_and_in_chat_once_back(r, monkeypatch):
    config = {"teams_remote_control_enabled": True}
    monkeypatch.setattr(status.relay_settings, "admin_allows_self_chat_autosend", lambda: True)
    monkeypatch.setattr(status.relay_settings, "user_allows_self_chat_autosend", lambda: True)
    await opened(r)
    r.clock.now += 60
    r.runner.connection_failed(RuntimeError("token expired"))
    snap = status.compute(r.state, r.clock, config)
    assert snap["state"] == "connection_failed"
    assert "token expired" in snap["reason"]
    r.channel.posted.clear()
    r.clock.now += 120
    await r.runner.connection_recovered()
    [line] = r.channel.posted
    assert "Back online" in line and "token expired" in line and "2 minutes" in line
    await r.runner.connection_recovered()
    assert len(r.channel.posted) == 1
    assert status.compute(r.state, r.clock, config)["state"] != "connection_failed"


async def test_a_note_sent_while_a_prompt_waits_is_still_rate_limited(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    for _ in range(25):
        w.guard.allow_command()
    w.channel.posted.clear()
    await say(w, "some other thought")
    assert len(w.channel.posted) == 1 and w.channel.posted[0].startswith("[\U0001F40A Gator] Not sent:")
    assert w.host.typed == []


async def test_a_restart_that_said_so_does_not_also_say_online(r):
    await opened(r)
    await say(r, "run the tests")
    r.state.clear_window("teams")
    r.restart()
    r.channel.posted.clear()
    await r.runner.restore()
    await r.runner.announce_online()
    assert r.channel.posted == [commands.restarted(1, 0)]
    await r.runner.announce_online()
    assert r.channel.posted[1:] == [commands.online()]


async def test_a_start_with_nothing_to_restore_still_says_online(r):
    await opened(r)
    r.state.clear_window("teams")
    r.restart()
    r.channel.posted.clear()
    await r.runner.restore()
    await r.runner.announce_online()
    assert r.channel.posted == [commands.online()]
