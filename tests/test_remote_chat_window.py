"""The chat window: `@gator hi` opens it, untagged messages in the own chat then run as commands
until 30 minutes of quiet. Every post it makes goes through the auto-send gate."""

import ast
import io
import re
import sys
from pathlib import Path

import pytest

from remote import commands, slack_channel
from remote.channel import InboundMessage
from remote.guard import Guard
from remote.master import Master
from remote.runner import RemoteRunner
from remote.service import PROMPT_GRACE_SECONDS, RemoteService
from remote.state import State
from tests.test_remote_autosend_gate import SlackWorldFake, TeamsWorld
from tests.test_remote_runner import BUDGET, OTHER, Clock, FakeChannel, FakeHost, World, baselined

MINUTE = 60.0
WINDOW = commands.WINDOW_SECONDS
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


async def say(w, text, age=0.0):
    w.seq = getattr(w, "seq", 100) + 1
    await w.feed(w.msg(w.seq, text, age))


async def opened(w):
    await baselined(w)
    await say(w, "@gator hi")
    return w


def window_of(w):
    return w.state.window("teams")


# ---------------------------------------------------------------- opening and the greeting


async def test_hi_opens_the_window_and_replies_with_the_tips_without_starting_a_session(w):
    await baselined(w)
    await say(w, "@gator hi")
    assert w.channel.posted == [commands.greeting()]
    assert w.host.delivered == []
    assert w.service.list() == []
    assert window_of(w) is not None


@pytest.mark.parametrize("text", ["@gator hello", "@gator Hello.", "@GATOR hey!", "@gator start", "@gator  hi  "])
async def test_greeting_words_are_reserved_and_never_reach_the_agent(w, text):
    await baselined(w)
    await say(w, text)
    assert w.channel.posted == [commands.greeting()]
    assert w.host.delivered == []


async def test_a_greeting_word_inside_a_longer_request_is_an_ordinary_request(w):
    await baselined(w)
    await say(w, "@gator hi there, what changed?")
    assert w.host.delivered == [("pty-1", "hi there, what changed?")]
    assert window_of(w) is None


async def test_a_tagged_request_never_opens_the_window_by_itself(w):
    await baselined(w)
    await say(w, "@gator run the tests")
    assert window_of(w) is None
    await say(w, "buy milk")
    assert w.host.delivered == [("pty-1", "run the tests")]


async def test_the_greeting_has_the_tips_and_help_repeats_them_under_a_fresh_prefix(w):
    await baselined(w)
    await say(w, "@gator hi")
    await say(w, "@gator help")
    greeting, helped = w.channel.posted
    note = commands.EVERYTHING_GOES_TO_AGENT
    assert greeting.startswith(
        f"[{commands.CROC} Gator] Gator on watch. This chat is open, so you can skip `@gator`.\n{note}\n\nNext:\n"
    )
    assert helped.startswith("[\U0001F40A Gator] Here is what you can type.\n\nNext:\n")
    assert "Gator on watch" not in helped and helped.count(commands.CROC) == 1
    assert note not in helped
    assert greeting.split("\n\nNext:\n", 1)[1].startswith(helped.split("\n\nNext:\n", 1)[1])
    assert helped.endswith("• `bye` to close this chat.")


async def test_help_with_the_chat_closed_tells_the_user_to_tag_every_message(w):
    await baselined(w)
    await say(w, "@gator help")
    helped = w.channel.posted[-1]
    assert helped.startswith("[\U0001F40A Gator] This chat is closed, so start each message with `@gator`.\n\nNext:\n")
    assert "• `@gator hi` to open this chat, then skip `@gator`." in helped
    assert "• `@gator stop all` to stop everything and turn Remote control off." in helped
    assert "30 minutes" not in helped


async def test_hi_while_the_chat_is_open_says_so_and_extends_the_window(w):
    await opened(w)
    w.clock.now += 20 * MINUTE
    await say(w, "@gator hi")
    assert w.channel.posted == [commands.greeting(), commands.already_open()]
    assert w.channel.posted[-1].startswith("[\U0001F40A Gator] This chat is already open.\n\nNext:\n")
    w.clock.now += 20 * MINUTE
    await say(w, "run the tests")
    assert w.host.delivered == [("pty-1", "run the tests")]


# ---------------------------------------------------------------- untagged messages inside and outside


async def test_an_untagged_message_runs_inside_the_window(w):
    await opened(w)
    await say(w, "run the tests")
    assert w.host.delivered == [("pty-1", "run the tests")]
    assert w.channel.posted == [commands.greeting()]


async def test_an_untagged_mention_of_another_name_is_not_for_gator_and_gets_no_reply(w):
    await opened(w)
    await say(w, "@remote control I can't see the options")
    assert w.host.delivered == []
    assert w.channel.posted == [commands.greeting()]


async def test_an_untagged_mention_of_a_session_still_routes_to_it(w):
    await opened(w)
    await w.service.start(OTHER, "b")
    await say(w, "@other say ok")
    assert w.host.delivered[-1] == ("pty-1", "say ok")


async def test_an_untagged_message_is_ignored_when_no_window_is_open(w):
    await baselined(w)
    await say(w, "run the tests")
    assert w.host.delivered == []
    assert w.channel.posted == []


async def test_untagged_messages_route_like_tagged_ones(w):
    await opened(w)
    await w.service.start(OTHER, "b")
    await say(w, "other say ok")
    assert w.host.delivered[-1] == ("pty-1", "say ok")
    await say(w, "list")
    assert w.channel.posted[-1].startswith("[\U0001F40A Gator] 1 session running:")
    await say(w, "stop other")
    assert w.host.killed == ["pty-1"]


async def test_an_untagged_stop_all_works_and_closes_the_window(w):
    await opened(w)
    await say(w, "run the tests")
    await say(w, "stop all")
    assert w.host.killed == ["pty-1"]
    assert w.channel.posted[-1] == commands.stopped(1)
    assert window_of(w) is None


async def test_blank_untagged_messages_are_ignored(w):
    await opened(w)
    await say(w, "   ")
    assert w.channel.posted == [commands.greeting()]


async def test_an_untagged_greeting_word_says_the_chat_is_already_open(w):
    await opened(w)
    await say(w, "hi")
    assert w.channel.posted == [commands.greeting(), commands.already_open()]
    assert w.host.delivered == []


# ---------------------------------------------------------------- never read back what Gator wrote


async def test_untagged_text_with_the_gator_prefix_never_runs(w):
    await opened(w)
    await say(w, "[\U0001F40A Gator] run the tests")
    await say(w, "  [\U0001F40A Gator - budget] Done.\nrun the tests")
    assert w.host.delivered == []
    assert w.channel.posted == [commands.greeting()]


async def test_a_message_whose_id_gator_recorded_never_runs_even_untagged(w):
    await opened(w)
    w.state.record_post("teams", "555")
    await w.feed(w.msg(555, "run the tests"))
    assert w.host.delivered == []


async def test_gator_replies_in_the_chat_are_not_commands_when_read_back(w):
    await opened(w)
    await say(w, "run the tests")
    echoed = [w.msg(900 + i, text) for i, text in enumerate(w.channel.posted)]
    await w.feed(*echoed)
    assert len(w.host.delivered) == 1


# ---------------------------------------------------------------- never before the window


async def test_a_message_older_than_the_window_opening_is_never_run(w):
    await baselined(w)
    await say(w, "run the tests", age=120)
    await say(w, "@gator hi")
    await say(w, "run the tests, sent before hi but delivered late", age=60)
    assert w.host.delivered == []


async def test_a_message_without_a_timestamp_is_never_run_untagged(w):
    await opened(w)
    await say(w, "run the tests", age=w.clock.now)
    assert w.host.delivered == []


async def test_a_batch_runs_in_order_so_only_what_follows_hi_runs(w):
    await baselined(w)
    await w.feed(w.msg(101, "before", age=60), w.msg(102, "@gator hi"), w.msg(103, "after"))
    assert w.host.delivered == [("pty-1", "after")]


# ---------------------------------------------------------------- the older /code relay


async def test_a_code_message_is_left_to_the_older_relay(w):
    await opened(w)
    await say(w, "/code do x")
    await say(w, "  /code   do x")
    assert w.host.delivered == []
    assert w.channel.posted == [commands.greeting()]
    await say(w, "do x")
    assert w.host.delivered == [("pty-1", "do x")]


def test_the_window_uses_the_older_relays_own_pattern_not_a_copy():
    import teams_remote_control
    from remote import runner

    assert runner.LEGACY_CODE_RE is teams_remote_control._COMMAND_RE


# ---------------------------------------------------------------- sliding window and expiry


async def test_the_window_slides_from_the_last_message(w):
    await opened(w)
    w.clock.now += 20 * MINUTE
    await say(w, "first")
    w.clock.now += 25 * MINUTE
    await say(w, "second")
    w.clock.now += 29 * MINUTE
    await say(w, "third")
    assert [t for _, t in w.host.delivered] == ["first", "second", "third"]


async def test_tagged_commands_and_replies_to_list_also_extend_the_window(w):
    await opened(w)
    w.clock.now += 25 * MINUTE
    await say(w, "@gator list")
    w.clock.now += 25 * MINUTE
    await say(w, "run the tests")
    assert w.host.delivered == [("pty-1", "run the tests")]


async def test_a_message_after_the_quiet_period_is_ignored_and_the_closed_notice_comes_once(w):
    await opened(w)
    w.clock.now += WINDOW + 1
    await say(w, "run the tests")
    await say(w, "run it again")
    assert w.host.delivered == []
    assert w.channel.posted == [commands.greeting(), commands.chat_closed_quiet()]
    assert window_of(w) is None


async def test_the_window_is_still_open_just_before_the_end(w):
    await opened(w)
    w.clock.now += WINDOW - 1
    await say(w, "run the tests")
    assert w.host.delivered == [("pty-1", "run the tests")]


async def test_tick_closes_a_quiet_window_with_one_notice(w):
    await opened(w)
    w.clock.now += WINDOW
    await w.runner.tick()
    await w.runner.tick()
    assert w.channel.posted == [commands.greeting(), commands.chat_closed_quiet()]
    assert window_of(w) is None


async def test_a_quiet_window_can_be_opened_again(w):
    await opened(w)
    w.clock.now += WINDOW
    await w.runner.tick()
    await say(w, "@gator hi")
    await say(w, "run the tests")
    assert w.host.delivered == [("pty-1", "run the tests")]


async def test_a_stale_untagged_message_is_skipped_with_the_notice_and_does_not_extend_the_window(w):
    await opened(w)
    w.clock.now += 20 * MINUTE
    await say(w, "too old", age=16 * MINUTE)
    assert w.host.delivered == []
    assert w.channel.posted[-1] == commands.stale_skipped(1, 900)
    w.clock.now += 11 * MINUTE
    await w.runner.tick()
    assert window_of(w) is None


# ---------------------------------------------------------------- bye, stop, stop all, switches


async def test_bye_closes_the_window_and_says_so(w):
    await opened(w)
    await say(w, "@gator bye")
    assert w.channel.posted[-1] == commands.chat_closed_bye()
    assert window_of(w) is None
    await say(w, "run the tests")
    assert w.host.delivered == []


async def test_an_untagged_bye_closes_the_window_too(w):
    await opened(w)
    await say(w, "bye")
    assert w.channel.posted[-1] == commands.chat_closed_bye()
    assert window_of(w) is None


async def test_stop_stops_a_session_but_keeps_the_chat_open(w):
    await opened(w)
    await say(w, "run the tests")
    await say(w, "stop")
    assert w.host.killed == ["pty-1"]
    assert window_of(w) is not None
    await say(w, "run more")
    assert w.host.delivered[-1] == ("pty-2", "run more")


async def test_turning_remote_control_off_closes_the_window(w):
    await opened(w)
    w.runner.sync_enabled(False)
    assert window_of(w) is None


async def test_the_12_hour_deadline_closes_the_window_and_posts_only_the_timeout_notice(w):
    await opened(w)
    w.clock.now += 12 * 3600 + 1
    await w.runner.tick()
    assert w.channel.posted == [commands.greeting(), commands.timed_out(12 * 3600)]
    assert window_of(w) is None


# ---------------------------------------------------------------- restart


async def test_an_open_window_survives_a_restart(w):
    await opened(w)
    w.clock.now += 10 * MINUTE
    w.restart()
    await say(w, "run the tests")
    assert w.host.delivered == [("pty-1", "run the tests")]


async def test_an_expired_window_stays_closed_after_a_restart_and_says_nothing(w):
    await opened(w)
    w.clock.now += WINDOW + 1
    w.restart()
    assert window_of(w) is None
    await say(w, "run the tests")
    await w.runner.tick()
    assert w.host.delivered == []
    assert w.channel.posted == []


async def test_a_restart_does_not_run_anything_twice_or_run_what_came_before_the_window(w):
    await baselined(w)
    await say(w, "sent before hi", age=60)
    await say(w, "@gator hi")
    await say(w, "run the tests")
    assert w.host.delivered == [("pty-1", "run the tests")]
    last = w.seq
    w.restart()
    await w.feed(
        w.msg(last - 2, "sent before hi", 60), w.msg(last - 1, "@gator hi"), w.msg(last, "run the tests")
    )
    assert w.host.delivered == [("pty-1", "run the tests")]
    assert w.channel.posted == []


async def test_the_window_is_stored_per_channel(tmp_path):
    clock = Clock()
    state = State(tmp_path / "state.json")
    Master(state, clock).arm()
    teams, slack = FakeChannel(state), FakeChannel(state)
    slack.name = "slack"
    runners = {}
    for chan in (teams, slack):
        service = RemoteService(FakeHost(), default_project=lambda: BUDGET, clock=clock)
        runners[chan.name] = RemoteRunner(chan, service, Guard(clock=clock), state, clock=clock, stale_seconds=900)
        runners[chan.name].sync_enabled(True)
    from remote.channel import InboundMessage

    for name in runners:
        await runners[name].process([InboundMessage(id="1", text="old", created_at=clock.now)])
    await runners["teams"].process([InboundMessage(id="2", text="@gator hi", created_at=clock.now)])
    assert state.window("teams") is not None
    assert state.window("slack") is None
    await runners["slack"].process([InboundMessage(id="2", text="run the tests", created_at=clock.now)])
    assert slack.posted == []


# ---------------------------------------------------------------- the rate limit notice


async def test_a_flood_gets_one_notice_then_one_with_the_count_of_the_rest(w):
    await opened(w)
    for _ in range(19):
        await say(w, "list")
    assert not any("Not sent" in p for p in w.channel.posted)
    for _ in range(5):
        await say(w, "list")
    slow = [p for p in w.channel.posted if "Not sent" in p]
    assert slow == [commands.slow_down(600)]
    assert "• Wait 10 minutes, then send it again." in slow[0]
    w.clock.now += 30
    await w.runner.tick()
    slow = [p for p in w.channel.posted if "Not sent" in p]
    assert slow[1:] == [commands.slow_down(570, 4)]
    assert "4 messages, because too many came at once" in slow[1]


def test_guard_wait_seconds_counts_down_from_the_oldest_command():
    clock = Clock()
    guard = Guard(clock=clock, rate_limit=2, rate_window=600)
    assert guard.wait_seconds() == 0.0
    guard.allow_command()
    clock.now += 100
    guard.allow_command()
    assert guard.wait_seconds() == 500
    clock.now += 600
    assert guard.wait_seconds() == 0.0


def test_the_state_window_round_trips_per_channel_and_survives_reload(tmp_path):
    path = tmp_path / "state.json"
    state = State(path)
    assert state.window("teams") is None
    state.set_window("teams", 10.0, 1810.0)
    assert State(path).window("teams") == (10.0, 1810.0)
    assert State(path).window("slack") is None
    state.clear_window("teams")
    assert State(path).window("teams") is None


def test_in_words_reads_naturally():
    words = commands.in_words
    assert [words(s) for s in (30, 1, 60, 600, 900, 1800, 3600, 5400, 86400)] == [
        "30 seconds",
        "1 second",
        "1 minute",
        "10 minutes",
        "15 minutes",
        "30 minutes",
        "1 hour",
        "90 minutes",
        "24 hours",
    ]


# ---------------------------------------------------------------- the name in "No session named"


async def test_an_echoed_session_name_is_capped_and_flattened(w):
    await baselined(w)
    await say(w, "@gator status " + "n" * 200)
    assert w.channel.posted[-1] == commands.session_not_found("n" * 200)
    assert w.channel.posted[-1].startswith(f"[\U0001F40A Gator] No session named {'n' * 40}.\n\nNext:\n")


def test_not_found_text_strips_newlines_and_caps_the_name():
    out = commands.session_not_found("ab\ncd\r\n" + "x" * 100)
    assert out.split("\n")[0] == f"[\U0001F40A Gator] No session named ab cd {'x' * 34}."
    assert out.endswith("Next:\n• `list` to see what is running.")


# ---------------------------------------------------------------- the copy deck

AGENT_KEYS = {
    "status", "working", "progress", "done", "done_empty", "done_long",
    "waiting_choices", "waiting_open", "agent_stopped", "agent_exited",
    "status_sleeping", "status_failed", "waking", "wake_failed", "lane_lost",
}
TIPS_KEYS = {"greeting", "help_open", "help_closed"}
NO_NEXT_KEYS = {"done", "done_long", "waiting_open", "progress", "list_idle"}
QUIET_NOTE = "It also closes after 30 minutes of quiet."


def _deck():
    rows = [("budget", "Budget", commands.WORKING, 60.0, ""), ("other", "Other Repo", commands.WAITING, 120.0, "allow")]
    question = "Which folder?\n1. Use the repo root\n2. Use web/"
    return {
        "greeting": commands.greeting(),
        "help_open": commands.help_text(True),
        "help_closed": commands.help_text(False),
        "already_open": commands.already_open(),
        "too_long": commands.too_long(),
        "attachment": commands.attachment_not_sent(),
        "closed": commands.chat_closed_quiet(),
        "bye": commands.chat_closed_bye(),
        "timeout": commands.timed_out(24 * 3600),
        "slow_down": commands.slow_down(600),
        "stale_one": commands.stale_skipped(1, 900),
        "stale_many": commands.stale_skipped(3, 900),
        "list": commands.session_list(rows),
        "list_idle": commands.session_list([("budget", "Budget", commands.IDLE, 60.0, "")]),
        "list_empty": commands.session_list([]),
        "not_found": commands.session_not_found("nope"),
        "stopped_one": commands.stopped(1),
        "stopped_many": commands.stopped(3),
        "stop_all_failed": commands.stop_all_failed("budget", "other"),
        "no_sessions": commands.no_sessions(),
        "online": commands.online(),
        "error": commands.error_reply("No default project is set. Choose one in Settings, then resend."),
        "which_session": commands.which_session(["budget", "other"]),
        "which_to_stop": commands.which_to_stop(["budget", "other"]),
        "status": commands.session_status(
            "budget", commands.WORKING, 1000.0, 2000.0, now=1240.0, last_step="running tests"
        ),
        "working": commands.working("budget", "main", False),
        "progress": commands.progress("budget", 130),
        "done": commands.agent_result("Claude", "budget", "Done.", "Two files are open.")[0],
        "done_empty": commands.agent_result("Claude", "budget", "Done.", "")[0],
        "done_long": commands.agent_result("Claude", "budget", "Done.", "Outcome. " + "word " * 2000)[0],
        "waiting_choices": commands.agent_result("Claude", "budget", "Waiting for your answer.", question, True)[0],
        "waiting_open": commands.agent_result("Claude", "budget", "Waiting for your answer.", "Which?", True)[0],
        "agent_stopped": commands.agent_stopped("budget"),
        "agent_exited": commands.agent_exited("budget"),
        "list_sleeping": commands.session_list([("budget", "Budget", commands.SLEEPING, 0.0, "")]),
        "status_sleeping": commands.session_status("budget", commands.SLEEPING, 1000.0, 2000.0),
        "status_failed": commands.session_status("budget", commands.FAILED, 1000.0, 2000.0),
        "waking": commands.waking("budget"),
        "wake_failed": commands.wake_failed("budget", "The session could not be woken."),
        "lane_lost": commands.lane_lost("budget"),
    }


def _next_block(text):
    """(options, what follows them). Exactly one Next marker; options are the bullet lines under it."""
    head, marker, tail = text.partition("\n\nNext:\n")
    assert marker and "\n\nNext:\n" not in tail
    lines = tail.split("\n")
    options = []
    for line in lines:
        if not line.startswith("• "):
            break
        options.append(line)
    return options, lines[len(options) :]


@pytest.mark.parametrize("key", list(_deck()))
def test_every_message_opens_with_the_croc_marker_and_only_agent_replies_carry_a_project_slot(key):
    text = _deck()[key]
    assert commands.is_own_message(text)
    assert text.startswith(commands.MARKER + " Gator")
    assert text.count(commands.CROC) == 1
    if key in AGENT_KEYS:
        assert text.startswith(f"[{commands.CROC} Gator - ")
    else:
        assert text.startswith(f"[{commands.CROC} Gator] ")


@pytest.mark.parametrize("key", list(_deck()))
def test_every_message_ends_with_a_next_block_of_one_to_three_options(key):
    if key in NO_NEXT_KEYS:
        assert "Next:" not in _deck()[key]
        return
    options, rest = _next_block(_deck()[key])
    if key in TIPS_KEYS:
        assert len(options) == 5
        assert rest == (["", QUIET_NOTE] if key == "greeting" else [])
    else:
        assert 1 <= len(options) <= 3
        assert rest == []


@pytest.mark.parametrize("key", list(_deck()))
def test_the_deck_has_no_exclamation_marks_bold_or_other_emoji(key):
    text = _deck()[key]
    assert "!" not in text and "**" not in text and "*" not in text.replace("`", "")
    assert set(text) - set(text.encode("ascii", "ignore").decode()) <= {"·", "•", commands.CROC}
    assert len(text.split("\n")) <= 30


def test_wordplay_lives_only_in_the_greeting_and_bye_lines():
    deck = _deck()
    assert [k for k, v in deck.items() if "Gator on watch." in v] == ["greeting"]
    assert [k for k, v in deck.items() if "Gator out." in v] == ["bye"]
    for text in deck.values():
        assert not re.search(r"\b(teeth|snap|bite|swamp)\b|see you later", text, re.IGNORECASE)


def test_the_deck_texts_match_the_copy():
    deck = _deck()
    reopen = "Next:\n• `@gator hi` to open it again."
    assert deck["closed"] == f"[{commands.CROC} Gator] Chat closed after 30 minutes of quiet.\n\n{reopen}"
    assert deck["bye"] == f"[{commands.CROC} Gator] Chat closed. Gator out.\n\n{reopen}"
    assert deck["already_open"] == (
        "[\U0001F40A Gator] This chat is already open.\n\nNext:\n• Type a request to run it.\n• `help` to see all options."
    )
    assert deck["stale_one"] == (
        "[\U0001F40A Gator] Not sent: a message you sent while AI Gator was off, because it was more than 15 minutes old.\n\n"
        "Next:\n• Send it again if you still need it."
    )
    assert deck["stale_many"].startswith("[\U0001F40A Gator] Not sent: 3 messages you sent while AI Gator was off")
    assert deck["slow_down"] == (
        "[\U0001F40A Gator] Not sent: too many messages at once.\n\nNext:\n• Wait 10 minutes, then send it again."
    )
    assert deck["timeout"] == (
        "[\U0001F40A Gator] Remote control turned itself off after 24 hours.\n\n"
        "Next:\n• Open AI Gator, then Settings, then Remote control, and switch it on."
    )
    assert deck["list"] == (
        "[\U0001F40A Gator] 2 sessions running:\nNeeds you:\n1. other · Other Repo · waiting 2 min\n"
        "Working:\n2. budget · 1 min\n\nNext:\n• `other: allow` to allow once."
    )
    assert deck["list_idle"] == "[\U0001F40A Gator] 1 session running:\nIdle:\n1. budget · 1 min"
    assert deck["no_sessions"] == (
        "[\U0001F40A Gator] No remote sessions are running.\n\nNext:\n• Send a request and it starts a new session."
    )
    assert deck["not_found"] == "[\U0001F40A Gator] No session named nope.\n\nNext:\n• `list` to see what is running."
    assert deck["which_session"] == (
        "[\U0001F40A Gator] Which session?\n\nNext:\n• `budget: your message`\n• `other: your message`\n• `list` to see them all."
    )
    assert deck["stopped_one"].startswith("[\U0001F40A Gator] Stopped 1 session. Remote control is off.\n\n")
    assert deck["stopped_many"].startswith("[\U0001F40A Gator] Stopped 3 sessions. Remote control is off.\n\n")
    assert deck["status"] == (
        "[\U0001F40A Gator - budget] Working for 4 min. Last step: running tests.\n\nNext:\n• `stop` to stop it."
    )
    assert deck["working"] == (
        "[\U0001F40A Gator - budget] Working on it.\nBranch: main\n\nNext:\n• `stop` to stop it."
    )
    assert deck["progress"] == "[\U0001F40A Gator - budget] Still working, 2 min."
    assert deck["agent_stopped"] == (
        "[\U0001F40A Gator - budget] Stopped.\n\n"
        "Next:\n• Send a message to start it again.\n• `list` to see what is running."
    )
    assert deck["agent_exited"] == (
        "[\U0001F40A Gator - budget] The agent process exited.\n\nNext:\n• Send a message to start a new session."
    )
    assert deck["waiting_choices"].endswith(
        "Next:\n• `Use the repo root`\n• `Use web/`"
    )
    assert deck["waiting_open"] == "[\U0001F40A Gator - budget] Waiting for your answer.\nWhich?"
    assert deck["done"] == "[\U0001F40A Gator - budget] Done.\nTwo files are open."


def test_the_prefix_literal_has_one_home():
    """The prefix is built in commands.py; no other module spells it out in code."""
    offenders = []
    for path in sorted((ROOT / "web" / "remote").glob("*.py")):
        if path.name == "commands.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                if "[Gator" in node.value or commands.MARKER in node.value:
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_the_loop_guard_and_the_adapters_share_one_own_message_check():
    from remote import runner, slack_channel, teams_channel

    for module in (runner, slack_channel, teams_channel):
        assert "is_own_message" in Path(module.__file__).read_text(encoding="utf-8")


def test_the_timeout_notice_names_the_real_settings_section():
    html = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
    tab = re.search(
        r'data-tab="remote"[^>]*>\s*(?:<span[^>]*>(?:[^<]|<svg.*?</svg>)*</span\s*>)?\s*([^<]+)<', html, re.S
    )
    if tab:
        label = tab.group(1).strip()
    else:
        before_toggle = html[: html.index('id="teams-remote-control-toggle"')]
        label = re.findall(r'class="spanel-divider"[^>]*>([^<]+)<', before_toggle)[-1].strip()
    assert commands.SETTINGS_SECTION == label
    assert f"Open AI Gator, then Settings, then {label}, and switch it on." in commands.timed_out(3600)
    assert commands.stopped(1) == (
        "[\U0001F40A Gator] Stopped 1 session. Remote control is off.\n\n"
        "Next:\n• Open AI Gator and turn Remote control on again."
    )
    assert commands.stopped(3).splitlines()[0] == "[\U0001F40A Gator] Stopped 3 sessions. Remote control is off."


_BASE = commands.app_prefix()[:-1]


async def test_everything_a_whole_session_posts_carries_the_prefix_and_a_next_block(w):
    await opened(w)
    await say(w, "run the tests")
    await say(w, "list")
    await say(w, "status")
    await say(w, "status nope")
    await say(w, "help")
    await say(w, "too old", age=2000)
    w.host.states["pty-1"] = {"state": "asking", "at": w.clock.now + 5}
    w.host.last["pty-1"] = "Which one?"
    await w.runner.tick()
    w.clock.now += PROMPT_GRACE_SECONDS
    await w.runner.tick()
    await say(w, "bye")
    assert len(w.channel.posted) >= 7
    assert all(p.startswith(_BASE) for p in w.channel.posted)
    agent_replies = [
        p
        for p in w.channel.posted
        if p.startswith(_BASE + " - ") and "Next:" not in p and "Working since" not in p
    ]
    assert agent_replies == [commands.agent_result("Claude", "budget", "Waiting for your answer.", "Which one?", True, project="Budget")[0]]
    no_next = [p for p in w.channel.posted if "\n\nNext:\n" not in p]
    assert all(p.startswith(_BASE + " - ") or p.startswith(_BASE + "] 1 session") for p in no_next)


async def test_a_session_that_asked_a_question_is_listed_as_waiting_for_you(w):
    await opened(w)
    await say(w, "run the tests")
    w.host.states["pty-1"] = {"state": "asking", "at": w.clock.now + 5}
    w.host.last["pty-1"] = "Which one?"
    await w.runner.tick()
    w.clock.now += PROMPT_GRACE_SECONDS
    await w.runner.tick()
    await say(w, "list")
    assert "Needs you:\n1. budget · waiting " in w.channel.posted[-1]
    assert "• `budget: your answer` to answer the longest-waiting one." in w.channel.posted[-1]
    w.host.states["pty-1"]["state"] = "working"
    await say(w, "the first one")
    await say(w, "list")
    assert "Working:\n1. budget · " in w.channel.posted[-1]
    assert "Next:" not in w.channel.posted[-1]


async def test_status_of_one_session_says_its_state_since_when_and_last_activity(w):
    await opened(w)
    await say(w, "run the tests")
    await say(w, "status budget")
    out = w.channel.posted[-1]
    assert out.startswith("[\U0001F40A Gator - Budget] Working for ")
    assert "Next:\n• `stop` to stop it." in out and "Last activity" not in out


async def test_status_with_no_name_and_one_session_describes_that_session(w):
    await opened(w)
    await say(w, "run the tests")
    await say(w, "status")
    assert w.channel.posted[-1].startswith("[\U0001F40A Gator - Budget] Working for ")


async def test_the_deck_wording_for_a_stop_that_needs_a_name_and_for_an_exit(w):
    await opened(w)
    await w.service.start(BUDGET, "a")
    await w.service.start(OTHER, "b")
    await say(w, "stop")
    assert w.channel.posted[-1] == commands.which_to_stop(["budget", "other"])
    w.host.alive_ids.clear()
    await w.runner.tick()
    assert commands.agent_exited("budget", project="Budget", several=True) in w.channel.posted
    assert commands.agent_exited("other", project="Other") in w.channel.posted


async def test_stop_all_failing_says_so_and_keeps_remote_control_on(w):
    await opened(w)
    await say(w, "run the tests")

    w.host.fail_kill = {"pty-1"}
    await say(w, "stop all")
    assert w.channel.posted[-1].startswith("[\U0001F40A Gator] Could not stop budget")
    assert "Remote control stays on." in w.channel.posted[-1]
    assert w.guard.armed is True


# ---------------------------------------------------------------- the loop guard reads back no deck message


@pytest.mark.parametrize("key", list(_deck()))
async def test_the_loop_guard_ignores_every_deck_message_read_back_untagged(w, key):
    await opened(w)
    await say(w, _deck()[key])
    assert w.host.delivered == []
    assert w.channel.posted == [commands.greeting()]


async def test_the_loop_guard_ignores_the_greeting_and_a_recorded_id_catches_a_stripped_prefix(w):
    await opened(w)
    await say(w, f"[{commands.CROC} Gator] Gator on watch. do the thing")
    assert w.host.delivered == []
    w.state.record_post("teams", "777")
    stripped = _deck()["greeting"].split("] ", 1)[1]
    await w.feed(w.msg(777, stripped))
    assert w.host.delivered == []


# ---------------------------------------------------------------- Teams and Slack behind the real adapters


@pytest.fixture(params=["teams", "slack"])
def chat(request, monkeypatch, autosend_gate):
    return TeamsWorld(monkeypatch) if request.param == "teams" else SlackWorldFake(monkeypatch)


def _runner(chat, tmp_path):
    clock = Clock()
    state = State(tmp_path / "s.json")
    host = FakeHost()
    service = RemoteService(host, default_project=lambda: BUDGET, clock=clock)
    Master(state, clock).arm()
    runner = RemoteRunner(chat.adapter(state), service, Guard(clock=clock), state, clock=clock)
    runner.sync_enabled(True)
    return runner, host, clock, state


async def _history(runner, chat, *messages):
    chat.history = list(messages)
    await runner.poll()


async def test_on_each_channel_hi_posts_the_tips_and_untagged_text_then_runs(tmp_path, chat):
    runner, host, clock, state = _runner(chat, tmp_path)
    await _history(runner, chat)
    hi = chat.say(1, "@gator hi", clock.now)
    await _history(runner, chat, hi)
    assert len(chat.posts()) == 1
    assert "Gator on watch." in str(chat.posts()[0])
    assert host.delivered == []
    await _history(runner, chat, chat.say(2, "run the tests", clock.now), hi)
    assert host.delivered == [("pty-1", "run the tests")]


async def test_on_each_channel_untagged_text_is_ignored_before_hi_and_after_bye(tmp_path, chat):
    runner, host, clock, state = _runner(chat, tmp_path)
    await _history(runner, chat)
    before = chat.say(1, "run the tests", clock.now)
    await _history(runner, chat, before)
    hi = chat.say(2, "@gator hi", clock.now)
    await _history(runner, chat, hi, before)
    bye = chat.say(3, "bye", clock.now)
    await _history(runner, chat, bye, hi, before)
    after = chat.say(4, "run the tests", clock.now)
    await _history(runner, chat, after, bye, hi, before)
    assert host.delivered == []
    assert len(chat.posts()) == 2


async def test_on_each_channel_with_the_gate_off_the_window_works_and_nothing_is_posted(tmp_path, chat, autosend_gate):
    autosend_gate["on"] = False
    runner, host, clock, state = _runner(chat, tmp_path)
    await _history(runner, chat)
    hi = chat.say(1, "@gator hi", clock.now)
    await _history(runner, chat, hi)
    assert state.window(chat.name) is not None
    run = chat.say(2, "run the tests", clock.now)
    await _history(runner, chat, run, hi)
    assert host.delivered == [("pty-1", "run the tests")]
    host.states["pty-1"] = {"state": "idle", "at": clock.now + 1}
    host.last["pty-1"] = "Done."
    await runner.tick()
    clock.now += WINDOW + 1
    await runner.tick()
    assert state.window(chat.name) is None
    assert chat.posts() == []


async def test_on_each_channel_the_closed_notice_and_bye_go_through_the_gate_when_it_is_on(tmp_path, chat, autosend_gate):
    runner, host, clock, state = _runner(chat, tmp_path)
    await _history(runner, chat)
    hi = chat.say(1, "@gator hi", clock.now)
    await _history(runner, chat, hi)
    clock.now += WINDOW + 1
    await runner.tick()
    assert len(chat.posts()) == 2
    assert "Chat closed after 30 minutes of quiet." in str(chat.posts()[1])


async def test_on_each_channel_tips_bye_and_replies_are_suppressed_with_the_gate_off(tmp_path, chat, autosend_gate):
    autosend_gate["on"] = False
    runner, host, clock, state = _runner(chat, tmp_path)
    await _history(runner, chat)
    hi = chat.say(1, "@gator hi", clock.now)
    await _history(runner, chat, hi)
    help_ = chat.say(2, "help", clock.now)
    await _history(runner, chat, help_, hi)
    bye = chat.say(3, "bye", clock.now)
    await _history(runner, chat, bye, help_, hi)
    assert state.window(chat.name) is None
    assert chat.posts() == []


async def test_on_each_channel_the_timeout_notice_is_gated_too(tmp_path, chat, autosend_gate):
    autosend_gate["on"] = False
    runner, host, clock, state = _runner(chat, tmp_path)
    await _history(runner, chat)
    await _history(runner, chat, chat.say(1, "@gator hi", clock.now))
    clock.now += 24 * 3600
    await runner.tick()
    assert state.window(chat.name) is None
    assert chat.posts() == []


async def test_on_each_channel_the_loop_guard_ignores_every_deck_message(tmp_path, chat):
    runner, host, clock, state = _runner(chat, tmp_path)
    await _history(runner, chat)
    hi = chat.say(1, "@gator hi", clock.now)
    await _history(runner, chat, hi)
    echoes = [chat.say(10 + i, text, clock.now) for i, text in enumerate(_deck().values())]
    await _history(runner, chat, *reversed(echoes), hi)
    assert host.delivered == []
    assert len(chat.posts()) == 1


def test_the_adapters_send_a_multi_line_croc_message_intact(tmp_path, chat):
    text = commands.greeting()
    chat.adapter(State(tmp_path / "s.json")).post(text)
    sent = chat.posts()[0]
    if chat.name == "teams":
        content = sent[1]
        assert "\n" not in content
        paragraphs = re.findall(r"<div>(.*?)</div>", content)
        assert "".join(f"<div>{p}</div>" for p in paragraphs) == content
        lines = [line for p in paragraphs for line in p.split("<br>")]
        assert lines[0] == (
            f"[{commands.CROC} Gator] Gator on watch. This chat is open, so you can skip <code>@gator</code>."
        )
        assert "• <code>stop all</code> to stop everything and turn Remote control off." in lines
        assert lines[-1] == QUIET_NOTE
    else:
        assert sent[1]["text"] == text
        assert text.count("\n") == sent[1]["text"].count("\n") == 10


def test_tp_teams_send_survives_an_emoji_under_a_cp1252_console(monkeypatch):
    import httpx
    from routes import teams

    class Skype:
        def get_auth(self):
            return "token", "https://chat.example"

        def get_global_service(self):
            return None

    class Reply:
        status_code = 200
        text = '{"id": "9"}'

        def json(self):
            return {"id": "9"}

    sent = []
    monkeypatch.setattr(teams, "_get_skype_module", lambda: Skype())
    monkeypatch.setattr(teams, "_get_my_name", lambda: "Me")
    monkeypatch.setattr(teams, "_invalidate_chats_cache", lambda: None)
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: sent.append(kwargs["json"]) or Reply())
    console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    out = teams.tp_teams_send("48:notes", teams.TeamsSendRequest(message=f"[{commands.CROC} Gator] Gator on watch."))
    assert out["ok"] is True and out["message_id"] == "9"
    assert commands.CROC in sent[0]["content"]


def test_tp_teams_send_returns_the_arrival_time_the_skype_post_answers_with_as_the_message_id(monkeypatch):
    import httpx
    from routes import teams

    class Skype:
        def get_auth(self):
            return "token", "https://chat.example"

        def get_global_service(self):
            return None

    class Reply:
        status_code = 201
        text = '{"OriginalArrivalTime":1795839015312}'

        def json(self):
            return {"OriginalArrivalTime": 1795839015312}

    monkeypatch.setattr(teams, "_get_skype_module", lambda: Skype())
    monkeypatch.setattr(teams, "_get_my_name", lambda: "Me")
    monkeypatch.setattr(teams, "_invalidate_chats_cache", lambda: None)
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: Reply())
    out = teams.tp_teams_send("48:notes", teams.TeamsSendRequest(message=f"[{commands.CROC} Gator] Online."))
    assert out["message_id"] == "1795839015312"


def test_the_teams_channel_records_each_post_so_it_reads_back_as_our_own(monkeypatch, tmp_path):
    from remote import teams_channel
    from remote.teams_channel import TeamsSelfChat

    state = State(tmp_path / "s.json")
    monkeypatch.setattr(teams_channel, "require_autosend", lambda: None)
    monkeypatch.setattr(teams_channel, "send_message", lambda chat_id, content: "1795839015312")
    chat = TeamsSelfChat(state=state)
    assert chat.post(commands.online()) == "1795839015312"
    assert state.is_own_post("teams", "1795839015312")


# ---------------------------------------------------------------- the notepad guard: untagged text is not always for the agent

CAP = commands.UNTAGGED_MAX_CHARS
LONG = "word " * (CAP // 5 + 10)


def _inbound(w, text, **fields):
    w.seq = getattr(w, "seq", 100) + 1
    return InboundMessage(id=str(w.seq), text=text, created_at=fields.pop("created_at", w.clock.now), **fields)


def test_the_cap_and_the_greeting_line_are_named_constants():
    assert commands.UNTAGGED_MAX_CHARS == 1500
    assert commands.EVERYTHING_GOES_TO_AGENT in commands.greeting()
    assert commands.too_long() == (
        "[\U0001F40A Gator] Not sent: over 1500 characters.\n\n"
        "Next:\n• Add `@gator` to send up to 4096.\n• Or shorten it and send it again."
    )
    assert commands.attachment_not_sent() == (
        "[\U0001F40A Gator] Attachments are not sent from this chat.\n\nNext:\n• Describe what you need in text, and send that."
    )


async def test_an_oversize_untagged_message_is_not_sent_and_gets_one_plain_line(w):
    await opened(w)
    await say(w, LONG)
    assert len(LONG.strip()) > CAP
    assert w.host.delivered == []
    assert w.channel.posted == [commands.greeting(), commands.too_long()]


async def test_a_message_of_exactly_the_cap_is_still_sent(w):
    await opened(w)
    await say(w, "x" * CAP)
    assert w.host.delivered == [("pty-1", "x" * CAP)]
    assert commands.too_long() not in w.channel.posted


async def test_the_same_long_text_sent_with_the_tag_is_sent(w):
    await opened(w)
    await say(w, f"@gator {LONG}")
    assert w.host.delivered == [("pty-1", LONG.strip())]
    assert commands.too_long() not in w.channel.posted


async def test_the_long_tagged_message_is_sent_even_with_the_chat_closed(w):
    await baselined(w)
    await say(w, f"@gator {LONG}")
    assert w.host.delivered == [("pty-1", LONG.strip())]


async def test_an_untagged_message_with_an_attachment_is_not_sent_and_gets_the_plain_line(w):
    await opened(w)
    await w.feed(_inbound(w, "see the attached file", attachments=True))
    assert w.host.delivered == []
    assert w.channel.posted == [commands.greeting(), commands.attachment_not_sent()]


async def test_a_tagged_message_with_an_attachment_is_sent_as_text(w):
    await opened(w)
    await w.feed(_inbound(w, "@gator look at this", attachments=True))
    assert w.host.delivered == [("pty-1", "look at this")]


async def test_an_attachment_with_no_text_is_ignored_quietly(w):
    await opened(w)
    await w.feed(_inbound(w, "", attachments=True))
    assert w.host.delivered == []
    assert w.channel.posted == [commands.greeting()]


async def test_too_long_is_said_every_time_and_the_attachment_line_once_per_window(w):
    await opened(w)
    for _ in range(4):
        await say(w, LONG)
    await w.feed(_inbound(w, "pasted", attachments=True))
    await w.feed(_inbound(w, "pasted again", attachments=True))
    assert w.channel.posted == [commands.greeting()] + [commands.too_long()] * 4 + [commands.attachment_not_sent()]
    await say(w, "bye")
    await say(w, "@gator hi")
    await say(w, LONG)
    await say(w, LONG)
    assert w.channel.posted.count(commands.too_long()) == 6
    assert w.channel.posted.count(commands.attachment_not_sent()) == 1
    assert w.host.delivered == []


async def test_a_held_back_message_does_not_slide_the_window(w):
    await opened(w)
    w.clock.now += 20 * MINUTE
    await say(w, LONG)
    w.clock.now += 11 * MINUTE
    await say(w, "run the tests")
    assert w.host.delivered == []
    assert commands.chat_closed_quiet() in w.channel.posted


async def test_the_plain_line_is_not_posted_once_remote_control_is_stopped(w):
    await opened(w)
    await say(w, "stop all")
    posted = len(w.channel.posted)
    await say(w, LONG)
    assert len(w.channel.posted) == posted


async def test_an_untagged_message_with_no_timestamp_is_never_run_and_a_tagged_one_still_is(w):
    await opened(w)
    await w.feed(_inbound(w, "run the tests", created_at=0.0))
    assert w.host.delivered == []
    await w.feed(_inbound(w, "@gator run the tests", created_at=0.0))
    assert w.host.delivered == [("pty-1", "run the tests")]


def _with_attachment(chat, message):
    if chat.name == "teams":
        message["attachments"] = [{"name": "report.pdf"}]
    else:
        message["files"] = [{"id": "F1"}]
        message["subtype"] = "file_share"
    return message


async def _window_on(runner, chat, clock):
    await _history(runner, chat)
    hi = chat.say(1, "@gator hi", clock.now)
    await _history(runner, chat, hi)
    return hi


async def test_on_each_channel_an_oversize_untagged_message_is_held_back_but_the_tagged_one_runs(tmp_path, chat):
    runner, host, clock, state = _runner(chat, tmp_path)
    hi = await _window_on(runner, chat, clock)
    big = chat.say(2, LONG, clock.now)
    await _history(runner, chat, big, hi)
    assert host.delivered == []
    assert len(chat.posts()) == 2
    assert "Not sent: over 1500 characters" in str(chat.posts()[1])
    tagged = chat.say(3, f"@gator {LONG}", clock.now)
    await _history(runner, chat, tagged, big, hi)
    assert host.delivered == [("pty-1", LONG.strip())]


async def test_on_each_channel_an_attachment_is_held_back_once_per_window(tmp_path, chat):
    runner, host, clock, state = _runner(chat, tmp_path)
    hi = await _window_on(runner, chat, clock)
    one = _with_attachment(chat, chat.say(2, "see this", clock.now))
    two = _with_attachment(chat, chat.say(3, "and this", clock.now))
    await _history(runner, chat, one, hi)
    await _history(runner, chat, two, one, hi)
    assert host.delivered == []
    assert len(chat.posts()) == 2
    assert "Attachments are not sent from this chat" in str(chat.posts()[1])


async def test_on_each_channel_with_the_gate_off_the_message_is_still_held_back_and_nothing_is_posted(
    tmp_path, chat, autosend_gate
):
    autosend_gate["on"] = False
    runner, host, clock, state = _runner(chat, tmp_path)
    hi = await _window_on(runner, chat, clock)
    await _history(runner, chat, chat.say(2, LONG, clock.now), hi)
    assert host.delivered == []
    assert chat.posts() == []


async def test_on_each_channel_a_recorded_own_post_id_is_never_read_as_the_user(tmp_path, chat):
    runner, host, clock, state = _runner(chat, tmp_path)
    hi = await _window_on(runner, chat, clock)
    echo = chat.say(2, "run the tests", clock.now)
    state.record_post(chat.name, echo.get("id") or echo["ts"])
    await _history(runner, chat, echo, hi)
    assert host.delivered == []


@pytest.fixture
def slack(monkeypatch, autosend_gate):
    return SlackWorldFake(monkeypatch)


@pytest.mark.parametrize(
    "extra",
    [{"user": "U999"}, {"bot_id": "B1"}, {"app_id": "A1"}, {"user": None}, {"subtype": "bot_message"}],
    ids=["other sender", "bot id", "app id", "no sender", "bot subtype"],
)
async def test_slack_ignores_a_message_that_is_not_the_user_typing(tmp_path, slack, extra):
    runner, host, clock, state = _runner(slack, tmp_path)
    hi = await _window_on(runner, slack, clock)
    other = {**slack.say(2, "run the tests", clock.now), **extra}
    await _history(runner, slack, other, hi)
    assert host.delivered == []
    tagged = {**slack.say(3, "@gator run the tests", clock.now), **extra}
    await _history(runner, slack, tagged, other, hi)
    assert host.delivered == []


async def test_slack_reads_nothing_when_it_cannot_tell_who_the_user_is(tmp_path, slack, monkeypatch):
    runner, host, clock, state = _runner(slack, tmp_path)
    hi = await _window_on(runner, slack, clock)
    monkeypatch.setattr(slack_channel, "_own_user_id", lambda: "")
    await _history(runner, slack, slack.say(2, "@gator run the tests", clock.now), hi)
    assert host.delivered == []


async def test_slack_reads_the_users_own_message(tmp_path, slack):
    runner, host, clock, state = _runner(slack, tmp_path)
    hi = await _window_on(runner, slack, clock)
    await _history(runner, slack, slack.say(2, "run the tests", clock.now), hi)
    assert host.delivered == [("pty-1", "run the tests")]
