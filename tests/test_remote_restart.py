"""Remote sessions outlive a backend restart: the table is rebuilt from the host's labels."""

import pytest

from remote import loop as remote_loop
from remote.guard import Guard
from remote.loop import RemoteLoop
from remote.runner import RemoteRunner
from remote.service import RemoteService
from remote.session_host import HostError, LocalPtyHost, Project, RestoredSession
from remote.state import State
from routes import terminal
from tests.test_remote_runner import BUDGET, Clock, FakeChannel, FakeHost, World


class LabelledHost(FakeHost):
    """A host that keeps what it was given at spawn, as the PTY host keeps labels."""

    def __init__(self):
        super().__init__()
        self.held = {}

    async def spawn(self, project, labels=None):
        session = await super().spawn(project, labels)
        self.held[session.pty_id] = (project, labels, session.vendor_session_id)
        return session

    async def restore(self, channel):
        if self.restore_fails:
            raise HostError("The terminal host did not answer.")
        return [
            RestoredSession(pty, project, labels["remote_short"], vendor, float(labels["remote_created"]))
            for pty, (project, labels, vendor) in self.held.items()
            if pty in self.alive_ids and labels["remote_channel"] == channel
        ]


class Restartable(World):
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.clock = Clock()
        self.host = LabelledHost()
        self.state = State(tmp_path / "state.json")
        self.build()

    def build(self):
        self.guard = Guard(clock=self.clock)
        self.service = RemoteService(
            self.host, default_project=lambda: BUDGET, clock=self.clock, channel="teams"
        )
        self.channel = FakeChannel(self.state)
        self.runner = RemoteRunner(self.channel, self.service, self.guard, self.state, clock=self.clock, stale_seconds=900)
        self.runner.sync_enabled(True)


@pytest.fixture
def w(tmp_path):
    return Restartable(tmp_path)


async def test_a_session_survives_a_restart_with_its_name_and_takes_a_named_send(w):
    await w.feed(w.msg(100, "old note"))
    await w.feed(w.msg(101, "@gator first task"))
    w.service._sessions.clear()
    w.restart()
    await w.runner.restore()
    await w.feed(w.msg(103, "@gator list"))
    assert "- budget (Claude, Budget) idle" in w.channel.posted[-1]
    await w.feed(w.msg(104, "@gator budget follow up"))
    assert w.host.delivered[-1] == ("pty-1", "follow up")
    assert w.host.n == 1


async def test_a_restored_session_keeps_its_stable_name_when_an_earlier_one_was_stopped(w):
    session_a = await w.service.start(BUDGET, "a")
    session_b = await w.service.start(BUDGET, "b")
    assert session_b.short == "budget-2"
    await w.service.stop(session_a.id)
    w.restart()
    await w.service.restore()
    assert [s.short for s in w.service.list()] == ["budget-2"]
    assert w.service.resolve("budget-2").pty_id == session_b.pty_id
    assert w.service.resolve("budget-2").vendor_session_id == "vendor-2"


async def test_sessions_that_are_done_are_not_restored(w):
    session = await w.service.start(BUDGET, "a")
    w.host.alive_ids.discard(session.pty_id)
    w.restart()
    await w.service.restore()
    assert w.service.list() == []


async def test_spawn_carries_the_labels_a_restart_needs(w):
    session = await w.service.start(BUDGET, "a")
    labels = w.host.spawn_labels[-1]
    assert labels["remote_channel"] == "teams"
    assert labels["remote_short"] == session.short
    assert float(labels["remote_created"]) == session.created_at


async def test_a_plain_message_after_a_restart_reaches_the_live_session_not_a_second_one(w):
    await w.feed(w.msg(100, "old note"))
    await w.feed(w.msg(101, "@gator first task"))
    w.restart()
    await w.runner.restore()
    await w.feed(w.msg(102, "@gator second task"))
    assert w.host.n == 1
    assert w.host.delivered[-1] == ("pty-1", "second task")


async def test_restore_refuses_when_the_host_does_not_answer(w):
    w.host.restore_fails = True
    with pytest.raises(Exception) as err:
        await w.service.restore()
    assert "did not answer" in str(err.value)


async def test_commands_wait_until_the_sessions_are_known(w):
    loop = RemoteLoop(w.runner, lambda: True, clock=w.clock, poll_every=0)
    polls = []

    async def poll():
        polls.append(1)

    w.runner.poll = poll
    w.host.restore_fails = True
    await loop.step()
    await loop.step()
    assert polls == []
    w.host.restore_fails = False
    await loop.step()
    assert polls == [1]


class _Terminal:
    def __init__(self, listed=None, unreachable=False):
        self.listed, self.unreachable = listed or [], unreachable

    def host_sessions(self):
        if self.unreachable:
            raise terminal.pty_client.HostError("down")
        return self.listed


def _pinned(pty, channel="teams", **extra):
    meta = {
        "project_id": "Budget",
        "agent": "claude",
        "remote_pinned": "1",
        "remote_channel": channel,
        "remote_short": "budget",
        "remote_created": "1234.5",
        "session_id": "vendor-9",
        **extra,
    }
    return {"id": pty, "meta": meta}


async def test_local_host_restores_only_this_channels_live_pinned_sessions(monkeypatch):
    from skills.code_agent import projects

    listed = [
        _pinned("mine"),
        _pinned("slack-one", channel="slack"),
        {**_pinned("finished"), "done": True},
        {"id": "ordinary", "meta": {"project_id": "Budget", "agent": "claude"}},
        _pinned("no-project", project_id="Gone"),
        _pinned("no-name", remote_short=""),
    ]
    monkeypatch.setattr(terminal, "host_sessions", lambda: listed)
    monkeypatch.setattr(
        projects, "get_project", lambda name: {"name": name, "repo_path": "C:/repo/b"} if name == "Budget" else None
    )
    restored = await LocalPtyHost().restore("teams")
    assert [(r.pty_id, r.short, r.vendor_session_id, r.created_at) for r in restored] == [("mine", "budget", "vendor-9", 1234.5)]
    assert restored[0].project == Project(id="Budget", name="Budget", repo_path="C:/repo/b", agent="claude")


async def test_local_host_reports_an_unreachable_host_as_an_error(monkeypatch):
    monkeypatch.setattr(terminal, "host_sessions", _Terminal(unreachable=True).host_sessions)
    with pytest.raises(HostError):
        await LocalPtyHost().restore("teams")


async def test_the_last_message_of_a_restored_session_is_read_from_the_host_labels(monkeypatch):
    import agent_handoff
    import agent_sessions
    from skills.code_agent import projects

    monkeypatch.setattr(terminal, "_pty_sessions", {"pty-1": type("Adopted", (), {"meta": None})()})
    monkeypatch.setattr(terminal, "host_session_labels", lambda sid, strict=False: _pinned(sid)["meta"])
    monkeypatch.setattr(projects, "get_project", lambda name: {"repo_path": "C:/repo/b"})
    monkeypatch.setattr(agent_sessions, "find_session", lambda repo, agent, sid: object())
    monkeypatch.setattr(agent_sessions, "_transcript_messages", lambda rec: [("assistant", "all done")])
    monkeypatch.setattr(agent_handoff, "_configured_api_keys", lambda: [])
    assert await LocalPtyHost().last_message("pty-1") == "all done"


def test_remote_loop_keeps_one_service_per_channel_named_for_it(tmp_path):
    loops = remote_loop.build_loops(State(tmp_path / "s.json"))
    assert [loop._runner._service._channel for loop in loops] == ["teams", "slack"]


def test_a_running_host_that_does_not_answer_is_unreachable_not_empty(monkeypatch):
    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(terminal.pty_client, "instance_key", lambda: "k")
    monkeypatch.setattr(terminal.pty_client, "find_host", lambda key: None)
    monkeypatch.setattr(terminal.pty_client, "host_alive_but_unreachable", lambda key: True)
    with pytest.raises(terminal.pty_client.HostError):
        terminal.host_sessions()
    assert terminal._list_host_sessions() == []


def test_a_stale_host_file_or_no_host_holds_no_sessions(monkeypatch):
    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(terminal.pty_client, "instance_key", lambda: "k")
    monkeypatch.setattr(terminal.pty_client, "find_host", lambda key: None)
    monkeypatch.setattr(terminal.pty_client, "host_alive_but_unreachable", lambda key: False)
    assert terminal.host_sessions() == []
