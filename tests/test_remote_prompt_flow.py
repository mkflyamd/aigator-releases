"""A permission or a question from an agent reaches the chat as one message per waiting session, and the
reply types exactly that answer, or nothing."""

import pytest

from remote import commands, prompts
from tests.test_remote_chat_window import MINUTE, WINDOW, opened, say, window_of
from tests.test_remote_prompts import ASK_USER_QUESTION, BASH_PERMISSION
from tests.test_remote_runner import BUDGET, OTHER, World


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


async def show(w, pty, payload, *, at=5):
    """What the agent's hooks leave behind when it asks: the payload, then the asking state."""
    when = w.clock.now + at
    w.host.states[pty] = {"state": "asking", "at": when}
    w.host.prompts[pty] = prompts.parse(payload, when)
    await w.runner.tick()


async def two_sessions(w):
    await opened(w)
    await say(w, "run the tests")
    await w.service.start(OTHER, "other task")
    w.channel.posted.clear()


def routed(w):
    return w.state.prompt_messages("teams")


async def test_a_permission_is_posted_with_the_agent_name_the_command_and_numbered_options(w):
    await opened(w)
    await say(w, "run the tests")
    w.channel.posted.clear()
    await show(w, "pty-1", BASH_PERMISSION)
    assert w.channel.posted == [
        "[Gator - budget - Budget] Needs you: permission.\n"
        "Tool: Bash\nCommand: echo hi > out.txt\n\n"
        "Next:\n• `allow` to allow once.\n• `deny` to deny."
    ]
    await w.runner.tick()
    assert len(w.channel.posted) == 1


async def test_the_posted_message_id_is_recorded_with_the_session_the_prompt_and_an_expiry(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    [entry] = routed(w)
    session = w.service.list()[0]
    assert entry["message_id"] == str(9000 + len(w.channel.posted) - 1)
    assert entry["session_id"] == session.id and entry["prompt_id"] == session.prompt.id
    assert entry["expires_at"] > w.clock.now


async def test_each_waiting_session_gets_its_own_message(w):
    await two_sessions(w)
    await show(w, "pty-1", BASH_PERMISSION)
    await show(w, "pty-2", ASK_USER_QUESTION)
    assert len(w.channel.posted) == 2
    assert w.channel.posted[0].startswith("[Gator - budget - Budget] Needs you: permission.")
    assert w.channel.posted[1].startswith("[Gator - other - Other] Needs you: a question.")
    assert {m["session_id"] for m in routed(w)} == {s.id for s in w.service.list()}
    assert len({m["message_id"] for m in routed(w)}) == 2


async def test_allow_types_enter_confirms_and_leaves_nothing_pending(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    await say(w, "allow")
    assert w.host.typed == [("pty-1", (prompts.ENTER,))]
    assert w.host.delivered == [("pty-1", "run the tests")]
    assert w.channel.posted[-1] == "[Gator - budget - Budget] Allowed once."
    assert routed(w) == []
    assert w.service.list()[0].prompt is None


async def test_deny_types_escape_and_the_turn_is_over(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    await say(w, "deny")
    assert w.host.typed == [("pty-1", (prompts.ESCAPE,))]
    assert w.channel.posted[-1] == "[Gator - budget - Budget] Denied."
    assert w.runner._turns == {}
    await w.runner.tick()
    assert w.channel.posted[-1] == "[Gator - budget - Budget] Denied."


async def test_a_number_picks_that_menu_row(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", ASK_USER_QUESTION)
    await say(w, "2")
    assert w.host.typed == [("pty-1", (prompts.DOWN, prompts.ENTER))]
    assert w.channel.posted[-1] == "[Gator - budget - Budget] Got it: Blue."


async def test_typed_words_answer_the_type_something_row(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", ASK_USER_QUESTION)
    await say(w, "green please")
    assert w.host.typed == [("pty-1", (prompts.DOWN, prompts.DOWN, "green please", prompts.ENTER))]


async def test_a_reply_that_is_not_an_answer_to_a_permission_says_what_is_asked_and_types_nothing(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    await say(w, "sure, go ahead and do it")
    assert w.host.typed == [] and w.host.delivered == [("pty-1", "run the tests")]
    out = w.channel.posted[-1]
    assert out.startswith("[Gator - budget - Budget] Not sent: this session is waiting on a permission.\nTool: Bash\n")
    assert out.endswith("Next:\n• `allow` to allow once.\n• `deny` to deny.")
    assert len(routed(w)) == 1
    await say(w, "allow")
    assert w.host.typed == [("pty-1", (prompts.ENTER,))]


async def test_an_out_of_range_number_says_what_to_pick_and_still_waits(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", ASK_USER_QUESTION)
    await say(w, "5")
    assert w.host.typed == []
    assert "Not sent: pick 1 or 2, or type your answer." in w.channel.posted[-1]
    assert w.service.list()[0].waiting


async def test_a_draft_cannot_be_answered_from_chat(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", {"tool_name": "mcp__outlook__send_email", "tool_input": {"to": "a@example.com"}})
    assert w.channel.posted[-1] == (
        "[Gator - budget - Budget] Needs you: a draft to review.\nOpen AI Gator to review it and send."
    )
    await say(w, "allow")
    assert w.host.typed == []
    assert "Not sent: this one has to be answered in AI Gator." in w.channel.posted[-1]


async def test_a_prompt_that_changed_before_the_reply_types_nothing_and_says_it_was_already_answered(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    w.host.states["pty-1"] = {"state": "working", "at": w.clock.now + 9}
    await say(w, "allow")
    assert w.host.typed == []
    assert w.channel.posted[-1] == f"[Gator - budget - Budget] {prompts.ALREADY_ANSWERED}"
    assert routed(w) == []


async def test_a_prompt_answered_in_the_app_is_not_typed_over_by_a_late_reply(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    del w.host.prompts["pty-1"]
    await say(w, "allow")
    assert w.host.typed == []
    assert prompts.ALREADY_ANSWERED in w.channel.posted[-1]


async def test_a_new_prompt_replaces_the_old_one_in_the_record(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    first = routed(w)[0]["prompt_id"]
    await show(w, "pty-1", {**BASH_PERMISSION, "tool_input": {"command": "ls"}}, at=20)
    [entry] = routed(w)
    assert entry["prompt_id"] != first
    await say(w, "allow")
    assert [k for _, k in w.host.typed] == [(prompts.ENTER,)]


async def test_with_two_waiting_sessions_a_bare_answer_asks_which_and_types_nothing(w):
    await two_sessions(w)
    await show(w, "pty-1", BASH_PERMISSION)
    await show(w, "pty-2", ASK_USER_QUESTION)
    await say(w, "2")
    assert w.host.typed == []
    assert w.channel.posted[-1] == commands.which_session(["budget", "other"])


async def test_a_named_answer_reaches_only_that_session(w):
    await two_sessions(w)
    await show(w, "pty-1", BASH_PERMISSION)
    await show(w, "pty-2", ASK_USER_QUESTION)
    await say(w, "other: 2")
    assert w.host.typed == [("pty-2", (prompts.DOWN, prompts.ENTER))]
    assert w.channel.posted[-1] == "[Gator - other - Other] Got it: Blue."
    assert [m["session_id"] for m in routed(w)] == [w.service.resolve("budget").id]
    await say(w, "budget: allow")
    assert w.host.typed[-1] == ("pty-1", (prompts.ENTER,))
    assert routed(w) == []


async def test_a_bare_answer_goes_to_the_only_waiting_session_when_several_run(w):
    await two_sessions(w)
    await show(w, "pty-2", ASK_USER_QUESTION)
    await say(w, "1")
    assert w.host.typed == [("pty-2", (prompts.ENTER,))]


async def test_a_message_to_a_session_that_is_not_waiting_is_an_ordinary_send(w):
    await two_sessions(w)
    await show(w, "pty-1", BASH_PERMISSION)
    await say(w, "other: keep going")
    assert w.host.delivered[-1] == ("pty-2", "keep going")
    assert w.host.typed == []
    assert len(routed(w)) == 1


async def test_a_plain_send_to_a_waiting_session_without_a_prompt_clears_nothing_it_did_not_own(w):
    await two_sessions(w)
    await show(w, "pty-1", BASH_PERMISSION)
    await show(w, "pty-2", ASK_USER_QUESTION)
    await say(w, "budget: allow")
    assert [m["session_id"] for m in routed(w)] == [w.service.resolve("other").id]


async def test_list_names_who_is_waiting_and_offers_the_answer_for_it(w):
    await two_sessions(w)
    await show(w, "pty-1", BASH_PERMISSION)
    w.clock.now += 3 * MINUTE
    await say(w, "list")
    out = w.channel.posted[-1]
    assert out.startswith("[Gator] 2 sessions running:\nNeeds you:\n1. budget · waiting ")
    assert "Working:\n2. other" in out
    assert out.endswith("Next:\n• `budget: allow` to allow once.")


async def test_the_quiet_close_does_not_fire_while_a_session_is_waiting(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    w.channel.posted.clear()
    for _ in range(4):
        w.clock.now += WINDOW / 2
        await w.runner.tick()
    assert window_of(w) is not None and window_of(w)[1] > w.clock.now
    assert w.channel.posted == []
    await say(w, "allow")
    assert w.host.typed == [("pty-1", (prompts.ENTER,))]


async def test_the_quiet_close_fires_once_nobody_is_waiting(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    await say(w, "allow")
    w.channel.posted.clear()
    w.clock.now += WINDOW + 1
    await w.runner.tick()
    assert commands.chat_closed_quiet() in w.channel.posted
    assert window_of(w) is None


async def test_help_while_the_chat_is_open_does_not_reprint_the_greeting(w):
    await opened(w)
    await say(w, "help")
    out = w.channel.posted[-1]
    assert out.startswith("[Gator] Here is what you can type.\n\nNext:\n")
    assert "Gator on watch" not in out and commands.CROC not in out
    assert commands.EVERYTHING_GOES_TO_AGENT not in out
    assert "30 minutes" not in out


async def test_a_prompt_in_a_session_the_chat_does_not_know_is_never_answered_by_a_stranger_message(w):
    await opened(w)
    await say(w, "run the tests")
    await show(w, "pty-1", BASH_PERMISSION)
    other_msgs = len(w.host.typed)
    await w.feed(w.msg(900, "allow", age=3600))
    assert len(w.host.typed) == other_msgs


async def test_the_default_project_is_the_one_the_session_started_in(w):
    await opened(w)
    await say(w, "run the tests")
    assert w.service.list()[0].project == BUDGET


def test_list_groups_by_state_with_the_longest_wait_first_and_omits_a_repeated_project():
    out = commands.session_list([
        ("budget", "Budget", commands.WORKING, 120.0, ""),
        ("hub", "Hub", commands.WAITING, 60.0, "allow"),
        ("api", "Services", commands.WAITING, 600.0, "your answer"),
        ("notes", "Notes", commands.IDLE, 3600.0, ""),
    ])
    assert out == (
        "[Gator] 4 sessions running:\n"
        "Needs you:\n"
        "1. api · Services · waiting 10 min\n"
        "2. hub · waiting 1 min\n"
        "Working:\n"
        "3. budget · 2 min\n"
        "Idle:\n"
        "4. notes · 1 h\n\n"
        "Next:\n"
        "• `api: your answer` to answer the longest-waiting one."
    )


def test_list_offers_no_next_block_when_nothing_is_waiting():
    out = commands.session_list([("budget", "Budget", commands.WORKING, 120.0, "")])
    assert "Next:" not in out and "budget · 2 min" in out


def test_status_leaves_out_last_activity_when_it_is_the_same_minute():
    same = commands.session_status("Claude", "budget", commands.WORKING, 1000.0, 1010.0)
    assert "Last activity" not in same
    later = commands.session_status("Claude", "budget", commands.WORKING, 1000.0, 5000.0)
    assert "Last activity" in later
