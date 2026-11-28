"""A waiting session reaches chat after a wait when it was started in AI Gator, at most three at a time, and a
reply to one prompt message answers that prompt and no other."""

import pytest

from remote import commands, prompts
from remote.channel import InboundMessage
from tests.test_remote_chat_window import MINUTE, opened, say
from tests.test_remote_prompt_flow import routed, show
from tests.test_remote_prompts import ASK_USER_QUESTION, BASH_PERMISSION
from tests.test_remote_runner import BUDGET, World


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


async def app_session(w):
    session = await w.service.start(BUDGET, "from the app")
    session.from_chat = False
    return session


async def several(w, count):
    await opened(w)
    for _ in range(count):
        await w.service.start(BUDGET, "task")
    w.channel.posted.clear()


def quoted(w, message_id, text, age=0.0):
    w.seq = getattr(w, "seq", 500) + 1
    return InboundMessage(id=str(w.seq), text=text, created_at=w.clock.now - age, reply_to=message_id)


async def quote_reply(w, message_id, text):
    await w.runner.process([quoted(w, message_id, text)])


async def test_a_session_started_in_the_app_is_not_posted_until_it_has_waited_two_minutes(w):
    await opened(w)
    await app_session(w)
    w.channel.posted.clear()
    await show(w, "pty-1", BASH_PERMISSION)
    assert w.channel.posted == []
    w.clock.now += 119
    await w.runner.tick()
    assert w.channel.posted == []
    w.clock.now += 20
    await w.runner.tick()
    [text] = w.channel.posted
    assert text.startswith("[Gator - budget - Budget] Needs you: permission, waiting 2 min.\n")
    assert len(routed(w)) == 1
    await w.runner.tick()
    assert len(w.channel.posted) == 1


async def test_an_app_session_answered_in_the_app_before_the_wait_is_never_posted(w):
    await opened(w)
    await app_session(w)
    w.channel.posted.clear()
    await show(w, "pty-1", BASH_PERMISSION)
    w.clock.now += 100
    w.host.states["pty-1"] = {"state": "working", "at": w.clock.now}
    await w.runner.tick()
    w.clock.now += 100
    await w.runner.tick()
    assert w.channel.posted == []


async def test_a_session_started_in_chat_is_posted_at_once_without_a_wait(w):
    await opened(w)
    await say(w, "run the tests")
    w.channel.posted.clear()
    await show(w, "pty-1", BASH_PERMISSION)
    [text] = w.channel.posted
    assert "waiting" not in text.splitlines()[0]


async def test_only_three_messages_go_out_and_one_line_names_the_rest(w):
    await several(w, 4)
    for n in range(1, 5):
        await show(w, f"pty-{n}", BASH_PERMISSION, at=n)
    assert len(routed(w)) == 3
    assert [t.split("]")[0] for t in w.channel.posted[:3]] == [
        "[Gator - budget - Budget",
        "[Gator - budget-2 - Budget",
        "[Gator - budget-3 - Budget",
    ]
    assert w.channel.posted[3] == prompts.more_waiting([("budget-4", 1)])
    await w.runner.tick()
    await w.runner.tick()
    assert len(w.channel.posted) == 4


async def test_the_next_waiting_session_is_posted_once_an_answer_frees_a_place(w):
    await several(w, 4)
    for n in range(1, 5):
        await show(w, f"pty-{n}", BASH_PERMISSION, at=n)
    before = len(w.channel.posted)
    first = routed(w)[0]["message_id"]
    await quote_reply(w, first, "allow")
    assert w.host.typed == [("pty-1", (prompts.ENTER,))]
    after = w.channel.posted[before:]
    assert after[0] == "[Gator - budget - Budget] Allowed once."
    assert after[1].startswith("[Gator - budget-4 - Budget] Needs you: permission.")
    assert len(after) == 2
    assert len(routed(w)) == 3


async def test_a_quote_reply_answers_the_quoted_session_even_when_the_chat_is_closed(w):
    await opened(w)
    await say(w, "run the tests")
    await w.service.start(BUDGET, "second")
    await show(w, "pty-1", BASH_PERMISSION)
    await show(w, "pty-2", ASK_USER_QUESTION)
    second = next(m for m in routed(w) if m["session_id"] == w.service.resolve("budget-2").id)
    w.runner._window.close()
    await quote_reply(w, second["message_id"], "2")
    assert w.host.typed == [("pty-2", (prompts.DOWN, prompts.ENTER))]
    assert w.channel.posted[-1] == "[Gator - budget-2 - Budget] Got it: Blue."
    assert [m["session_id"] for m in routed(w)] == [w.service.resolve("budget").id]


async def test_a_quote_reply_to_the_other_session_does_not_answer_the_first(w):
    await opened(w)
    await say(w, "run the tests")
    await w.service.start(BUDGET, "second")
    await show(w, "pty-1", BASH_PERMISSION)
    await show(w, "pty-2", BASH_PERMISSION)
    first = next(m for m in routed(w) if m["session_id"] == w.service.resolve("budget").id)
    await quote_reply(w, first["message_id"], "deny")
    assert w.host.typed == [("pty-1", (prompts.ESCAPE,))]


async def test_a_late_quote_reply_to_an_answered_prompt_types_nothing_and_does_not_answer_the_next_one(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    old = routed(w)[0]["message_id"]
    await say(w, "allow")
    await show(w, "pty-1", {**BASH_PERMISSION, "tool_input": {"command": "ls"}}, at=30)
    w.host.typed.clear()
    w.channel.posted.clear()
    await quote_reply(w, old, "allow")
    assert w.host.typed == []
    assert w.channel.posted == [f"[Gator - budget - Budget] {prompts.ALREADY_ANSWERED}"]
    assert len(routed(w)) == 1


async def test_a_quote_reply_to_a_prompt_answered_in_the_app_says_so(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    posted = routed(w)[0]["message_id"]
    w.host.states["pty-1"] = {"state": "working", "at": w.clock.now + 9}
    await w.runner.tick()
    w.channel.posted.clear()
    await quote_reply(w, posted, "allow")
    assert w.host.typed == []
    assert w.channel.posted == [f"[Gator - budget - Budget] {prompts.ALREADY_ANSWERED}"]


async def test_a_quote_reply_to_a_message_gator_never_posted_is_an_ordinary_message(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    w.runner._window.close()
    await quote_reply(w, "somebody-elses-message", "allow")
    assert w.host.typed == []


async def test_a_quote_reply_that_is_not_an_answer_is_refused_and_the_prompt_still_waits(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    await quote_reply(w, routed(w)[0]["message_id"], "sure go ahead")
    assert w.host.typed == []
    assert "Not sent: this session is waiting on a permission." in w.channel.posted[-1]
    assert len(routed(w)) == 1


async def test_a_quote_reply_with_a_command_in_it_runs_that_command(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    await quote_reply(w, routed(w)[0]["message_id"], "@gator list")
    assert w.channel.posted[-1].startswith("[Gator] 1 session running:")
    assert w.host.typed == []


async def test_an_unquoted_answer_still_works_when_exactly_one_prompt_is_pending(w):
    await opened(w)
    await say(w, "run the tests")
    await w.service.start(BUDGET, "second")
    await show(w, "pty-2", ASK_USER_QUESTION)
    await say(w, "1")
    assert w.host.typed == [("pty-2", (prompts.ENTER,))]


async def test_a_stale_quote_reply_is_dropped_like_any_old_message(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    w.channel.posted.clear()
    await w.runner.process([quoted(w, routed(w)[0]["message_id"], "allow", age=3600)])
    assert w.host.typed == []
    assert w.channel.posted == [commands.stale_skipped(1, 900)]


async def test_replies_the_channel_lists_apart_are_answered_in_order_and_once(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", ASK_USER_QUESTION)
    posted = routed(w)[0]["message_id"]
    w.runner._window.close()
    await w.runner.process_replies([quoted(w, posted, "2")])
    assert w.host.typed == [("pty-1", (prompts.DOWN, prompts.ENTER))]
    await w.runner.process_replies([quoted(w, posted, "1")])
    assert len(w.host.typed) == 1
    assert w.channel.posted[-1] == f"[Gator - budget - Budget] {prompts.ALREADY_ANSWERED}"


async def test_a_prompt_answered_in_the_app_frees_its_place_for_the_next_waiting_session(w):
    await several(w, 4)
    for n in range(1, 5):
        await show(w, f"pty-{n}", BASH_PERMISSION, at=n)
    before = len(w.channel.posted)
    w.host.states["pty-1"] = {"state": "working", "at": w.clock.now + 50}
    await w.runner.tick()
    [text] = w.channel.posted[before:]
    assert text.startswith("[Gator - budget-4 - Budget] Needs you: permission.")
    assert all(m["session_id"] != w.service.resolve("budget").id for m in routed(w))
