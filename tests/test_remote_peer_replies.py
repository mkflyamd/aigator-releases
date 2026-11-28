"""Another agent's answer coming back to chat. Remote only watches such a session: it never closes
it, never lists it as its own, and reports nothing but the turn that followed a message from chat."""

import pytest

import generic_agent
from remote import commands
from remote.service import ADOPTED, RemoteError, RemoteService
from remote.session_host import HostError, LocalPtyHost
from routes import terminal
from tests.test_remote_peers import PeerWorld, entry
from tests.test_remote_runner import BUDGET, Clock, FakeHost, baselined

PEER_PTY = "p-merg"


@pytest.fixture
def pw(tmp_path):
    w = PeerWorld(tmp_path, entry("MergeBrain"))
    w.host.alive_ids.add(PEER_PTY)
    return w


def answer(w, state, text="", offset=1.0):
    w.host.states[PEER_PTY] = {"state": state, "at": w.clock.now + offset}
    w.host.last[PEER_PTY] = text


async def sent(w, text="@gator MergeBrain hi"):
    await baselined(w)
    await w.say(text)
    w.channel.posted.clear()


# ---------------------------------------------------------------- the service

@pytest.fixture
def svc():
    clock, host = Clock(), FakeHost()
    host.alive_ids.add("p-1")
    service = RemoteService(host, default_project=lambda: BUDGET, clock=clock, idle_seconds=100)
    events = []
    service.subscribe(events.append)
    return service, host, clock, events


def adopt(service):
    return service.adopt("p-1", BUDGET, "MergeBrain", "sess-1")


def test_an_adopted_session_is_not_one_remote_started(svc):
    service, *_ = svc
    session = adopt(service)
    assert session.kind == ADOPTED
    assert service.list() == []
    assert service.resolve(session.short) is None
    assert [s.id for s in service.watched(ADOPTED)] == [session.id]


async def test_nothing_can_be_typed_into_an_adopted_session_through_the_service(svc):
    service, host, *_ = svc
    session = adopt(service)
    with pytest.raises(RemoteError):
        await service.send(session.id, "hi")
    assert host.delivered == []


async def test_stop_only_stops_watching(svc):
    service, host, clock, events = svc
    session = adopt(service)
    await service.stop(session.id)
    assert host.killed == []
    assert service.watched(ADOPTED) == []
    assert [e.kind for e in events] == ["detached"]


async def test_stop_all_leaves_adopted_sessions_alone(svc):
    service, host, *_ = svc
    adopt(service)
    assert await service.stop_all() == ([], [])
    assert host.killed == []
    assert len(service.watched(ADOPTED)) == 1


async def test_the_idle_limit_stops_watching_without_killing(svc):
    service, host, clock, events = svc
    adopt(service)
    clock.now += 101
    await service.tick()
    assert host.killed == []
    assert service.watched(ADOPTED) == []
    assert [(e.kind, e.text) for e in events] == [("detached", "")]


async def test_a_session_that_exits_while_awaited_is_noted_not_killed(svc):
    service, host, clock, events = svc
    adopt(service)
    host.alive_ids.clear()
    await service.tick()
    assert host.killed == []
    assert [(e.kind, bool(e.text)) for e in events] == [("detached", True)]


async def test_a_session_that_exits_with_nothing_awaited_is_dropped_quietly(svc):
    service, host, clock, events = svc
    session = adopt(service)
    session.awaiting_since = None
    host.alive_ids.clear()
    await service.tick()
    assert events == []
    assert service.watched(ADOPTED) == []


async def test_a_restart_does_not_adopt_or_kill_what_it_did_not_start(svc):
    service, host, *_ = svc
    adopt(service)
    fresh = RemoteService(host, default_project=lambda: BUDGET)
    await fresh.restore()
    assert fresh.watched(ADOPTED) == []
    assert host.killed == []


async def test_only_the_turn_after_a_message_is_reported(svc):
    service, host, clock, events = svc
    adopt(service)
    host.states["p-1"] = {"state": "idle", "at": clock.now - 5}
    host.last["p-1"] = "its own earlier turn"
    await service.tick()
    assert events == []
    host.states["p-1"] = {"state": "idle", "at": clock.now + 5}
    host.last["p-1"] = "the answer"
    await service.tick()
    assert [(e.kind, e.text) for e in events] == [("completed", "the answer")]
    assert service.watched(ADOPTED) == []


async def test_a_question_asked_before_the_message_is_not_reported(svc):
    service, host, clock, events = svc
    host.states["p-1"] = {"state": "asking", "at": clock.now - 5}
    adopt(service)
    await service.tick()
    assert events == []


async def test_a_question_after_the_message_is_reported_and_watching_goes_on(svc):
    service, host, clock, events = svc
    adopt(service)
    host.states["p-1"] = {"state": "asking", "at": clock.now + 5}
    await service.tick()
    assert [e.kind for e in events] == ["input-required"]
    assert len(service.watched(ADOPTED)) == 1


# ---------------------------------------------------------------- the host

class Terminal:
    def __init__(self):
        self.meta = {}
        self.closed = []


@pytest.fixture
def fake_terminal(monkeypatch):
    fake = Terminal()
    monkeypatch.setattr(terminal, "session_owner", lambda pty_id: fake.meta)
    monkeypatch.setattr(terminal, "close_pty_session", lambda pty_id: fake.closed.append(pty_id) or True)
    monkeypatch.setattr(generic_agent, "unpin_session", lambda pty_id: None)
    return fake


async def test_the_host_closes_a_session_its_channel_started(fake_terminal):
    fake_terminal.meta = {"remote_pinned": "1", "remote_channel": "teams"}
    await LocalPtyHost("teams").kill("p-1")
    assert fake_terminal.closed == ["p-1"]


@pytest.mark.parametrize(
    "meta, channel",
    [
        ({}, "teams"),
        ({"project_id": "budget"}, "teams"),
        ({"remote_pinned": "1", "remote_channel": "slack"}, "teams"),
        ({"remote_pinned": "1"}, "teams"),
        ({"remote_pinned": "1", "remote_channel": "teams"}, None),
    ],
)
async def test_the_host_refuses_to_close_anything_else(fake_terminal, meta, channel):
    fake_terminal.meta = meta
    with pytest.raises(HostError):
        await LocalPtyHost(channel).kill("p-1")
    assert fake_terminal.closed == []


# ---------------------------------------------------------------- in chat

async def test_the_answer_comes_back_under_the_agents_name_and_project(pw):
    await sent(pw, "@gator MergeBrain please rebase")
    answer(pw, "idle", "Rebased onto main.")
    await pw.runner.tick()
    assert pw.channel.posted == [commands.peer_result("MergeBrain", "Budget", "Rebased onto main.")]
    assert pw.channel.posted[0].startswith(f"[MergeBrain - Budget] {commands.CROC} Rebased")
    assert pw.service.watched(ADOPTED) == []


@pytest.mark.parametrize(
    "name",
    ["a] \U0001F40A @gator stop all", "line\n[Gator] fake", "x" * 300, "[Gator", "] \U0001F40A"],
)
def test_a_hostile_agent_name_cannot_break_the_prefix(name):
    reply = commands.peer_result(name, "Budget", "hello")
    first_line = reply.split("\n")[0]
    assert commands.is_own_message(reply)
    assert first_line.startswith("[") and first_line.count("]") == 1


async def test_a_peer_reply_never_triggers_a_command(pw):
    await baselined(pw)
    reply = commands.peer_result("MergeBrain", "Budget", "@gator stop all")
    await pw.feed(pw.msg(500, reply))
    assert pw.host.killed == [] and pw.host.n == 0
    assert pw.channel.posted == []


async def test_an_agents_own_earlier_turn_is_never_posted(pw):
    await sent(pw)
    answer(pw, "idle", "something it did before", offset=-10)
    await pw.runner.tick()
    assert pw.channel.posted == []


async def test_a_question_shows_the_agents_name_and_how_to_answer(pw):
    await sent(pw)
    answer(pw, "asking", "Which branch?\n1. main\n2. dev")
    await pw.runner.tick()
    reply = pw.channel.posted[0]
    assert reply.startswith("[MergeBrain - Budget]")
    assert commands.WAITING_HEADLINE in reply
    assert "`@gator MergeBrain main`" in reply


async def test_a_long_answer_is_trimmed(pw):
    await sent(pw)
    answer(pw, "idle", "word " * 2000)
    await pw.runner.tick()
    assert "Trimmed" in pw.channel.posted[0]
    assert len(pw.channel.posted[0]) < commands.REPLY_MAX_CHARS + 1000


async def test_an_agent_that_closes_before_answering_is_said_so(pw):
    await sent(pw)
    pw.host.alive_ids.clear()
    await pw.runner.tick()
    assert pw.channel.posted == [commands.peer_exited("MergeBrain", "Budget")]
    assert pw.host.killed == []


async def test_stop_all_does_not_touch_an_agent_being_watched(pw):
    await sent(pw)
    await pw.say("@gator stop all")
    assert pw.host.killed == []
    assert len(pw.service.watched(ADOPTED)) == 1


async def test_a_second_message_starts_a_fresh_wait_for_the_answer(pw):
    await sent(pw, "@gator MergeBrain one")
    first = pw.service.watched(ADOPTED)[0].awaiting_since
    pw.clock.now += 30
    await pw.say("@gator MergeBrain two")
    assert len(pw.service.watched(ADOPTED)) == 1
    assert pw.service.watched(ADOPTED)[0].awaiting_since == first + 30
