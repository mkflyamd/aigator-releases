
import time

import pytest

from remote import commands, slack_channel
from remote.channel import ChannelRefused, InboundMessage
from remote.guard import Guard
from remote.master import Master
from remote.runner import RemoteRunner
from remote.service import RemoteService
from remote.slack_channel import SlackSelfDM
from remote.state import State
from tests.test_remote_runner import BUDGET, Clock, FakeChannel, FakeHost

ME = "U111"
SELF_DM = "D111"
OTHER_DM = "D999"


class FakeSlack:
    def __init__(self):
        self.calls = []
        self.history = []
        self.channels = {SELF_DM: {"is_im": True, "user": ME}, OTHER_DM: {"is_im": True, "user": "U222"}}
        self.fail_post = None
        self.next_ts = 1
        self.threads = {}

    def __call__(self, endpoint, params=None, method="GET"):
        self.calls.append((endpoint, dict(params or {}), method))
        if endpoint == "conversations.open":
            return {"ok": True, "channel": {"id": SELF_DM}}
        if endpoint == "conversations.info":
            info = self.channels.get(params["channel"])
            return {"ok": True, "channel": info} if info else {"ok": False, "error": "channel_not_found"}
        if endpoint == "conversations.history":
            return {"ok": True, "messages": self.history}
        if endpoint == "conversations.replies":
            parent = {"ts": params["ts"], "user": ME, "text": "[Gator] prompt"}
            return {"ok": True, "messages": [parent, *self.threads.get(params["ts"], [])]}
        if endpoint == "chat.postMessage":
            if self.fail_post:
                return {"ok": False, "error": self.fail_post}
            ts = f"1700000000.{self.next_ts:06d}"
            self.next_ts += 1
            return {"ok": True, "ts": ts}
        raise AssertionError(endpoint)

    def posts(self):
        return [c for c in self.calls if c[0] == "chat.postMessage"]


@pytest.fixture
def slack(monkeypatch, autosend_gate):
    fake = FakeSlack()
    monkeypatch.setattr(slack_channel, "_api", fake)
    monkeypatch.setattr(slack_channel, "_own_user_id", lambda: ME)
    return fake


def test_post_to_the_own_self_dm_sends_and_records_the_ts(tmp_path, slack):
    state = State(tmp_path / "s.json")
    channel = SlackSelfDM(state=state)
    ts = channel.post("[\U0001F40A Gator] Online")
    assert ts == "1700000000.000001"
    assert slack.posts() == [("chat.postMessage", {"channel": SELF_DM, "text": "[\U0001F40A Gator] Online"}, "POST")]
    assert state.is_own_post("slack", "1700000000.000001")


def test_post_to_any_other_dm_is_refused_and_logged(tmp_path, slack, caplog):
    channel = SlackSelfDM(channel_id=OTHER_DM, state=State(tmp_path / "s.json"))
    assert channel.is_own_self_chat() is False
    with caplog.at_level("WARNING"):
        with pytest.raises(ChannelRefused, match="not the own self-DM"):
            channel.post("[\U0001F40A Gator] hello")
    assert slack.posts() == []
    assert OTHER_DM in caplog.text


def test_a_channel_that_is_not_a_dm_is_refused(tmp_path, slack):
    slack.channels["C123"] = {"is_im": False, "is_channel": True}
    channel = SlackSelfDM(channel_id="C123", state=State(tmp_path / "s.json"))
    with pytest.raises(ChannelRefused):
        channel.post("[\U0001F40A Gator] hello")
    assert slack.posts() == []


def test_a_failed_ownership_check_posts_nothing(tmp_path, slack):
    channel = SlackSelfDM(channel_id="D404", state=State(tmp_path / "s.json"))
    with pytest.raises(ChannelRefused):
        channel.post("[\U0001F40A Gator] hello")
    assert slack.posts() == []


def test_an_unknown_own_user_id_posts_nothing(tmp_path, slack, monkeypatch):
    monkeypatch.setattr(slack_channel, "_own_user_id", lambda: "")
    channel = SlackSelfDM(channel_id=SELF_DM, state=State(tmp_path / "s.json"))
    with pytest.raises(ChannelRefused):
        channel.post("[\U0001F40A Gator] hello")
    assert slack.posts() == []


def test_a_check_that_cannot_be_made_posts_nothing(tmp_path, slack, monkeypatch):
    def api(endpoint, params=None, method="GET"):
        if endpoint == "conversations.info":
            raise ConnectionError("network down")
        return slack(endpoint, params, method)

    monkeypatch.setattr(slack_channel, "_api", api)
    channel = SlackSelfDM(channel_id=SELF_DM, state=State(tmp_path / "s.json"))
    with pytest.raises(ChannelRefused, match="not the own self-DM"):
        channel.post("[\U0001F40A Gator] hello")
    assert slack.posts() == []


def test_no_self_dm_to_open_posts_nothing(tmp_path, slack, monkeypatch):
    def api(endpoint, params=None, method="GET"):
        if endpoint == "conversations.open":
            return {"ok": False, "error": "user_not_found"}
        return slack(endpoint, params, method)

    monkeypatch.setattr(slack_channel, "_api", api)
    channel = SlackSelfDM(state=State(tmp_path / "s.json"))
    with pytest.raises(ChannelRefused):
        channel.post("[\U0001F40A Gator] hello")
    assert slack.posts() == []


def test_the_self_dm_is_opened_with_the_own_user_id(slack):
    SlackSelfDM().poll()
    assert slack.calls[0] == ("conversations.open", {"users": ME}, "POST")


def test_the_ownership_check_is_cached_after_it_passes(tmp_path, slack):
    channel = SlackSelfDM(state=State(tmp_path / "s.json"))
    channel.poll()
    channel.post("[\U0001F40A Gator] one")
    channel.post("[\U0001F40A Gator] two")
    assert [c[0] for c in slack.calls].count("conversations.info") == 1


def test_post_that_could_form_a_command_is_refused(tmp_path, slack):
    channel = SlackSelfDM(state=State(tmp_path / "s.json"))
    for text in ("@gator stop all", "hello", "  @GATOR x", "[todo] x"):
        with pytest.raises(ChannelRefused):
            channel.post(text)
    assert slack.posts() == []


def test_post_escapes_slack_control_characters(tmp_path, slack):
    channel = SlackSelfDM(state=State(tmp_path / "s.json"))
    channel.post("[\U0001F40A Gator - x] <!channel> a & b")
    assert slack.posts()[0][1]["text"] == "[\U0001F40A Gator - x] &lt;!channel&gt; a &amp; b"


def test_post_converts_markdown_to_slack_mrkdwn(tmp_path, slack):
    channel = SlackSelfDM(state=State(tmp_path / "s.json"))
    channel.post("[\U0001F40A Gator - x] **Done** with `ls`\n- one\n- two")
    text = slack.posts()[0][1]["text"]
    assert "**" not in text
    assert text == "[\U0001F40A Gator - x] *Done* with `ls`\n\n• one\n• two"


def test_a_failed_post_raises_refused_and_records_nothing(tmp_path, slack):
    state = State(tmp_path / "s.json")
    slack.fail_post = "token_revoked"
    with pytest.raises(ChannelRefused, match="token_revoked"):
        SlackSelfDM(state=state).post("[\U0001F40A Gator] hi")
    assert not state.is_own_post("slack", "1700000000.000001")


def test_poll_returns_messages_newest_first_with_ts_ids_and_unescaped_text(slack):
    slack.history = [
        {"ts": "1700000005.000200", "user": ME, "text": "@gator a &amp; b &lt;c&gt;"},
        {"ts": "1700000004.000100", "subtype": "channel_join", "text": "joined"},
        {"ts": "1700000000.000200", "user": ME, "text": "@gator one"},
    ]
    messages = SlackSelfDM().poll()
    assert [m.id for m in messages] == ["1700000005.000200", "1700000000.000200"]
    assert messages[0].text == "@gator a & b <c>"
    assert messages[0].created_at == pytest.approx(1700000005.0002)
    assert slack.calls[-1][1] == {"channel": SELF_DM, "limit": slack_channel.HISTORY_LIMIT}


def test_an_unreadable_ts_has_no_time(slack):
    slack.history = [{"ts": "garbage", "user": ME, "text": "@gator x"}]
    (message,) = SlackSelfDM().poll()
    assert message.created_at == 0.0


def test_a_history_error_raises(monkeypatch):
    def api(endpoint, params=None, method="GET"):
        if endpoint == "conversations.open":
            return {"ok": True, "channel": {"id": SELF_DM}}
        return {"ok": False, "error": "missing_scope"}

    monkeypatch.setattr(slack_channel, "_api", api)
    monkeypatch.setattr(slack_channel, "_own_user_id", lambda: ME)
    with pytest.raises(RuntimeError, match="missing_scope"):
        SlackSelfDM().poll()


class SlackWorld:
    """A runner over a real SlackSelfDM and a fake Slack, with a controllable clock."""

    def __init__(self, tmp_path, slack):
        self.clock = Clock()
        self.slack = slack
        self.state = State(tmp_path / "s.json")
        self.host = FakeHost()
        service = RemoteService(self.host, default_project=lambda: BUDGET, clock=self.clock)
        self.runner = RemoteRunner(SlackSelfDM(state=self.state), service, Guard(clock=self.clock), self.state, clock=self.clock)
        Master(self.state, self.clock).arm()
        self.runner.sync_enabled(True)

    def ts(self, offset=0.0, seq=1):
        return f"{int(self.clock.now - offset)}.{seq:06d}"

    def say(self, ts, text):
        return {"ts": ts, "user": ME, "text": text}

    async def deliver(self, *newest_first):
        self.slack.history = list(newest_first)
        await self.runner.poll()


async def test_slack_command_runs_and_the_reply_is_posted_to_the_self_dm(tmp_path, slack):
    w = SlackWorld(tmp_path, slack)
    await w.deliver()
    await w.deliver(w.say(w.ts(), "@gator say ok"))
    assert w.host.delivered == [("pty-1", "say ok")]
    assert slack.posts() == []
    w.host.states["pty-1"] = {"state": "idle", "at": w.clock.now + 5}
    w.host.last["pty-1"] = "Two files are open."
    await w.runner.tick()
    (post,) = slack.posts()
    assert post[1]["channel"] == SELF_DM
    assert post[1]["text"] == "[\U0001F40A Gator - Budget] Two files are open."


async def test_gator_own_posts_are_never_read_back_as_commands(tmp_path, slack):
    w = SlackWorld(tmp_path, slack)
    await w.deliver()
    first = w.say(w.ts(), "@gator say ok")
    await w.deliver(first)
    w.host.states["pty-1"] = {"state": "idle", "at": w.clock.now + 5}
    w.host.last["pty-1"] = "Two files are open."
    await w.runner.tick()
    (post,) = slack.posts()
    echoed = w.say("1700000000.000001", post[1]["text"])
    await w.deliver(echoed, first)
    assert len(w.host.delivered) == 1
    assert w.host.killed == []


async def test_a_recorded_own_ts_is_ignored_even_if_its_text_looks_like_a_command(tmp_path, slack):
    w = SlackWorld(tmp_path, slack)
    await w.deliver()
    w.state.record_post("slack", w.ts(seq=99))
    await w.deliver(w.say(w.ts(seq=99), "@gator stop all"))
    assert w.host.killed == []
    assert w.host.delivered == []


async def test_ts_ordering_uses_history_position_not_number_comparison(tmp_path, slack):
    w = SlackWorld(tmp_path, slack)
    now = int(w.clock.now)
    first = w.say(f"{now}.000200", "@gator old")
    second = w.say(f"{now}.000300", "@gator two")
    third = w.say(f"{now + 1}.000100", "@gator three")
    await w.deliver(first)
    await w.deliver(third, second, first)
    assert [t for _, t in w.host.delivered] == ["two", "three"]
    await w.deliver(third, second, first)
    assert len(w.host.delivered) == 2
    assert w.state.last_id("slack") == third["ts"]


async def test_a_ts_older_than_the_stale_window_is_skipped_with_a_notice(tmp_path, slack):
    w = SlackWorld(tmp_path, slack)
    await w.deliver()
    w.clock.now += 3600
    await w.deliver(w.say(w.ts(offset=1800), "@gator late"))
    assert w.host.delivered == []
    (post,) = slack.posts()
    assert post[1]["text"] == commands.stale_skipped(1, 900)


async def test_a_message_not_addressed_to_gator_is_ignored(tmp_path, slack):
    w = SlackWorld(tmp_path, slack)
    await w.deliver()
    await w.deliver(w.say(w.ts(), "lunch at noon?"))
    assert w.host.delivered == []
    assert slack.posts() == []


async def test_list_and_stop_all_work_over_slack(tmp_path, slack):
    w = SlackWorld(tmp_path, slack)
    await w.deliver()
    a = w.say(w.ts(seq=1), "@gator say ok")
    await w.deliver(a)
    b = w.say(w.ts(seq=2), "@gator list")
    await w.deliver(b, a)
    assert "1. budget \u00b7 " in slack.posts()[-1][1]["text"]
    c = w.say(w.ts(seq=3), "@gator stop all")
    await w.deliver(c, b, a)
    assert w.host.killed == ["pty-1"]
    assert slack.posts()[-1][1]["text"] == commands.stopped(1)
    assert w.state.disarmed("slack") is True


async def test_stop_all_on_slack_leaves_teams_armed_and_its_sessions_running(tmp_path, slack):
    state = State(tmp_path / "s.json")
    clock = Clock()
    host = FakeHost()
    guards = {}

    def build(channel):
        service = RemoteService(host, default_project=lambda: BUDGET, clock=clock)
        guard = Guard(clock=clock)
        runner = RemoteRunner(channel, service, guard, state, clock=clock)
        Master(state, clock).arm()
        runner.sync_enabled(True)
        guards[channel.name] = guard
        return runner, service

    teams, teams_service = build(FakeChannel(state))
    slack_runner, slack_service = build(SlackSelfDM(state=state))
    now = int(clock.now)

    def teams_msg(mid, text):
        return InboundMessage(id=mid, text=text, created_at=clock.now)

    await teams.process([teams_msg("t0", "x")])
    await teams.process([teams_msg("t1", "@gator say ok"), teams_msg("t0", "x")])
    slack.history = []
    await slack_runner.poll()
    slack.history = [{"ts": f"{now}.000001", "user": ME, "text": "@gator say ok"}]
    await slack_runner.poll()
    assert len(teams_service.list()) == 1
    assert len(slack_service.list()) == 1

    slack.history = [
        {"ts": f"{now}.000002", "user": ME, "text": "@gator stop all"},
        {"ts": f"{now}.000001", "user": ME, "text": "@gator say ok"},
    ]
    await slack_runner.poll()
    assert slack_service.list() == []
    assert len(teams_service.list()) == 1
    assert state.disarmed("slack") is True
    assert state.disarmed("teams") is False
    assert guards["teams"].armed is True
    assert guards["slack"].armed is False


def test_channel_state_is_kept_per_channel(tmp_path):
    state = State(tmp_path / "s.json")
    state.set_last_id("teams", "42")
    state.set_last_id("slack", "1700000000.000200")
    state.record_post("slack", "1700000001.000100")
    assert state.last_id("teams") == "42"
    assert state.last_id("slack") == "1700000000.000200"
    assert state.is_own_post("slack", "1700000001.000100")
    assert not state.is_own_post("teams", "1700000001.000100")


def reply(ts, text, user=ME, **extra):
    return {"ts": ts, "user": user, "text": text, **extra}


def test_thread_replies_under_an_open_prompt_message_come_back_once_with_the_parent_as_reply_to(tmp_path, slack):
    state = State(tmp_path / "s.json")
    channel = SlackSelfDM(state=state)
    state.record_prompt_message("slack", "1700000000.000001", "pty:1", "p1", time.time() + 3600, time.time())
    slack.threads["1700000000.000001"] = [
        reply("1700000001.000001", "allow"),
        reply("1700000002.000001", "deny"),
    ]
    got = channel.poll_replies()
    assert [(m.id, m.text, m.reply_to) for m in got] == [
        ("1700000002.000001", "deny", "1700000000.000001"),
        ("1700000001.000001", "allow", "1700000000.000001"),
    ]
    assert channel.poll_replies() == []
    slack.threads["1700000000.000001"].append(reply("1700000003.000001", "2"))
    assert [m.text for m in channel.poll_replies()] == ["2"]


def test_thread_replies_from_someone_else_or_a_bot_are_not_read(tmp_path, slack):
    state = State(tmp_path / "s.json")
    channel = SlackSelfDM(state=state)
    state.record_prompt_message("slack", "1700000000.000001", "pty:1", "p1", time.time() + 3600, time.time())
    slack.threads["1700000000.000001"] = [
        reply("1700000001.000001", "allow", user="U222"),
        reply("1700000002.000001", "allow", bot_id="B1"),
        reply("1700000003.000001", "allow", subtype="channel_join"),
    ]
    assert channel.poll_replies() == []


def test_no_replies_are_asked_for_when_no_prompt_message_is_open_or_it_has_expired(tmp_path, slack):
    state = State(tmp_path / "s.json")
    channel = SlackSelfDM(state=state)
    assert channel.poll_replies() == []
    state.record_prompt_message("slack", "1700000000.000001", "pty:1", "p1", time.time() - 1, time.time() - 10)
    assert channel.poll_replies() == []
    assert [c for c in slack.calls if c[0] == "conversations.replies"] == []


def test_a_reply_under_a_prompt_that_closed_a_minute_ago_is_still_read_so_it_can_be_told_it_was_answered(tmp_path, slack):
    state = State(tmp_path / "s.json")
    channel = SlackSelfDM(state=state)
    state.record_prompt_message("slack", "1700000000.000001", "pty:1", "p1", time.time() + 3600, time.time())
    state.clear_prompt_messages("slack", "pty:1")
    slack.threads["1700000000.000001"] = [reply("1700000001.000001", "allow")]
    [got] = channel.poll_replies()
    assert got.reply_to == "1700000000.000001"
    assert channel.poll_replies() == []


def test_a_prompt_closed_long_ago_is_no_longer_polled(tmp_path, slack):
    state = State(tmp_path / "s.json")
    channel = SlackSelfDM(state=state)
    state.record_prompt_message("slack", "1700000000.000001", "pty:1", "p1", time.time() + 3600, time.time())
    state.clear_prompt_messages("slack", "pty:1")
    assert channel.poll_replies() == []
    stored = state._load()["slack"]["prompt_closed"]
    stored[0]["closed_at"] = time.time() - 3600
    state._save(state._load() | {"slack": {**state._load()["slack"], "prompt_closed": stored}})
    slack.calls.clear()
    assert channel.poll_replies() == []
    assert [c for c in slack.calls if c[0] == "conversations.replies"] == []
