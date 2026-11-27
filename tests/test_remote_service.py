import pytest

from remote.guard import Guard
from remote.service import Event, RemoteError, RemoteService
from remote.session_host import HostError, HostSession, Project


class FakeHost:
    def __init__(self):
        self.n = 0
        self.alive_ids = set()
        self.states = {}
        self.last = {}
        self.delivered = []
        self.killed = []
        self.fail_deliver = None
        self.fail_kill = set()

    async def spawn(self, project):
        self.n += 1
        pty = f"pty-{self.n}"
        self.alive_ids.add(pty)
        return HostSession(pty_id=pty, vendor_session_id=f"vendor-{self.n}")

    async def deliver(self, pty_id, text):
        if self.fail_deliver:
            raise HostError(self.fail_deliver)
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
        return ("out", since + 3)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


BUDGET = Project(id="p1", name="Budget", repo_path="C:/repo/budget")


@pytest.fixture
def host():
    return FakeHost()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def svc(host, clock):
    events = []

    async def on_event(ev: Event):
        events.append(ev)

    s = RemoteService(host, default_project=lambda: BUDGET, clock=clock, idle_seconds=8 * 3600)
    s.subscribe(on_event)
    s.events = events
    return s


async def test_start_registers_an_opaque_id_and_keeps_the_vendor_id(svc, host):
    s = await svc.start(BUDGET, "hello")
    assert s.id == "pty:pty-1"
    assert s.vendor_session_id == "vendor-1"
    assert s.short == "budget"
    assert host.delivered == [("pty-1", "hello")]


async def test_second_session_in_a_project_gets_a_numbered_short_name(svc):
    await svc.start(BUDGET, "a")
    second = await svc.start(BUDGET, "b")
    assert second.short == "budget-2"
    assert svc.resolve("budget-2") is second


async def test_send_to_unknown_session_is_refused(svc):
    with pytest.raises(RemoteError):
        await svc.send("pty:nope", "hi")


async def test_send_delivers_text_to_the_pty(svc, host):
    s = await svc.start(BUDGET, "a")
    await svc.send(s.id, "second")
    assert host.delivered[-1] == ("pty-1", "second")


async def test_failed_delivery_surfaces_the_reason(svc, host):
    s = await svc.start(BUDGET, "a")
    host.fail_deliver = "The agent is waiting for the user to answer a permission prompt."
    with pytest.raises(RemoteError, match="permission prompt"):
        await svc.send(s.id, "x")


async def test_completed_event_when_idle_follows_a_send(svc, host, clock):
    s = await svc.start(BUDGET, "a")
    host.states["pty-1"] = {"state": "idle", "at": clock.now - 5}
    await svc.tick()
    assert svc.events == []
    host.states["pty-1"] = {"state": "idle", "at": clock.now + 10}
    host.last["pty-1"] = "All done."
    await svc.tick()
    assert [(e.kind, e.session.id, e.text) for e in svc.events] == [("completed", s.id, "All done.")]
    await svc.tick()
    assert len(svc.events) == 1


async def test_input_required_event_when_the_agent_asks(svc, host, clock):
    await svc.start(BUDGET, "a")
    host.states["pty-1"] = {"state": "asking", "at": clock.now + 1}
    host.last["pty-1"] = "May I run rm?"
    await svc.tick()
    assert [(e.kind, e.text) for e in svc.events] == [("input-required", "May I run rm?")]
    await svc.tick()
    assert len(svc.events) == 1


async def test_failed_event_when_the_process_exits(svc, host):
    s = await svc.start(BUDGET, "a")
    host.alive_ids.clear()
    await svc.tick()
    assert [e.kind for e in svc.events] == ["failed"]
    assert svc.list() == []
    with pytest.raises(RemoteError):
        await svc.send(s.id, "x")


async def test_stop_kills_and_removes_the_session(svc, host):
    s = await svc.start(BUDGET, "a")
    await svc.stop(s.id)
    assert host.killed == ["pty-1"]
    assert svc.list() == []
    assert [e.kind for e in svc.events] == ["canceled"]


async def test_stop_all_stops_every_session(svc, host):
    await svc.start(BUDGET, "a")
    await svc.start(BUDGET, "b")
    stopped, failed = await svc.stop_all()
    assert sorted(host.killed) == ["pty-1", "pty-2"]
    assert svc.list() == []
    assert sorted(s.short for s in stopped) == ["budget", "budget-2"]
    assert failed == []


async def test_stop_all_reports_the_sessions_it_could_not_stop(svc, host):
    await svc.start(BUDGET, "a")
    await svc.start(BUDGET, "b")
    host.fail_kill = {"pty-2"}
    stopped, failed = await svc.stop_all()
    assert [s.short for s in stopped] == ["budget"]
    assert [s.short for s in failed] == ["budget-2"]
    assert [s.short for s in svc.list()] == ["budget-2"]


async def test_a_failed_first_delivery_leaves_no_session_and_kills_the_pty(svc, host):
    host.fail_deliver = "The agent is waiting for the user to answer a permission prompt."
    with pytest.raises(RemoteError, match="permission prompt"):
        await svc.start(BUDGET, "a")
    assert svc.list() == []
    assert host.killed == ["pty-1"]
    assert host.alive_ids == set()


async def test_a_failed_rollback_kill_still_raises_the_delivery_error(svc, host):
    host.fail_deliver = "no prompt reached"
    host.fail_kill = {"pty-1"}
    with pytest.raises(RemoteError, match="no prompt reached"):
        await svc.start(BUDGET, "a")
    assert svc.list() == []


async def test_idle_session_is_stopped_after_the_limit(svc, host, clock):
    await svc.start(BUDGET, "a")
    clock.now += 8 * 3600 + 1
    await svc.tick()
    assert host.killed == ["pty-1"]
    assert [e.kind for e in svc.events] == ["canceled"]


async def test_activity_resets_the_idle_clock(svc, host, clock):
    s = await svc.start(BUDGET, "a")
    clock.now += 7 * 3600
    await svc.send(s.id, "more")
    clock.now += 7 * 3600
    await svc.tick()
    assert host.killed == []


async def test_output_delegates_with_a_cursor(svc):
    s = await svc.start(BUDGET, "a")
    assert await svc.output(s.id, 4) == ("out", 7)
