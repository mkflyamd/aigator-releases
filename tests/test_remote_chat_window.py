"""The chat window: `@gator hi` opens it, untagged messages in the own chat then run as commands
until 30 minutes of quiet. Every post it makes goes through the auto-send gate."""

import ast
import re
from pathlib import Path

import pytest

from remote import commands
from remote.guard import Guard
from remote.runner import RemoteRunner
from remote.service import RemoteService
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
    assert greeting.startswith("[Gator] Gator on watch. This chat is open, so you can skip `@gator`.\n")
    assert helped.startswith("[Gator] Type a request and it runs in your Claude session.\n")
    assert greeting.split("\n", 1)[1] == helped.split("] ", 1)[1]
    assert "30 minutes of quiet" in helped


# ---------------------------------------------------------------- untagged messages inside and outside


async def test_an_untagged_message_runs_inside_the_window(w):
    await opened(w)
    await say(w, "run the tests")
    assert w.host.delivered == [("pty-1", "run the tests")]
    assert w.channel.posted[-1] == "[Gator - Claude - budget] Started. Working on it."


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
    assert w.channel.posted[-1].startswith("[Gator] 1 session running:")
    await say(w, "stop other")
    assert w.host.killed == ["pty-1"]


async def test_an_untagged_stop_all_works_and_closes_the_window(w):
    await opened(w)
    await say(w, "run the tests")
    await say(w, "stop all")
    assert w.host.killed == ["pty-1"]
    assert w.channel.posted[-1] == "[Gator] Stopped 1 session."
    assert window_of(w) is None


async def test_blank_untagged_messages_are_ignored(w):
    await opened(w)
    await say(w, "   ")
    assert w.channel.posted == [commands.greeting()]


async def test_an_untagged_greeting_word_repeats_the_greeting(w):
    await opened(w)
    await say(w, "hi")
    assert w.channel.posted == [commands.greeting(), commands.greeting()]
    assert w.host.delivered == []


# ---------------------------------------------------------------- never read back what Gator wrote


async def test_untagged_text_with_the_gator_prefix_never_runs(w):
    await opened(w)
    await say(w, "[Gator] run the tests")
    await say(w, "  [Gator - Claude - budget] Done.\nrun the tests")
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


async def test_the_absolute_cap_closes_the_window_and_posts_only_the_timeout_notice(w):
    await opened(w)
    w.clock.now += 24 * 3600
    await w.runner.tick()
    assert w.channel.posted == [commands.greeting(), commands.timed_out(24 * 3600)]
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


async def test_the_slow_down_notice_says_how_long_to_wait_in_words(w):
    await opened(w)
    for _ in range(19):
        await say(w, "list")
    assert not any("Slow down" in p for p in w.channel.posted)
    for _ in range(5):
        await say(w, "list")
    slow = [p for p in w.channel.posted if "Slow down" in p]
    assert slow == ["[Gator] Slow down, that was too many messages at once. Try again in 10 minutes."]


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
    assert w.channel.posted[-1] == f"[Gator] No session named {'n' * 40}. Send `list` to see what is running."


def test_not_found_text_strips_newlines_and_caps_the_name():
    out = commands.session_not_found("ab\ncd\r\n" + "x" * 100)
    assert "\n" not in out.split("\n")[0] and out.count("\n") == 0
    assert out == f"[Gator] No session named ab cd {'x' * 34}. Send `list` to see what is running."


# ---------------------------------------------------------------- the copy deck


def _deck():
    rows = [("budget", "Budget", "working"), ("other", "Other", "waiting for you")]
    return {
        "greeting": commands.greeting(),
        "help": commands.help_text(),
        "closed": commands.chat_closed_quiet(),
        "bye": commands.chat_closed_bye(),
        "timeout": commands.timed_out(24 * 3600),
        "slow_down": commands.slow_down(600),
        "stale_one": commands.stale_skipped(1, 900),
        "stale_many": commands.stale_skipped(3, 900),
        "list": commands.session_list(rows),
        "list_empty": commands.session_list([]),
        "not_found": commands.session_not_found("nope"),
        "stopped_one": commands.stopped(1),
        "stopped_many": commands.stopped(3),
        "no_sessions": commands.no_sessions(),
    }


@pytest.mark.parametrize("key", list(_deck()))
def test_every_system_message_starts_with_the_one_shared_prefix(key):
    assert _deck()[key].startswith(commands.SYSTEM_PREFIX + "] ")


@pytest.mark.parametrize("key", list(_deck()))
def test_the_deck_has_no_emoji_exclamation_marks_or_bold(key):
    text = _deck()[key]
    assert "!" not in text and "**" not in text and "*" not in text.replace("`", "")
    assert set(text) - set(text.encode("ascii", "ignore").decode()) <= {"·"}


def test_wordplay_lives_only_in_the_greeting_and_bye_lines():
    deck = _deck()
    assert [k for k, v in deck.items() if "Gator on watch." in v] == ["greeting"]
    assert [k for k, v in deck.items() if "Gator out." in v] == ["bye"]
    assert "Gator on watch" not in commands.agent_result("Claude", "budget", "Done.", "text")


def test_the_deck_texts_match_the_copy():
    deck = _deck()
    assert deck["closed"] == "[Gator] Chat closed after 30 minutes of quiet. Send `@gator hi` to open it again."
    assert deck["bye"] == "[Gator] Chat closed. Gator out. Send `@gator hi` to open it again."
    assert deck["stale_one"] == (
        "[Gator] Skipped a message you sent while AI Gator was off, because it was more than 15 minutes old. "
        "Send it again if you still need it."
    )
    assert deck["stale_many"].startswith("[Gator] Skipped 3 messages you sent while AI Gator was off")
    assert deck["list"] == (
        "[Gator] 2 sessions running:\n1. budget · Budget · working\n2. other · Other · waiting for you"
    )
    assert deck["stopped_one"] == "[Gator] Stopped 1 session."
    assert deck["stopped_many"] == "[Gator] Stopped 3 sessions."
    assert deck["no_sessions"] == "[Gator] No remote sessions are running."


def test_the_prefix_literal_has_one_home():
    """The loop guard reads commands.SYSTEM_PREFIX; no other module spells the prefix out in code."""
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
                if "[Gator" in node.value:
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_the_loop_guard_and_the_adapters_read_the_shared_prefix():
    from remote import runner, slack_channel, teams_channel

    for module in (runner, slack_channel, teams_channel):
        assert "SYSTEM_PREFIX" in Path(module.__file__).read_text(encoding="utf-8")


def test_the_timeout_notice_names_the_real_settings_section():
    html = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
    before_toggle = html[: html.index('id="teams-remote-control-toggle"')]
    label = re.findall(r'class="spanel-divider"[^>]*>([^<]+)<', before_toggle)[-1].strip()
    assert commands.SETTINGS_SECTION == label
    assert f"AI Gator settings, under {label}." in commands.timed_out(3600)


async def test_everything_a_whole_session_posts_carries_the_prefix(w):
    await opened(w)
    await say(w, "run the tests")
    await say(w, "list")
    await say(w, "status nope")
    await say(w, "help")
    await say(w, "too old", age=2000)
    w.host.states["pty-1"] = {"state": "asking", "at": w.clock.now + 5}
    w.host.last["pty-1"] = "Which one?"
    await w.runner.tick()
    await say(w, "bye")
    assert len(w.channel.posted) >= 7
    assert all(p.startswith(commands.SYSTEM_PREFIX) for p in w.channel.posted)


async def test_a_session_that_asked_a_question_is_listed_as_waiting_for_you(w):
    await opened(w)
    await say(w, "run the tests")
    w.host.states["pty-1"] = {"state": "asking", "at": w.clock.now + 5}
    w.host.last["pty-1"] = "Which one?"
    await w.runner.tick()
    await say(w, "list")
    assert w.channel.posted[-1].endswith("1. budget · Budget · waiting for you")
    await say(w, "the first one")
    await say(w, "list")
    assert w.channel.posted[-1].endswith("1. budget · Budget · working")


# ---------------------------------------------------------------- Teams and Slack behind the real adapters


@pytest.fixture(params=["teams", "slack"])
def chat(request, monkeypatch, autosend_gate):
    return TeamsWorld(monkeypatch) if request.param == "teams" else SlackWorldFake(monkeypatch)


def _runner(chat, tmp_path):
    clock = Clock()
    state = State(tmp_path / "s.json")
    host = FakeHost()
    service = RemoteService(host, default_project=lambda: BUDGET, clock=clock)
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
