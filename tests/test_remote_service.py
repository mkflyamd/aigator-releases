import pytest

from remote import prompts
from remote.guard import Guard
from remote.service import PROMPT_GRACE_SECONDS, Event, PromptGone, PromptRefused, RemoteError, RemoteService
from remote.session_host import HostError, HostSession, Project, StalePrompt


class FakeHost:
    restore_fails = False

    def __init__(self):
        self.n = 0
        self.restorable = []
        self.spawn_labels = []
        self.alive_ids = set()
        self.states = {}
        self.last = {}
        self.prompts = {}
        self.typed = []
        self.delivered = []
        self.killed = []
        self.fail_deliver = None
        self.fail_kill = set()
        self.sleeping_ids = set()
        self.woken = []
        self.wake_error = None
        self.wake_gate = None

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
        self.sleeping_ids.discard(pty_id)

    async def sleeping(self, pty_id):
        return pty_id in self.sleeping_ids

    async def wake(self, pty_id, project, labels):
        self.woken.append((pty_id, project.id, labels))
        if self.wake_gate is not None:
            await self.wake_gate.wait()
        if self.wake_error is not None:
            raise self.wake_error
        self.sleeping_ids.discard(pty_id)
        self.alive_ids.add(pty_id)

    def suspend(self, pty_id):
        self.alive_ids.discard(pty_id)
        self.sleeping_ids.add(pty_id)

    async def state(self, pty_id):
        return self.states.get(pty_id)

    async def last_message(self, pty_id):
        return self.last.get(pty_id, "")

    async def last_step(self, pty_id):
        return getattr(self, "steps", {}).get(pty_id, "")

    async def output(self, pty_id, since):
        return ("out", since + 3)

    async def prompt(self, pty_id):
        return self.prompts.get(pty_id)

    async def answer(self, pty_id, prompt_id, keys, ends_turn=False):
        shown, state = self.prompts.get(pty_id), self.states.get(pty_id)
        if shown is None or shown.id != prompt_id or not state or state["state"] != "asking":
            raise StalePrompt("That prompt is no longer showing.")
        self.typed.append((pty_id, keys))
        del self.prompts[pty_id]
        if ends_turn:
            self.states[pty_id] = {"state": "idle", "at": state["at"] + 1}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


BUDGET = Project(id="p1", name="Budget", repo_path="C:/repo/budget")
OTHER = Project(id="p2", name="Other", repo_path="C:/repo/other")


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


async def test_a_project_has_one_lane_and_a_second_start_is_refused(svc, host):
    first = await svc.start(BUDGET, "a")
    with pytest.raises(RemoteError, match="Already has a session"):
        await svc.start(BUDGET, "b")
    assert host.n == 1
    assert svc.list() == [first]


async def test_two_projects_whose_names_collide_get_numbered_short_names(svc):
    await svc.start(BUDGET, "a")
    clash = await svc.start(Project(id="p9", name="budget", repo_path="C:/repo/b2"), "b")
    assert clash.short == "budget-2"
    assert svc.resolve("budget-2") is clash


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


async def test_idle_written_while_the_prompt_is_still_being_typed_is_not_a_finished_turn(svc, host, clock):
    async def slow_deliver(pty_id, text):
        clock.now += 6
        host.states[pty_id] = {"state": "idle", "at": clock.now}
        clock.now += 2
        host.delivered.append((pty_id, text))

    host.deliver = slow_deliver
    await svc.start(BUDGET, "hello")
    await svc.tick()
    assert svc.events == []
    host.states["pty-1"] = {"state": "idle", "at": clock.now + 20}
    host.last["pty-1"] = "Hello. Here is where things stand."
    await svc.tick()
    assert [(e.kind, e.text) for e in svc.events] == [("completed", "Hello. Here is where things stand.")]


async def test_input_required_event_when_the_agent_asks(svc, host, clock):
    await svc.start(BUDGET, "a")
    host.states["pty-1"] = {"state": "asking", "at": clock.now + 1}
    host.last["pty-1"] = "May I run rm?"
    await svc.tick()
    clock.now += PROMPT_GRACE_SECONDS
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
    await svc.start(OTHER, "b")
    stopped, failed = await svc.stop_all()
    assert sorted(host.killed) == ["pty-1", "pty-2"]
    assert svc.list() == []
    assert sorted(s.short for s in stopped) == ["budget", "other"]
    assert failed == []


async def test_stop_all_reports_the_sessions_it_could_not_stop(svc, host):
    await svc.start(BUDGET, "a")
    await svc.start(OTHER, "b")
    host.fail_kill = {"pty-2"}
    stopped, failed = await svc.stop_all()
    assert [s.short for s in stopped] == ["budget"]
    assert [s.short for s in failed] == ["other"]
    assert [s.short for s in svc.list()] == ["other"]


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


# ---------------------------------------------------------------- permission and question prompts

BASH_CALL = {"tool_name": "Bash", "cwd": "C:/repo/budget", "tool_input": {"command": "echo hi"}}


def _asking(host, clock, payload=BASH_CALL, at=1):
    host.states["pty-1"] = {"state": "asking", "at": clock.now + at}
    host.prompts["pty-1"] = prompts.parse(payload, clock.now + at)
    host.last["pty-1"] = "a transcript line that must not be posted"


async def test_a_prompt_event_carries_the_prompt_and_not_the_transcript(svc, host, clock):
    await svc.start(BUDGET, "a")
    _asking(host, clock)
    await svc.tick()
    [event] = svc.events
    assert event.kind == "input-required" and event.text == ""
    assert event.session.waiting and event.session.prompt is host.prompts["pty-1"]


async def test_an_ask_without_a_prompt_file_still_posts_the_transcript(svc, host, clock):
    await svc.start(BUDGET, "a")
    host.states["pty-1"] = {"state": "asking", "at": clock.now + 1}
    host.last["pty-1"] = "May I run rm?"
    await svc.tick()
    assert svc.events == []
    clock.now += PROMPT_GRACE_SECONDS
    await svc.tick()
    assert [(e.kind, e.text) for e in svc.events] == [("input-required", "May I run rm?")]
    assert svc.list()[0].prompt is None


async def test_an_answer_types_its_keys_and_returns_the_confirmation(svc, host, clock):
    session = await svc.start(BUDGET, "a")
    _asking(host, clock)
    await svc.tick()
    result = await svc.answer(session.id, "allow")
    assert host.typed == [("pty-1", (prompts.ENTER,))]
    assert result.done == "Allowed once." and not result.ends_turn
    assert not session.waiting and session.prompt is None
    assert session.awaiting_since is not None


async def test_a_denied_answer_ends_the_turn_so_no_done_is_posted_later(svc, host, clock):
    session = await svc.start(BUDGET, "a")
    _asking(host, clock)
    await svc.tick()
    result = await svc.answer(session.id, "deny")
    assert result.ends_turn and session.awaiting_since is None
    await svc.tick()
    assert [e.kind for e in svc.events] == ["input-required"]


async def test_a_reply_that_is_not_an_answer_types_nothing_and_keeps_waiting(svc, host, clock):
    session = await svc.start(BUDGET, "a")
    _asking(host, clock)
    await svc.tick()
    with pytest.raises(PromptRefused) as refused:
        await svc.answer(session.id, "sure, go for it")
    assert host.typed == [] and session.waiting and session.prompt is not None
    assert refused.value.prompt is session.prompt


async def test_an_answer_to_a_prompt_that_changed_types_nothing_and_says_gone(svc, host, clock):
    session = await svc.start(BUDGET, "a")
    _asking(host, clock)
    await svc.tick()
    _asking(host, clock, {**BASH_CALL, "tool_input": {"command": "rm -rf build"}}, at=5)
    with pytest.raises(PromptGone):
        await svc.answer(session.id, "allow")
    assert host.typed == [] and not session.waiting and session.prompt is None


async def test_an_answer_after_it_was_answered_locally_says_gone(svc, host, clock):
    session = await svc.start(BUDGET, "a")
    _asking(host, clock)
    await svc.tick()
    host.states["pty-1"] = {"state": "working", "at": clock.now + 2}
    with pytest.raises(PromptGone):
        await svc.answer(session.id, "allow")
    assert host.typed == []


async def test_answering_a_session_that_shows_no_prompt_is_an_error(svc, host):
    session = await svc.start(BUDGET, "a")
    with pytest.raises(RemoteError):
        await svc.answer(session.id, "allow")
    assert host.typed == []


async def test_a_send_clears_the_prompt(svc, host, clock):
    session = await svc.start(BUDGET, "a")
    _asking(host, clock)
    await svc.tick()
    await svc.send(session.id, "something else")
    assert session.prompt is None and not session.waiting
