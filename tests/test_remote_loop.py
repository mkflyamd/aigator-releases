import pytest
from remote import commands

from remote import loop as remote_loop
from remote.guard import Guard
from remote.master import Master
from remote.loop import RemoteLoop
from remote.runner import RemoteRunner
from remote.service import RemoteService
from remote.session_host import Project
from remote.state import State
from tests.test_remote_runner import BUDGET, Clock, FakeChannel, FakeHost


class PollingChannel(FakeChannel):
    def __init__(self, state):
        super().__init__(state)
        self.fail = False
        self.polls = 0

    def poll(self):
        self.polls += 1
        if self.fail:
            raise RuntimeError("token expired")
        return []


class Setup:
    def __init__(self, tmp_path):
        self.clock = Clock()
        self.state = State(tmp_path / "s.json")
        self.channel = PollingChannel(self.state)
        self.guard = Guard(clock=self.clock)
        self.host = FakeHost()
        service = RemoteService(self.host, default_project=lambda: Project("p", "P", "C:/p"), clock=self.clock)
        self.master = Master(self.state, self.clock)
        self.service = service
        self.runner = RemoteRunner(self.channel, service, self.guard, self.state, clock=self.clock, master=self.master)
        self.enabled = False
        self.loop = RemoteLoop(self.runner, lambda: self.enabled, clock=self.clock, poll_every=10.0)


@pytest.fixture
def s(tmp_path):
    return Setup(tmp_path)


async def test_disabled_does_nothing(s):
    await s.loop.step()
    assert s.channel.polls == 0
    assert s.channel.posted == []
    assert s.guard.armed is False


async def test_enabling_arms_polls_and_says_online_once(s):
    s.master.arm()
    s.enabled = True
    await s.loop.step()
    await s.loop.step()
    assert s.guard.armed is True
    assert s.channel.posted == [commands.online()]


async def test_polls_only_every_poll_interval(s):
    s.master.arm()
    s.enabled = True
    await s.loop.step()
    await s.loop.step()
    assert s.channel.polls == 1
    s.clock.now += 10
    await s.loop.step()
    assert s.channel.polls == 2


async def test_a_failed_poll_and_its_recovery_never_say_online_again(s):
    s.master.arm()
    s.enabled = True
    await s.loop.step()
    s.channel.fail = True
    s.clock.now += 10
    await s.loop.step()
    s.channel.fail = False
    s.clock.now += 10
    await s.loop.step()
    assert s.channel.posted == [commands.online()]


async def test_a_restart_with_the_chat_window_open_says_nothing(s):
    s.enabled = True
    s.runner._window.open(s.clock.now)
    assert s.runner._window.is_open()
    await s.loop.step()
    await s.loop.step()
    assert s.channel.posted == []


async def test_turning_the_switch_off_disarms(s):
    s.master.arm()
    s.enabled = True
    await s.loop.step()
    s.enabled = False
    await s.loop.step()
    assert s.guard.armed is False


async def test_a_channel_whose_switch_is_off_still_stops_its_sessions_at_the_deadline(s):
    s.master.arm()
    await s.service.start(BUDGET, "job")
    s.clock.now += 12 * 3600 + 1
    await s.loop.step()
    await s.loop.step()
    assert s.host.killed == ["pty-1"]
    assert s.service.list() == []
    assert s.channel.posted == []


def test_default_project_prefers_the_remote_setting_then_the_active_project(monkeypatch):
    projects = {"a": {"name": "a", "repo_path": "C:/a"}, "b": {"name": "b", "repo_path": "C:/b"}}
    import skills.code_agent.projects as store

    monkeypatch.setattr(store, "get_project", lambda name: projects.get(name))
    monkeypatch.setattr(store, "get_active_project", lambda: "b")
    monkeypatch.setattr(remote_loop, "load_config", lambda: {"remote_default_project": "a"})
    assert remote_loop.default_project() == Project("a", "a", "C:/a")
    monkeypatch.setattr(remote_loop, "load_config", lambda: {})
    assert remote_loop.default_project() == Project("b", "b", "C:/b")
    monkeypatch.setattr(store, "get_active_project", lambda: None)
    assert remote_loop.default_project() is None


def test_the_switch_is_the_existing_teams_remote_control_setting(monkeypatch):
    monkeypatch.setattr(remote_loop, "load_config", lambda: {"teams_remote_control_enabled": True})
    assert remote_loop.teams_switch_on() is True
    monkeypatch.setattr(remote_loop, "load_config", lambda: {})
    assert remote_loop.teams_switch_on() is False


def test_each_channel_has_its_own_switch(monkeypatch):
    config = {"teams_remote_control_enabled": True, "slack_remote_control_enabled": False}
    monkeypatch.setattr(remote_loop, "load_config", lambda: config)
    assert remote_loop.teams_switch_on() is True
    assert remote_loop.slack_switch_on() is False
    config["slack_remote_control_enabled"] = True
    assert remote_loop.slack_switch_on() is True


class SlackPolling(PollingChannel):
    name = "slack"


def test_the_slack_switch_is_an_allowed_config_key():
    from config import PATCHABLE_CONFIG_KEYS

    assert "slack_remote_control_enabled" in PATCHABLE_CONFIG_KEYS


async def test_the_slack_loop_follows_only_the_slack_switch(tmp_path, monkeypatch):
    config = {"teams_remote_control_enabled": True, "slack_remote_control_enabled": False}
    monkeypatch.setattr(remote_loop, "load_config", lambda: config)
    monkeypatch.setattr(remote_loop, "LocalPtyHost", lambda channel: FakeHost())
    channels = {}
    monkeypatch.setattr(remote_loop, "TeamsSelfChat", lambda state: channels.setdefault("teams", PollingChannel(state)))
    monkeypatch.setattr(remote_loop, "SlackSelfDM", lambda state: channels.setdefault("slack", SlackPolling(state)))
    teams_loop, slack_loop = remote_loop.build_loops(State(tmp_path / "s.json"))
    await teams_loop.step()
    await slack_loop.step()
    assert channels["teams"].polls == 1
    assert channels["slack"].polls == 0
    config["slack_remote_control_enabled"] = True
    await slack_loop.step()
    assert channels["slack"].polls == 1


async def test_a_slow_channel_step_does_not_hold_the_other_channel(monkeypatch):
    import asyncio

    release = asyncio.Event()
    steps = {"teams": 0}

    class Blocked:
        async def step(self):
            await release.wait()

    class Quick:
        async def step(self):
            steps["teams"] += 1

    monkeypatch.setattr(remote_loop, "STEP_SECONDS", 0.001)
    monkeypatch.setattr(remote_loop, "build_loops", lambda: [Quick(), Blocked()])
    task = asyncio.create_task(remote_loop.remote_control_loop())
    try:
        for _ in range(200):
            if steps["teams"] >= 3:
                break
            await asyncio.sleep(0.005)
        assert steps["teams"] >= 3
    finally:
        release.set()
        task.cancel()


async def test_switching_off_and_on_again_does_not_say_online_a_second_time(s):
    s.master.arm()
    s.enabled = True
    await s.loop.step()
    s.enabled = False
    await s.loop.step()
    s.enabled = True
    await s.loop.step()
    assert s.channel.posted == [commands.online()]
