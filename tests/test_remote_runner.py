import pytest

from remote.channel import ChannelRefused, InboundMessage
from remote.guard import Guard
from remote.runner import RemoteRunner
from remote.service import RemoteService
from remote.session_host import HostError, HostSession, Project
from remote.state import State


class ProcessExit(BaseException):
    """What a process exit looks like to the runner: it is not an Exception."""


class FakeHost:
    restore_fails = False

    def __init__(self):
        self.n = 0
        self.restorable = []
        self.spawn_labels = []
        self.alive_ids = set()
        self.states = {}
        self.last = {}
        self.delivered = []
        self.killed = []
        self.crash_on_deliver = False
        self.exit_on_deliver = False
        self.fail_kill = set()

    async def spawn(self, project, labels=None):
        self.spawn_labels.append(labels)
        self.n += 1
        pty = f"pty-{self.n}"
        self.alive_ids.add(pty)
        return HostSession(pty_id=pty, vendor_session_id=f"vendor-{self.n}")

    async def restore(self, channel):
        if self.restore_fails:
            raise HostError("The terminal host did not answer.")
        return list(self.restorable)

    async def deliver(self, pty_id, text):
        if self.exit_on_deliver:
            raise ProcessExit()
        if self.crash_on_deliver:
            raise RuntimeError("boom")
        self.delivered.append((pty_id, text))

    async def alive(self, pty_id):
        return pty_id in self.alive_ids

    async def kill(self, pty_id):
        if pty_id in self.fail_kill:
            raise HostError("The terminal could not be closed.")
        self.killed.append(pty_id)
        self.alive_ids.discard(pty_id)

    async def state(self, pty_id):
        return self.states.get(pty_id)

    async def last_message(self, pty_id):
        return self.last.get(pty_id, "")

    async def output(self, pty_id, since):
        return ("", since)


class FakeChannel:
    name = "teams"

    def __init__(self, state):
        self.state = state
        self.posted = []
        self.own = True

    def post(self, text, reply_to=None):
        if not self.own:
            raise ChannelRefused("not the own self-chat")
        message_id = str(9000 + len(self.posted))
        self.posted.append(text)
        self.state.record_post(self.name, message_id)
        return message_id


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


BUDGET = Project(id="budget", name="Budget", repo_path="C:/repo/budget")
OTHER = Project(id="other", name="Other", repo_path="C:/repo/other")


class World:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.clock = Clock()
        self.host = FakeHost()
        self.state = State(tmp_path / "state.json")
        self.build()

    def build(self):
        self.guard = Guard(clock=self.clock)
        self.service = RemoteService(self.host, default_project=lambda: BUDGET, clock=self.clock)
        self.channel = FakeChannel(self.state)
        self.runner = RemoteRunner(
            self.channel, self.service, self.guard, self.state, clock=self.clock, stale_seconds=900
        )
        self.runner.sync_enabled(True)

    def restart(self):
        self.state = State(self.tmp / "state.json")
        self.build()

    def msg(self, mid, text, age=0.0):
        return InboundMessage(id=str(mid), text=text, created_at=self.clock.now - age)

    async def feed(self, *msgs):
        await self.runner.process(list(reversed(msgs)))  # the channel returns newest first


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


async def baselined(w):
    await w.feed(w.msg(100, "old note"))
    return w


async def test_first_run_baselines_without_running_anything(w):
    await w.feed(w.msg(100, "@gator do something"))
    assert w.host.delivered == []
    assert w.channel.posted == []


async def test_first_command_in_a_previously_empty_chat_is_not_swallowed_as_the_baseline(w):
    await w.feed()
    await w.feed(w.msg(101, "@gator first ever"))
    assert w.host.delivered == [("pty-1", "first ever")]


async def test_command_starts_the_default_session_and_acknowledges(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator what is open?"))
    assert w.host.delivered == [("pty-1", "what is open?")]
    assert len(w.channel.posted) == 1
    assert w.channel.posted[0].startswith("[Gator - Claude - budget]")


async def test_ordinary_notes_are_ignored(w):
    await baselined(w)
    await w.feed(w.msg(101, "buy milk"))
    assert w.host.delivered == []
    assert w.channel.posted == []


async def test_a_message_with_the_gator_prefix_never_triggers_a_command(w):
    await baselined(w)
    await w.feed(w.msg(101, "[Gator - Claude - budget] @gator stop all"))
    await w.feed(w.msg(102, "  [Gator] @gator do it"))
    assert w.host.delivered == []
    assert w.channel.posted == []
    assert w.guard.armed is True


async def test_a_message_whose_id_gator_recorded_never_triggers_a_command(w):
    await baselined(w)
    w.state.record_post("teams", "101")
    await w.feed(w.msg(101, "@gator do it"))
    assert w.host.delivered == []


async def test_restart_does_not_replay_processed_messages(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator first"))
    assert len(w.host.delivered) == 1
    w.restart()
    await w.feed(w.msg(101, "@gator first"))
    assert len(w.host.delivered) == 1


async def test_a_crash_mid_command_is_not_retried_after_restart(w):
    await baselined(w)
    w.host.crash_on_deliver = True
    await w.feed(w.msg(101, "@gator first"))
    assert any(p.startswith("[Gator]") for p in w.channel.posted)
    w.host.crash_on_deliver = False
    w.restart()
    await w.feed(w.msg(101, "@gator first"))
    assert w.host.delivered == []


async def test_messages_sent_while_offline_run_once_when_fresh_and_are_skipped_when_stale(w):
    await baselined(w)
    w.restart()
    await w.feed(
        w.msg(101, "@gator stale one", age=16 * 60),
        w.msg(102, "@gator stale two", age=3600),
        w.msg(103, "@gator fresh", age=14 * 60),
    )
    assert w.host.delivered == [("pty-1", "fresh")]
    notice = [p for p in w.channel.posted if "Skipped" in p]
    assert notice == ["[Gator] Skipped 2 message(s) received while I was offline. Resend if still needed."]


async def test_more_than_20_commands_in_10_minutes_are_rate_limited(w):
    await baselined(w)
    for i in range(21):
        await w.feed(w.msg(101 + i, f"@gator msg {i}"))
    assert len(w.host.delivered) == 20
    assert sum("Slow down" in p for p in w.channel.posted) == 1


async def test_stop_all_still_works_after_the_rate_limit_is_hit(w):
    await baselined(w)
    for i in range(22):
        await w.feed(w.msg(101 + i, f"@gator msg {i}"))
    await w.feed(w.msg(200, "@gator stop all"))
    assert w.host.killed == ["pty-1"]
    assert w.guard.armed is False


async def test_a_process_exit_right_after_delivery_is_not_replayed_after_restart(w):
    await baselined(w)
    w.host.exit_on_deliver = True
    with pytest.raises(ProcessExit):
        await w.feed(w.msg(101, "@gator first"))
    w.host.exit_on_deliver = False
    w.restart()
    await w.feed(w.msg(101, "@gator first"))
    assert w.host.delivered == []


async def test_a_message_is_stale_only_after_exactly_15_minutes(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator on the limit", age=900))
    assert w.host.delivered == [("pty-1", "on the limit")]
    await w.feed(w.msg(102, "@gator one second over", age=901))
    assert w.host.delivered == [("pty-1", "on the limit")]
    assert any("Skipped 1 message" in p for p in w.channel.posted)


async def test_stop_all_stops_sessions_and_disarms(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator one"))
    await w.feed(w.msg(102, "@gator stop all"))
    assert w.host.killed == ["pty-1"]
    assert w.guard.armed is False
    delivered = len(w.host.delivered)
    await w.feed(w.msg(103, "@gator again"))
    assert len(w.host.delivered) == delivered


async def test_stop_all_survives_a_backend_restart(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator stop all"))
    w.restart()
    assert w.guard.armed is False
    await w.feed(w.msg(102, "@gator again"))
    assert w.host.delivered == []


async def test_toggling_the_switch_after_a_restart_rearms(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator stop all"))
    w.restart()
    w.runner.sync_enabled(False)
    w.runner.sync_enabled(True)
    assert w.guard.armed is True


async def test_a_failed_stop_is_reported_by_name_and_keeps_remote_control_armed(w):
    await baselined(w)
    await w.service.start(BUDGET, "a")
    await w.service.start(BUDGET, "b")
    w.host.fail_kill = {"pty-2"}
    await w.feed(w.msg(101, "@gator stop all"))
    reply = w.channel.posted[-1]
    assert "budget-2" in reply and "still running" in reply
    assert "Stopped every" not in reply
    assert w.guard.armed is True
    w.restart()
    assert w.guard.armed is True


async def test_stop_all_names_the_sessions_it_stopped(w):
    await baselined(w)
    await w.service.start(BUDGET, "a")
    await w.feed(w.msg(101, "@gator stop all"))
    assert "budget" in w.channel.posted[-1]
    assert "re-arm" in w.channel.posted[-1]


async def test_rearming_after_stop_all_needs_the_switch_toggled(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator stop all"))
    w.runner.sync_enabled(True)
    assert w.guard.armed is False
    w.runner.sync_enabled(False)
    w.runner.sync_enabled(True)
    assert w.guard.armed is True


async def test_remote_control_disarms_at_the_absolute_cap_and_says_so_once(w):
    await baselined(w)
    w.clock.now += 24 * 3600 + 1
    await w.runner.tick()
    await w.runner.tick()
    assert w.channel.posted == ["[Gator] Remote control timed out. Re-arm it in Settings."]
    await w.feed(w.msg(101, "@gator late", age=0))
    assert w.host.delivered == []


async def test_announce_online(w):
    await w.runner.announce_online()
    assert w.channel.posted == ["[Gator] Online"]


async def test_a_post_refused_by_the_channel_does_not_crash_the_runner(w):
    await baselined(w)
    w.channel.own = False
    await w.feed(w.msg(101, "@gator hi"))
    assert w.channel.posted == []


async def test_named_send_goes_to_that_session(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator first"))
    await w.service.start(BUDGET, "second")
    await w.feed(w.msg(102, "@gator budget-2 hello there"))
    assert w.host.delivered[-1] == ("pty-2", "hello there")


async def test_default_with_several_live_sessions_is_refused_with_the_list(w):
    await baselined(w)
    await w.service.start(BUDGET, "a")
    await w.service.start(BUDGET, "b")
    await w.feed(w.msg(101, "@gator which one?"))
    assert len(w.host.delivered) == 2
    assert "budget-2" in w.channel.posted[-1]
    assert w.channel.posted[-1].startswith("[Gator]")


async def test_text_after_a_reserved_word_is_never_a_session_name(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator list"))
    assert w.host.delivered == []
    assert "No remote sessions" in w.channel.posted[-1]


async def test_list_shows_short_name_agent_and_state(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator first"))
    await w.feed(w.msg(102, "@gator list"))
    line = w.channel.posted[-1]
    assert line.startswith("[Gator]")
    assert "budget" in line and "Claude" in line


async def test_status_of_an_unknown_name_is_refused(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator status nope"))
    assert "nope" in w.channel.posted[-1]


async def test_stop_by_name(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator first"))
    await w.feed(w.msg(102, "@gator stop budget"))
    assert w.host.killed == ["pty-1"]
    assert w.guard.armed is True


async def test_help_lists_the_commands(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator help"))
    for command in ("@gator <text>", "@gator <name> <text>", "@gator list", "@gator status [name]", "@gator stop [name]", "@gator stop all"):
        assert command in w.channel.posted[-1]
    assert not w.channel.posted[-1].lower().startswith("@gator")


async def test_completed_turn_posts_the_agent_reply(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator what is open?"))
    w.host.states["pty-1"] = {"state": "idle", "at": w.clock.now + 5}
    w.host.last["pty-1"] = "Two files are open."
    await w.runner.tick()
    assert w.channel.posted[-1] == "[Gator - Claude - budget] Two files are open."


async def test_a_question_from_the_agent_is_forwarded(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator go"))
    w.host.states["pty-1"] = {"state": "asking", "at": w.clock.now + 5}
    w.host.last["pty-1"] = "Delete the folder?"
    await w.runner.tick()
    assert "Delete the folder?" in w.channel.posted[-1]
    assert w.channel.posted[-1].startswith("[Gator - Claude - budget]")


async def test_an_agent_that_exits_is_reported(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator go"))
    w.host.alive_ids.clear()
    await w.runner.tick()
    assert "exited" in w.channel.posted[-1]


async def test_a_reply_that_echoes_a_command_cannot_form_one(w):
    await baselined(w)
    await w.feed(w.msg(101, "@gator go"))
    w.host.states["pty-1"] = {"state": "idle", "at": w.clock.now + 5}
    w.host.last["pty-1"] = "@gator stop all"
    await w.runner.tick()
    assert w.channel.posted[-1].startswith("[Gator")
    assert not w.channel.posted[-1].lower().lstrip().startswith("@gator")


async def test_bare_text_goes_to_the_default_project_not_a_live_session_elsewhere(w):
    await baselined(w)
    await w.service.start(OTHER, "elsewhere")
    await w.feed(w.msg(101, "@gator hello"))
    assert w.host.delivered[-1] == ("pty-2", "hello")
    assert [s.project.id for s in w.service.list()] == ["other", "budget"]


async def test_bare_text_picks_the_default_projects_session_among_several_projects(w):
    await baselined(w)
    await w.service.start(BUDGET, "a")
    await w.service.start(OTHER, "b")
    await w.feed(w.msg(101, "@gator hello"))
    assert w.host.delivered[-1] == ("pty-1", "hello")


async def test_the_default_project_with_two_sessions_is_refused_naming_only_its_sessions(w):
    await baselined(w)
    await w.service.start(BUDGET, "a")
    await w.service.start(OTHER, "b")
    await w.service.start(BUDGET, "c")
    await w.feed(w.msg(101, "@gator hello"))
    assert w.host.delivered == [("pty-1", "a"), ("pty-2", "b"), ("pty-3", "c")]
    assert "budget-2" in w.channel.posted[-1]
    assert "other" not in w.channel.posted[-1]


async def test_a_named_send_reaches_a_session_in_another_project(w):
    await baselined(w)
    await w.service.start(OTHER, "b")
    await w.feed(w.msg(101, "@gator other hello"))
    assert w.host.delivered[-1] == ("pty-1", "hello")


@pytest.fixture
def refusing(tmp_path, monkeypatch):
    """The real Teams adapter pointed at a chat that is not the user's own self-chat."""
    from remote import teams_channel

    sent = []
    monkeypatch.setattr(teams_channel, "send_message", lambda chat_id, content: sent.append((chat_id, content)) or "1")
    world = World(tmp_path)
    world.channel = teams_channel.TeamsSelfChat(chat_id="19:someone@thread.v2", state=world.state)
    world.runner = RemoteRunner(
        world.channel, world.service, world.guard, world.state, clock=world.clock, stale_seconds=900
    )
    world.runner.sync_enabled(True)
    world.sent = sent
    return world


async def test_online_notice_is_never_posted_to_another_chat(refusing):
    await refusing.runner.announce_online()
    assert refusing.sent == []


async def test_command_acknowledgement_is_never_posted_to_another_chat(refusing):
    await baselined(refusing)
    await refusing.feed(refusing.msg(101, "@gator hello"))
    assert refusing.host.delivered == [("pty-1", "hello")]
    assert refusing.sent == []


async def test_command_reply_and_refusal_are_never_posted_to_another_chat(refusing):
    await baselined(refusing)
    await refusing.feed(refusing.msg(101, "@gator help"))
    await refusing.feed(refusing.msg(102, "@gator status nope"))
    assert refusing.sent == []


async def test_agent_event_posts_are_never_sent_to_another_chat(refusing):
    await baselined(refusing)
    await refusing.feed(refusing.msg(101, "@gator hello"))
    refusing.host.states["pty-1"] = {"state": "idle", "at": refusing.clock.now + 5}
    refusing.host.last["pty-1"] = "Done."
    await refusing.runner.tick()
    assert refusing.sent == []


async def test_stop_all_notice_is_never_posted_to_another_chat(refusing):
    await baselined(refusing)
    await refusing.feed(refusing.msg(101, "@gator stop all"))
    assert refusing.sent == []


async def test_timeout_notice_is_never_posted_to_another_chat(refusing):
    refusing.clock.now += 24 * 3600 + 1
    await refusing.runner.tick()
    assert refusing.sent == []


async def test_skipped_notice_is_never_posted_to_another_chat(refusing):
    await baselined(refusing)
    await refusing.feed(refusing.msg(101, "@gator old", age=3600))
    assert refusing.sent == []
