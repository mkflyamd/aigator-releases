"""Remote control never leaves the user at a dead end: every refusal names a next step that can work, a prompt
can be cancelled from chat, and a question takes a typed answer."""

import pytest

from remote import commands, prompts
from remote.session_host import OpenElsewhere
from tests.test_remote_chat_window import opened, say
from tests.test_remote_needs_you import quote_reply
from tests.test_remote_prompt_flow import routed, show, two_sessions
from tests.test_remote_prompts import ASK_USER_QUESTION, BASH_PERMISSION
from tests.test_remote_runner import World

DRAFT = {"tool_name": "mcp__outlook__send_email", "tool_input": {"to": "a@example.com"}}
PREFIX = "[\U0001F40A Gator - budget - Budget]"


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def test_open_elsewhere_is_permanent_so_no_one_is_told_to_retry():
    assert OpenElsewhere("x", True).permanent


def test_a_transient_refusal_says_to_send_again_and_a_permanent_one_does_not():
    transient = commands.peer_refused("Memory", "It is busy.")
    permanent = commands.peer_refused("Memory", "It is set to run without asking.", True)
    assert "Send it again in a moment." in transient
    assert "Send it again" not in permanent
    assert "`list`" in transient and "`list`" in permanent


def test_a_permanent_send_failure_offers_stop_and_a_new_session():
    out = commands.send_failed("budget", "It cannot be woken.", permanent=True)
    assert "`stop budget`, then send a message to start a new session." in out


def test_waking_tells_the_user_not_to_resend():
    assert "Your message goes in when it is up, so no need to resend." in commands.waking("budget")


def test_esc_is_a_command_with_an_optional_name():
    assert commands.parse("@gator esc").kind == "interrupt"
    assert commands.parse("@gator escape budget").name == "budget"


async def test_esc_cancels_the_waiting_prompt_and_keeps_the_session(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", DRAFT)
    await say(w, "esc")
    assert w.host.typed == [("pty-1", (prompts.ESCAPE,))]
    assert w.channel.posted[-1] == f"{PREFIX} {prompts.CANCELLED}"
    assert w.service.list()[0].prompt is None
    assert routed(w) == []


async def test_a_named_esc_reaches_only_that_session(w):
    await two_sessions(w)
    await show(w, "pty-1", DRAFT)
    await show(w, "pty-2", DRAFT)
    await say(w, "esc other")
    assert w.host.typed == [("pty-2", (prompts.ESCAPE,))]


async def test_esc_with_several_waiting_asks_which_and_types_nothing(w):
    await two_sessions(w)
    await show(w, "pty-1", DRAFT)
    await show(w, "pty-2", DRAFT)
    await say(w, "esc")
    assert w.host.typed == []
    assert w.channel.posted[-1] == commands.which_to_cancel(["budget", "other"])


async def test_esc_with_nothing_waiting_says_so(w):
    await opened(w)
    await say(w, "run the tests")
    await say(w, "esc")
    assert w.host.typed == []
    assert w.channel.posted[-1] == commands.nothing_to_cancel()


async def test_a_quote_reply_esc_cancels_the_quoted_prompt(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", DRAFT)
    [entry] = routed(w)
    await quote_reply(w, entry["message_id"], "esc")
    assert w.host.typed == [("pty-1", (prompts.ESCAPE,))]


async def test_esc_after_the_prompt_changed_types_nothing(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", DRAFT)
    w.host.states["pty-1"] = {"state": "working", "at": w.clock.now + 9}
    await say(w, "esc")
    assert w.host.typed == []
    assert prompts.ALREADY_ANSWERED in w.channel.posted[-1]


async def test_an_app_only_permission_offers_esc(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", {"tool_name": "WebFetch", "tool_input": {"url": "https://example.com"}})
    assert prompts.ESC_OPTION in w.channel.posted[-1]


async def test_a_reply_that_is_not_an_answer_to_a_permission_shows_the_options_again(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    await say(w, "hmm, not sure")
    assert w.host.typed == []
    assert w.channel.posted[-1].endswith("Next:\n• `allow` to allow once.\n• `deny` to deny.")


async def test_a_typed_answer_to_a_question_is_offered_and_typed_as_its_own_answer(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", ASK_USER_QUESTION)
    assert prompts.TYPE_OPTION in w.channel.posted[-1]
    await say(w, "@gator " + "x" * 900)
    assert w.host.typed == [] and "limit is 500" in w.channel.posted[-1]
    await say(w, "@gator " + "x" * prompts.ANSWER_MAX_CHARS)
    [(_, keys)] = w.host.typed
    assert keys[:2] == (prompts.DOWN, prompts.DOWN) and keys[-1] == prompts.ENTER
    assert len(keys[2]) == prompts.ANSWER_MAX_CHARS


async def test_a_typed_answer_goes_nowhere_when_the_question_changed(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", ASK_USER_QUESTION)
    w.host.states["pty-1"] = {"state": "working", "at": w.clock.now + 9}
    await say(w, "green please")
    assert w.host.typed == []
