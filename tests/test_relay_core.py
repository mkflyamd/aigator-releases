"""The relay core: switches, sender stamping, idempotency, hop depth, limits, links, audit."""

import asyncio

import pytest

import agent_suspend
from relay import core, settings
from relay.model import META_KEY, TaskState, chat_endpoint, pty_endpoint
from sandbox import policy as pol

A = pty_endpoint("a", "Alpha", "demo")
B = pty_endpoint("b", "Beta", "demo")
D = pty_endpoint("d", "Delta", "demo")
C = pty_endpoint("c", "Gamma", "other")
REJECTED = TaskState.REJECTED.value
FAILED = TaskState.FAILED.value
WORKING = TaskState.WORKING.value
CANCELED = TaskState.CANCELED.value


class FakeAdapter:
    kind = "pty"

    def __init__(self, endpoints, *, leaky=False):
        self.endpoints = list(endpoints)
        self.leaky = leaky
        self.delivered = []
        self.gate = None
        self.error = None

    async def resolve(self, ref, sender, *, allow_cross_project):
        found = [e for e in self.endpoints if ref in (e.id, e.name)]
        if allow_cross_project or self.leaky:
            return found
        return [e for e in found if e.project_id == sender.project_id]

    async def deliver(self, sender, target, text, mode):
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        self.delivered.append((sender.id, target.id, text, mode))
        return "submitted"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_suspend, "STATE_FILE", tmp_path / "suspended-agents.json")
    monkeypatch.setattr(pol, "policy_path", lambda: tmp_path / "sandbox-policy.json")
    monkeypatch.setattr(pol, "_is_posix", lambda: False)
    pol._reset_cache()
    now = [1_000_000.0]
    audit = []
    adapter = FakeAdapter([A, B, D, C])
    relay = core.Relay(clock=lambda: now[0], audit=audit.append)
    relay.register(adapter)
    return type("World", (), {"relay": relay, "adapter": adapter, "now": now, "audit": audit, "tmp": tmp_path})()


def code_of(task):
    return task["metadata"][META_KEY]["code"]


def state_of(task):
    return task["status"]["state"]


async def test_message_comes_back_as_an_a2a_task(world):
    task = await world.relay.submit(A, "Beta", "Hello", message_id="m1")
    assert state_of(task) == WORKING
    assert task["contextId"].startswith("pair:")
    message = task["history"][0]
    assert message["messageId"] == "m1"
    assert message["role"] == "ROLE_USER"
    assert message["parts"] == [{"text": "Hello"}]
    meta = task["metadata"][META_KEY]
    assert meta["sender"]["id"] == A.id
    assert meta["target"]["id"] == B.id
    assert meta["delivery"] == "submitted"
    assert world.adapter.delivered == [(A.id, B.id, "Hello", core.SUBMIT)]
    assert world.relay.task(task["id"]) == task


async def test_same_message_id_is_delivered_once(world):
    first = await world.relay.submit(A, "Beta", "Hello", message_id="m1")
    again = await world.relay.submit(A, "Beta", "Hello", message_id="m1")
    assert again["id"] == first["id"]
    assert len(world.adapter.delivered) == 1


async def test_admin_lock_wins_over_the_user_switch(world):
    (world.tmp / "sandbox-policy.json").write_text('{"agent_messaging": "deny"}')
    settings.set_user_messaging(True)
    task = await world.relay.submit(A, "Beta", "Hello")
    assert state_of(task) == REJECTED and code_of(task) == "admin_denied"
    assert world.adapter.delivered == []


async def test_user_switch_off_refuses(world):
    settings.set_user_messaging(False)
    task = await world.relay.submit(A, "Beta", "Hello")
    assert state_of(task) == REJECTED and code_of(task) == "switched_off"
    assert world.adapter.delivered == []


async def test_opted_out_target_refuses(world):
    settings.set_opted_out(B.id, True)
    task = await world.relay.submit(A, "Beta", "Hello")
    assert state_of(task) == REJECTED and code_of(task) == "opted_out"
    assert world.adapter.delivered == []


@pytest.mark.parametrize("text", ["", "   ", "x" * 5000])
async def test_empty_and_oversized_messages_are_refused(world, text):
    task = await world.relay.submit(A, "Beta", text)
    assert state_of(task) == REJECTED and code_of(task) == "invalid"


async def test_an_agent_cannot_message_itself(world):
    task = await world.relay.submit(A, "Alpha", "Hello")
    assert state_of(task) == REJECTED and code_of(task) == "invalid"


async def test_other_project_is_not_found_without_a_link(world):
    task = await world.relay.submit(A, "Gamma", "Hello")
    assert state_of(task) == FAILED and code_of(task) == "not_found"
    assert world.adapter.delivered == []


async def test_core_refuses_cross_project_even_if_an_adapter_leaks_it(world):
    world.adapter.leaky = True
    task = await world.relay.submit(A, "Gamma", "Hello")
    assert state_of(task) == REJECTED and code_of(task) == "cross_project"
    assert world.adapter.delivered == []


async def test_a_link_may_cross_projects(world):
    link = world.relay.create_link(A, C)
    task = await world.relay.send_on_link(link.id, A, "Hello")
    assert state_of(task) == WORKING
    assert task["contextId"] == f"link:{link.id}"
    assert world.adapter.delivered == [(A.id, C.id, "Hello", core.SUBMIT)]


async def test_two_agents_with_one_name_are_ambiguous(world):
    twin = pty_endpoint("b2", "Beta", "demo")
    world.adapter.endpoints.append(twin)
    task = await world.relay.submit(A, "Beta", "Hello")
    assert state_of(task) == FAILED and code_of(task) == "ambiguous"
    ids = {c["id"] for c in task["metadata"][META_KEY]["candidates"]}
    assert ids == {B.id, twin.id}


async def test_a_target_kind_with_no_adapter_fails(world):
    tab = chat_endpoint("t1", "Chat", "demo")
    link = world.relay.create_link(A, tab)
    task = await world.relay.send_on_link(link.id, A, "Hello")
    assert state_of(task) == FAILED and code_of(task) == "no_adapter"


async def test_unlinked_agent_is_limited_to_five_an_hour(world):
    for i in range(core.UNLINKED_LIMIT):
        assert state_of(await world.relay.submit(A, "Beta", f"m{i}")) == WORKING
    refused = await world.relay.submit(A, "Beta", "one more")
    assert state_of(refused) == REJECTED and code_of(refused) == "rate_limited"
    world.now[0] += core.HOUR + 1
    assert state_of(await world.relay.submit(A, "Beta", "later")) == WORKING


async def test_refused_messages_do_not_use_up_the_limit(world):
    settings.set_opted_out(B.id, True)
    for i in range(core.UNLINKED_LIMIT + 2):
        await world.relay.submit(A, "Beta", f"m{i}")
    settings.set_opted_out(B.id, False)
    assert state_of(await world.relay.submit(A, "Beta", "now")) == WORKING


async def test_link_hourly_limit_pauses_the_link_until_resumed(world):
    link = world.relay.create_link(A, B)
    for i in range(core.LINK_LIMIT):
        assert state_of(await world.relay.send_on_link(link.id, A, f"m{i}")) == WORKING
    over = await world.relay.send_on_link(link.id, A, "over")
    assert code_of(over) == "limit_reached"
    paused = await world.relay.send_on_link(link.id, A, "while paused")
    assert code_of(paused) == "link_paused"
    assert world.relay.links()[0]["paused"] == "limit_reached"
    world.now[0] += core.HOUR + 1
    assert world.relay.resume_link(link.id)
    assert state_of(await world.relay.send_on_link(link.id, A, "again")) == WORKING


async def test_same_message_over_and_over_pauses_the_link(world):
    link = world.relay.create_link(A, B)
    assert state_of(await world.relay.send_on_link(link.id, A, "ping")) == WORKING
    assert state_of(await world.relay.send_on_link(link.id, A, "ping")) == WORKING
    third = await world.relay.send_on_link(link.id, A, "ping")
    assert code_of(third) == "repeated"
    assert world.relay.links()[0]["paused"] == "repeated"


async def test_back_and_forth_stops_at_the_hop_cap(world):
    link = world.relay.create_link(A, B)
    senders = [A, B]
    for i in range(core.MAX_HOPS):
        task = await world.relay.send_on_link(link.id, senders[i % 2], f"m{i}")
        assert state_of(task) == WORKING
        assert task["metadata"][META_KEY]["hop"] == i + 1
    over = await world.relay.send_on_link(link.id, senders[core.MAX_HOPS % 2], "one too many")
    assert state_of(over) == REJECTED and code_of(over) == "hop_limit"


async def test_one_message_at_a_time_to_a_target(world):
    world.adapter.gate = asyncio.Event()
    first = asyncio.ensure_future(world.relay.submit(A, "Beta", "first"))
    await asyncio.sleep(0)
    second = await world.relay.submit(D, "Beta", "second")
    assert state_of(second) == FAILED and code_of(second) == "busy"
    world.adapter.gate.set()
    assert state_of(await first) == WORKING
    assert state_of(await world.relay.submit(D, "Beta", "third")) == WORKING


async def test_stopping_a_link_cancels_what_is_in_flight(world):
    world.adapter.gate = asyncio.Event()
    link = world.relay.create_link(A, B)
    pending = asyncio.ensure_future(world.relay.send_on_link(link.id, A, "slow"))
    await asyncio.sleep(0)
    assert world.relay.stop_link(link.id)
    result = await pending
    assert state_of(result) == CANCELED
    assert world.adapter.delivered == []
    after = await world.relay.send_on_link(link.id, A, "too late")
    assert code_of(after) == "no_link"
    assert world.relay.links() == []


async def test_stop_all_cancels_in_flight_messages_and_ends_links(world):
    world.adapter.gate = asyncio.Event()
    link = world.relay.create_link(A, B)
    pending = asyncio.ensure_future(world.relay.submit(D, "Beta", "slow"))
    await asyncio.sleep(0)
    world.relay.stop_all()
    assert state_of(await pending) == CANCELED
    assert world.relay.links() == []
    assert code_of(await world.relay.send_on_link(link.id, A, "no")) == "no_link"


async def test_a_link_expires(world):
    link = world.relay.create_link(A, B, seconds=10)
    assert state_of(await world.relay.send_on_link(link.id, A, "in time")) == WORKING
    world.now[0] += 11
    assert code_of(await world.relay.send_on_link(link.id, A, "too late")) == "no_link"
    assert world.relay.links() == []


async def test_a_link_is_capped_at_a_day(world):
    link = world.relay.create_link(A, B, seconds=10 * core.MAX_LINK_SECONDS)
    assert link.expires_at - world.now[0] == core.MAX_LINK_SECONDS


async def test_a_message_on_a_link_cannot_come_from_a_stranger(world):
    link = world.relay.create_link(A, B)
    task = await world.relay.send_on_link(link.id, D, "let me in")
    assert state_of(task) == REJECTED and code_of(task) == "no_link"
    assert world.adapter.delivered == []


@pytest.mark.parametrize(
    "error, state, code",
    [
        (core.Refused("target_busy", "typing", permanent=False), FAILED, "target_busy"),
        (core.Refused("declined", "no", permanent=True), REJECTED, "declined"),
        (RuntimeError("boom"), FAILED, "error"),
    ],
)
async def test_adapter_failures_become_task_states(world, error, state, code):
    world.adapter.error = error
    task = await world.relay.submit(A, "Beta", "Hello")
    assert state_of(task) == state and code_of(task) == code
    assert "boom" not in str(task)


async def test_the_target_can_be_messaged_again_after_a_failure(world):
    world.adapter.error = RuntimeError("boom")
    await world.relay.submit(A, "Beta", "one")
    world.adapter.error = None
    assert state_of(await world.relay.submit(A, "Beta", "two")) == WORKING


async def test_every_message_is_audited_with_a_short_preview(world):
    world.relay.create_link(A, B)
    await world.relay.submit(A, "Beta", "x" * 300)
    await world.relay.submit(A, "Nobody", "Hello")
    events = [line["event"] for line in world.audit]
    assert events == ["link_created", "message", "message"]
    sent = world.audit[1]
    assert sent["state"] == WORKING and len(sent["message"]) == core.PREVIEW_CHARS
    assert world.audit[2]["code"] == "not_found"


def test_audit_file_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_suspend, "STATE_FILE", tmp_path / "suspended-agents.json")
    for i in range(core.AUDIT_KEEP + 5):
        core.write_audit({"n": i})
    lines = core.audit_file().read_text(encoding="utf-8").splitlines()
    assert len(lines) == core.AUDIT_KEEP
    assert lines[-1] == '{"n": %d}' % (core.AUDIT_KEEP + 4)
