import pytest

from remote import loop as remote_loop
from remote.guard import Guard
from remote.loop import RemoteLoop
from remote.runner import RemoteRunner
from remote.service import RemoteService
from remote.session_host import Project
from remote.state import State
from tests.test_remote_runner import Clock, FakeChannel, FakeHost


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
        service = RemoteService(FakeHost(), default_project=lambda: Project("p", "P", "C:/p"), clock=self.clock)
        self.runner = RemoteRunner(self.channel, service, self.guard, self.state, clock=self.clock)
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
    s.enabled = True
    await s.loop.step()
    await s.loop.step()
    assert s.guard.armed is True
    assert s.channel.posted == ["[Gator] Online"]


async def test_polls_only_every_poll_interval(s):
    s.enabled = True
    await s.loop.step()
    await s.loop.step()
    assert s.channel.polls == 1
    s.clock.now += 10
    await s.loop.step()
    assert s.channel.polls == 2


async def test_recovery_from_a_failed_poll_says_online_again(s):
    s.enabled = True
    await s.loop.step()
    s.channel.fail = True
    s.clock.now += 10
    await s.loop.step()
    s.clock.now += 10
    await s.loop.step()
    assert s.channel.posted == ["[Gator] Online"]
    s.channel.fail = False
    s.clock.now += 10
    await s.loop.step()
    assert s.channel.posted == ["[Gator] Online", "[Gator] Online"]


async def test_turning_the_switch_off_disarms(s):
    s.enabled = True
    await s.loop.step()
    s.enabled = False
    await s.loop.step()
    assert s.guard.armed is False


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
