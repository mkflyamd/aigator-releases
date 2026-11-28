"""Remote control posts into the user's own Teams chat and Slack DM only when the auto-send
gate is on, and still only into the user's own chat. Commands run either way."""

import logging
from datetime import datetime, timezone

import pytest

import agent_suspend
from relay import settings
from remote import slack_channel, teams_channel
from remote.channel import AutosendOff, ChannelRefused
from remote.guard import Guard
from remote.master import Master
from remote.runner import RemoteRunner
from remote.service import RemoteService
from remote.slack_channel import SlackSelfDM
from remote.state import State
from remote.teams_channel import TeamsSelfChat
from sandbox import policy as pol
from tests.test_remote_runner import BUDGET, Clock, FakeChannel, FakeHost
from tests.test_remote_slack_channel import ME, OTHER_DM, SELF_DM, FakeSlack

OTHER_TEAMS_CHAT = "19:someone@thread.v2"


class TeamsWorld:
    """A fake Teams behind the real adapter."""

    name = "teams"

    def __init__(self, monkeypatch):
        self.sent = []
        self.history = []
        monkeypatch.setattr(teams_channel, "send_message", self._send)
        monkeypatch.setattr(teams_channel, "fetch_messages", lambda chat_id: self.history)

    def _send(self, chat_id, html):
        self.sent.append((chat_id, html))
        return str(700 + len(self.sent))

    def adapter(self, state, own=True):
        return TeamsSelfChat(chat_id="48:notes" if own else OTHER_TEAMS_CHAT, state=state)

    def posts(self):
        return self.sent

    def say(self, seq, text, now):
        stamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
        return {"id": str(seq), "message_type": "message", "body": text, "body_html": "", "created_at": stamp}


class SlackWorldFake:
    """A fake Slack behind the real adapter."""

    name = "slack"

    def __init__(self, monkeypatch):
        self.fake = FakeSlack()
        monkeypatch.setattr(slack_channel, "_api", self.fake)
        monkeypatch.setattr(slack_channel, "_own_user_id", lambda: ME)

    @property
    def history(self):
        return self.fake.history

    @history.setter
    def history(self, value):
        self.fake.history = value

    def adapter(self, state, own=True):
        return SlackSelfDM(channel_id=SELF_DM if own else OTHER_DM, state=state)

    def posts(self):
        return self.fake.posts()

    def say(self, seq, text, now):
        return {"ts": f"{int(now)}.{seq:06d}", "user": ME, "text": text}


@pytest.fixture(params=["teams", "slack"])
def chat(request, monkeypatch, autosend_gate):
    return TeamsWorld(monkeypatch) if request.param == "teams" else SlackWorldFake(monkeypatch)


def test_gate_on_posts_to_the_own_chat(tmp_path, chat):
    state = State(tmp_path / "s.json")
    assert chat.adapter(state).post("[\U0001F40A Gator] Online")
    assert len(chat.posts()) == 1


def test_gate_off_posts_nothing_and_records_nothing(tmp_path, chat, autosend_gate):
    autosend_gate["on"] = False
    state = State(tmp_path / "s.json")
    with pytest.raises(AutosendOff):
        chat.adapter(state).post("[\U0001F40A Gator] Online")
    assert chat.posts() == []
    assert issubclass(AutosendOff, ChannelRefused)


def test_gate_on_but_not_the_own_chat_posts_nothing(tmp_path, chat):
    state = State(tmp_path / "s.json")
    with pytest.raises(ChannelRefused) as refused:
        chat.adapter(state, own=False).post("[\U0001F40A Gator] hello")
    assert not isinstance(refused.value, AutosendOff)
    assert chat.posts() == []


def test_gate_off_and_not_the_own_chat_posts_nothing(tmp_path, chat, autosend_gate):
    autosend_gate["on"] = False
    with pytest.raises(ChannelRefused):
        chat.adapter(State(tmp_path / "s.json"), own=False).post("[\U0001F40A Gator] hello")
    assert chat.posts() == []


def _runner(chat, tmp_path):
    clock = Clock()
    state = State(tmp_path / "s.json")
    host = FakeHost()
    service = RemoteService(host, default_project=lambda: BUDGET, clock=clock)
    runner = RemoteRunner(chat.adapter(state), service, Guard(clock=clock), state, clock=clock)
    Master(state, clock).arm()
    runner.sync_enabled(True)
    return runner, host, clock


async def _deliver(runner, chat, *messages):
    chat.history = list(messages)
    await runner.poll()


async def test_commands_still_run_with_the_gate_off_but_nothing_is_posted(tmp_path, chat, autosend_gate):
    autosend_gate["on"] = False
    runner, host, clock = _runner(chat, tmp_path)
    await runner.announce_online()
    await _deliver(runner, chat)
    await _deliver(runner, chat, chat.say(1, "@gator say ok", clock.now))
    assert host.delivered == [("pty-1", "say ok")]
    assert chat.posts() == []


async def test_stop_all_still_stops_with_the_gate_off_and_says_nothing(tmp_path, chat, autosend_gate):
    runner, host, clock = _runner(chat, tmp_path)
    await _deliver(runner, chat)
    await _deliver(runner, chat, chat.say(1, "@gator say ok", clock.now))
    posted = len(chat.posts())
    autosend_gate["on"] = False
    await _deliver(runner, chat, chat.say(2, "@gator stop all", clock.now), chat.say(1, "@gator say ok", clock.now))
    assert host.killed == ["pty-1"]
    assert len(chat.posts()) == posted


async def test_replies_resume_when_the_gate_is_turned_on_and_nothing_old_is_sent(tmp_path, chat, autosend_gate):
    autosend_gate["on"] = False
    runner, host, clock = _runner(chat, tmp_path)
    await _deliver(runner, chat)
    first = chat.say(1, "@gator say ok", clock.now)
    await _deliver(runner, chat, first)
    assert chat.posts() == []
    autosend_gate["on"] = True
    await _deliver(runner, chat, chat.say(2, "@gator list", clock.now), first)
    assert len(chat.posts()) == 1


async def test_a_reply_to_a_command_is_not_sent_to_a_chat_that_is_not_the_own_chat(tmp_path, chat):
    clock = Clock()
    state = State(tmp_path / "s.json")
    service = RemoteService(FakeHost(), default_project=lambda: BUDGET, clock=clock)
    runner = RemoteRunner(chat.adapter(state, own=False), service, Guard(clock=clock), state, clock=clock)
    Master(state, clock).arm()
    runner.sync_enabled(True)
    await runner.announce_online()
    assert chat.posts() == []


class OffChannel(FakeChannel):
    def post(self, text, reply_to=None):
        raise AutosendOff("posting to your own chat is switched off")


async def test_the_switch_being_off_is_logged_once_per_arming_period(tmp_path, caplog):
    clock = Clock()
    state = State(tmp_path / "s.json")
    service = RemoteService(FakeHost(), default_project=lambda: BUDGET, clock=clock)
    runner = RemoteRunner(OffChannel(state), service, Guard(clock=clock), state, clock=clock)
    Master(state, clock).arm()
    runner.sync_enabled(True)
    with caplog.at_level(logging.INFO, logger="remote.runner"):
        for _ in range(3):
            await runner.announce_online()
        assert caplog.text.count("auto-send is off") == 1
        runner.sync_enabled(False)
        runner.sync_enabled(True)
        await runner.announce_online()
        assert caplog.text.count("auto-send is off") == 2
    assert "could not post" not in caplog.text


@pytest.fixture
def real_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_suspend, "STATE_FILE", tmp_path / "suspended-agents.json")
    monkeypatch.setattr(pol, "policy_path", lambda: tmp_path / "sandbox-policy.json")
    monkeypatch.setattr(pol, "_is_posix", lambda: False)
    pol._reset_cache()
    return tmp_path


@pytest.fixture(params=["teams", "slack"])
def real_chat(request, monkeypatch, real_settings):
    return TeamsWorld(monkeypatch) if request.param == "teams" else SlackWorldFake(monkeypatch)


def test_with_the_real_settings_a_fresh_install_posts_nothing(tmp_path, real_chat):
    with pytest.raises(AutosendOff):
        real_chat.adapter(State(tmp_path / "s.json")).post("[\U0001F40A Gator] Online")
    assert real_chat.posts() == []


def test_with_the_real_settings_the_user_switch_turns_posting_on(tmp_path, real_chat):
    settings.set_user_self_chat_autosend(True)
    real_chat.adapter(State(tmp_path / "s.json")).post("[\U0001F40A Gator] Online")
    assert len(real_chat.posts()) == 1


def test_with_the_real_settings_the_admin_policy_beats_the_user_switch(tmp_path, real_chat, real_settings):
    (real_settings / "sandbox-policy.json").write_text('{"self_chat_autosend": "deny"}')
    pol._reset_cache()
    settings.set_user_self_chat_autosend(True)
    with pytest.raises(AutosendOff):
        real_chat.adapter(State(tmp_path / "s.json")).post("[\U0001F40A Gator] Online")
    assert real_chat.posts() == []
