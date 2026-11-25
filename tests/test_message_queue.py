"""Messages typed while a turn runs wait in a per-conversation queue and are sent one at a time."""

import asyncio
import json
import os
import sys
import types
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import app as app_module  # noqa: E402
import shared  # noqa: E402
import chat_queue  # noqa: E402
from chat_queue import MAX_QUEUED, MessageQueue, QueueError  # noqa: E402
from routes import chat as chat_routes  # noqa: E402
from security import get_csrf_token  # noqa: E402


@pytest.fixture
def queue(tmp_path):
    q = MessageQueue(tmp_path / "queue.db")
    chat_queue.reset_queue(q)
    yield q
    chat_queue.reset_queue(None)


def _msg(text="hello", images=None):
    payload = {"text": text}
    if images:
        payload["images"] = images
    return payload


def test_messages_come_back_in_the_order_they_were_queued(queue):
    queue.enqueue("c", "a", _msg("first"))
    queue.enqueue("c", "b", _msg("second"))
    assert [i["text"] for i in queue.snapshot("c")["items"]] == ["first", "second"]
    assert queue.head("c")["id"] == "a"


def test_queueing_the_same_id_twice_keeps_one_message(queue):
    assert queue.enqueue("c", "a", _msg())["created"] is True
    assert queue.enqueue("c", "a", _msg())["created"] is False
    assert len(queue.snapshot("c")["items"]) == 1


def test_an_id_cannot_be_reused_by_another_conversation(queue):
    queue.enqueue("c", "a", _msg())
    with pytest.raises(QueueError) as err:
        queue.enqueue("other", "a", _msg())
    assert err.value.status == 409


def test_the_queue_holds_five_messages(queue):
    for n in range(MAX_QUEUED):
        queue.enqueue("c", f"id{n}", _msg(f"m{n}"))
    with pytest.raises(QueueError) as err:
        queue.enqueue("c", "extra", _msg())
    assert err.value.status == 429
    queue.enqueue("another", "id0x", _msg())


def test_empty_and_oversized_messages_are_refused(queue):
    with pytest.raises(QueueError) as err:
        queue.enqueue("c", "a", _msg("   "))
    assert err.value.status == 400
    with pytest.raises(QueueError) as err:
        queue.enqueue("c", "b", _msg("x" * (chat_queue.MAX_TEXT_CHARS + 1)))
    assert err.value.status == 413
    with pytest.raises(QueueError) as err:
        queue.enqueue("c", "d", _msg("see attached", images=["x" * (chat_queue.MAX_ITEM_BYTES + 1)]))
    assert err.value.status == 413


def test_an_image_alone_is_a_message(queue):
    queue.enqueue("c", "a", _msg("", images=["data:image/png;base64,AAAA"]))
    assert queue.snapshot("c")["items"][0]["attachments"] == 1


def test_editing_changes_the_text_that_will_be_sent(queue):
    queue.enqueue("c", "a", _msg("old"))
    queue.edit("c", "a", "new")
    assert queue.head("c")["payload"]["text"] == "new"
    with pytest.raises(QueueError) as err:
        queue.edit("c", "gone", "x")
    assert err.value.status == 409


def test_a_paused_queue_offers_nothing_until_resumed(queue):
    queue.enqueue("c", "a", _msg())
    queue.pause("c", "stopped")
    assert queue.head("c") is None
    snap = queue.snapshot("c")
    assert snap["paused"] is True and snap["reason"] == "stopped"
    queue.resume("c")
    assert queue.head("c")["id"] == "a"


def test_pausing_an_empty_queue_is_a_no_op(queue):
    queue.pause_if_queued("c", "stopped")
    assert queue.snapshot("c")["paused"] is False


def test_removing_the_last_message_clears_the_pause(queue):
    queue.enqueue("c", "a", _msg())
    queue.pause("c", "error")
    queue.remove("c", "a")
    queue.enqueue("c", "b", _msg())
    assert queue.head("c")["id"] == "b"


def test_a_message_is_consumed_once(queue):
    queue.enqueue("c", "a", _msg())
    assert queue.consume("c", "a") is True
    assert queue.consume("c", "a") is False


def test_clear_drops_everything_and_the_pause(queue):
    queue.enqueue("c", "a", _msg())
    queue.pause("c", "stopped")
    queue.clear("c")
    snap = queue.snapshot("c")
    assert snap["items"] == [] and snap["paused"] is False


def test_the_queue_survives_a_restart(tmp_path):
    first = MessageQueue(tmp_path / "queue.db")
    first.enqueue("c", "a", _msg("kept"))
    again = MessageQueue(tmp_path / "queue.db")
    assert again.head("c")["payload"]["text"] == "kept"


def test_a_broken_database_is_reported_not_raised_as_a_crash(tmp_path):
    q = MessageQueue(tmp_path)  # a directory cannot be opened as a database
    with pytest.raises(QueueError) as err:
        q.snapshot("c")
    assert err.value.status == 503
    q.pause_if_queued("c", "stopped")


# ── routes ───────────────────────────────────────────────────────────────────

HOST = "127.0.0.1:8000"


@pytest.fixture
def api(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(chat_routes, "_classify_skills_via_llm", lambda *a, **k: [])
    with TestClient(app_module.app, base_url=f"http://{HOST}") as client:
        client.headers.update({"X-CSRF-Token": get_csrf_token(HOST)})
        yield client


def _hold_turns_open(monkeypatch):
    async def waits_forever(task_id, timeout):
        await asyncio.sleep(1000)

    monkeypatch.setattr(shared.chat_task_store, "wait_for_subscriber", waits_forever)


def test_mutating_queue_routes_need_the_csrf_token(queue, monkeypatch, api):
    client = api
    bare = {"X-CSRF-Token": ""}
    body = {"context_id": "c", "id": "a", "payload": _msg()}
    assert client.post("/api/queue", json=body, headers=bare).status_code == 403
    assert client.put("/api/queue/a", json={"context_id": "c", "text": "x"}, headers=bare).status_code == 403
    assert client.delete("/api/queue/a", params={"context_id": "c"}, headers=bare).status_code == 403
    assert client.post("/api/queue/resume", json={"context_id": "c"}, headers=bare).status_code == 403
    assert client.post("/api/queue/clear", json={"context_id": "c"}, headers=bare).status_code == 403


def test_the_chips_round_trip_through_the_routes(queue, monkeypatch, api):
    client = api
    added = client.post("/api/queue", json={"context_id": "c", "id": "a", "payload": _msg("one")}).json()
    assert [i["id"] for i in added["items"]] == ["a"]
    edited = client.put("/api/queue/a", json={"context_id": "c", "text": "uno"}).json()
    assert edited["items"][0]["text"] == "uno"
    assert client.get("/api/queue/head", params={"context_id": "c"}).json()["item"]["payload"]["text"] == "uno"
    assert client.delete("/api/queue/a", params={"context_id": "c"}).json()["items"] == []


def test_a_full_queue_answers_429_with_a_readable_message(queue, monkeypatch, api):
    client = api
    for n in range(MAX_QUEUED):
        client.post("/api/queue", json={"context_id": "c", "id": f"i{n}", "payload": _msg()})
    full = client.post("/api/queue", json={"context_id": "c", "id": "more", "payload": _msg()})
    assert full.status_code == 429
    assert "full" in full.json()["detail"]


def test_stopping_a_turn_pauses_the_messages_queued_behind_it(queue, monkeypatch, api):
    _hold_turns_open(monkeypatch)
    ctx = f"q-{uuid.uuid4().hex}"
    client = api
    task_id = client.post("/api/chat", json={"message": "hello", "context_id": ctx}).json()["task_id"]
    client.post("/api/queue", json={"context_id": ctx, "id": "a", "payload": _msg("next")})
    assert client.post(f"/api/chat/{task_id}/cancel").json()["cancelled"] is True
    snap = client.get("/api/queue", params={"context_id": ctx}).json()
    assert snap["paused"] is True and snap["reason"] == "stopped"
    assert client.get("/api/queue/head", params={"context_id": ctx}).json()["item"] is None


def test_stopping_with_nothing_queued_leaves_no_pause(queue, monkeypatch, api):
    _hold_turns_open(monkeypatch)
    ctx = f"q-{uuid.uuid4().hex}"
    client = api
    task_id = client.post("/api/chat", json={"message": "hello", "context_id": ctx}).json()["task_id"]
    client.post(f"/api/chat/{task_id}/cancel")
    client.post("/api/queue", json={"context_id": ctx, "id": "a", "payload": _msg("later")})
    assert client.get("/api/queue/head", params={"context_id": ctx}).json()["item"]["id"] == "a"


def test_sending_a_queued_message_starts_a_turn_and_removes_it(queue, monkeypatch, api):
    _hold_turns_open(monkeypatch)
    ctx = f"q-{uuid.uuid4().hex}"
    client = api
    queue.enqueue(ctx, "a", _msg("next"))
    sent = client.post("/api/chat", json={"message": "next", "context_id": ctx, "queued_id": "a"})
    assert sent.status_code == 200
    assert queue.snapshot(ctx)["items"] == []
    client.post(f"/api/chat/{sent.json()['task_id']}/cancel")


def test_a_message_another_window_already_sent_is_not_sent_twice(queue, monkeypatch, api):
    _hold_turns_open(monkeypatch)
    ctx = f"q-{uuid.uuid4().hex}"
    client = api
    again = client.post("/api/chat", json={"message": "next", "context_id": ctx, "queued_id": "a"})
    assert again.status_code == 409
    assert again.json()["error"] == "queue_item_gone"
    assert shared.chat_task_store.active_task_for(ctx) is None


def test_a_refused_send_leaves_the_queue_alone(queue, monkeypatch, api):
    _hold_turns_open(monkeypatch)
    ctx = f"q-{uuid.uuid4().hex}"
    client = api
    first = client.post("/api/chat", json={"message": "hello", "context_id": ctx})
    queue.enqueue(ctx, "a", _msg("next"))
    refused = client.post("/api/chat", json={"message": "next", "context_id": ctx, "queued_id": "a"})
    assert refused.status_code == 409
    assert refused.json()["error"] == "turn_in_progress"
    assert [i["id"] for i in queue.snapshot(ctx)["items"]] == ["a"]
    client.post(f"/api/chat/{first.json()['task_id']}/cancel")


def test_an_unavailable_queue_refuses_the_send_instead_of_dropping_it(tmp_path, monkeypatch, api):
    _hold_turns_open(monkeypatch)
    chat_queue.reset_queue(MessageQueue(tmp_path))
    try:
        client = api
        r = client.post("/api/chat", json={"message": "next", "context_id": f"q-{uuid.uuid4().hex}", "queued_id": "a"})
        assert r.status_code == 503
        assert r.json()["error"] == "queue_unavailable"
    finally:
        chat_queue.reset_queue(None)


async def test_a_failed_turn_pauses_the_queue_only_when_something_is_waiting(queue):
    await chat_routes._pause_queue("c", "error")
    assert queue.snapshot("c")["paused"] is False
    queue.enqueue("c", "a", _msg())
    await chat_routes._pause_queue("c", "error")
    snap = queue.snapshot("c")
    assert snap["paused"] is True and snap["reason"] == "error"
    await chat_routes._pause_queue(None, "error")


# ── error turns pause the queue ───────────────────────────────────────────────

@pytest.mark.parametrize("outcome", ["llm_error", "stalled", "leaked_tool_call", "max_iterations", "planner_error"])
async def test_a_turn_that_ends_in_an_error_outcome_is_flagged(outcome):
    import agent_loop

    task_id = f"t-{uuid.uuid4().hex}"
    shared.chat_task_store.create_task(task_id, "c")
    await agent_loop._log_turn_end_safe(
        "turn", "c", task_id, 0, "single", "m", "p", outcome, None, [], None, None, 0, 0, 0, 0, False, 0, 0)
    assert shared.chat_task_store.had_error(task_id) is True


@pytest.mark.parametrize("outcome", ["end_turn", "tool_round", "terminal_tool", "ask_user"])
async def test_a_turn_that_ends_normally_is_not_flagged(outcome):
    import agent_loop

    task_id = f"t-{uuid.uuid4().hex}"
    shared.chat_task_store.create_task(task_id, "c")
    await agent_loop._log_turn_end_safe(
        "turn", "c", task_id, 0, "single", "m", "p", outcome, None, [], None, None, 0, 0, 0, 0, False, 0, 0)
    assert shared.chat_task_store.had_error(task_id) is False


def _wait_for(predicate, seconds=5):
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_a_turn_that_crashes_pauses_the_queue_before_it_is_marked_done(queue, monkeypatch, api):
    async def subscriber_ready(task_id, timeout):
        return True

    async def window_fails(*args, **kwargs):
        raise RuntimeError("the history store broke")

    monkeypatch.setattr(shared.chat_task_store, "wait_for_subscriber", subscriber_ready)
    monkeypatch.setattr(shared.conversation_store, "get_window", window_fails)
    ctx = f"q-{uuid.uuid4().hex}"
    client = api
    queue.enqueue(ctx, "a", _msg("next"))
    task_id = client.post("/api/chat", json={"message": "hello", "context_id": ctx}).json()["task_id"]
    assert _wait_for(lambda: shared.chat_task_store.is_done(task_id))
    assert shared.chat_task_store.had_error(task_id) is True
    snap = client.get("/api/queue", params={"context_id": ctx}).json()
    assert snap["paused"] is True and snap["reason"] == "error"


def test_an_outer_failure_pauses_the_queue(queue, monkeypatch, api):
    async def subscriber_fails(task_id, timeout):
        raise RuntimeError("could not wait")

    monkeypatch.setattr(shared.chat_task_store, "wait_for_subscriber", subscriber_fails)
    ctx = f"q-{uuid.uuid4().hex}"
    client = api
    queue.enqueue(ctx, "a", _msg("next"))
    task_id = client.post("/api/chat", json={"message": "hello", "context_id": ctx}).json()["task_id"]
    assert _wait_for(lambda: shared.chat_task_store.is_done(task_id))
    assert queue.snapshot(ctx)["paused"] is True


def test_a_paused_queue_refuses_a_send_in_the_same_step_that_would_consume_it(queue, monkeypatch, api):
    _hold_turns_open(monkeypatch)
    ctx = f"q-{uuid.uuid4().hex}"
    client = api
    queue.enqueue(ctx, "a", _msg("next"))
    queue.pause(ctx, "error")
    with pytest.raises(QueueError) as err:
        queue.consume(ctx, "a")
    assert err.value.status == 409 and err.value.code == "queue_paused"
    refused = client.post("/api/chat", json={"message": "next", "context_id": ctx, "queued_id": "a"})
    assert refused.status_code == 409 and refused.json()["error"] == "queue_paused"
    assert shared.chat_task_store.active_task_for(ctx) is None
    assert [i["id"] for i in queue.snapshot(ctx)["items"]] == ["a"]
    queue.resume(ctx)
    sent = client.post("/api/chat", json={"message": "next", "context_id": ctx, "queued_id": "a"})
    assert sent.status_code == 200
    client.post(f"/api/chat/{sent.json()['task_id']}/cancel")


def test_the_head_waits_while_a_reply_runs_and_is_offered_once_it_is_stopped(queue, monkeypatch, api):
    _hold_turns_open(monkeypatch)
    ctx = f"q-{uuid.uuid4().hex}"
    client = api
    task_id = client.post("/api/chat", json={"message": "hello", "context_id": ctx}).json()["task_id"]
    queue.enqueue(ctx, "a", _msg("next"))
    assert client.get("/api/queue/head", params={"context_id": ctx}).json()["item"] is None
    client.post(f"/api/chat/{task_id}/cancel")
    client.post("/api/queue/resume", json={"context_id": ctx})
    assert client.get("/api/queue/head", params={"context_id": ctx}).json()["item"]["id"] == "a"


# ── what the queue keeps ──────────────────────────────────────────────────────

def test_the_snapshot_is_metadata_only_and_never_reads_the_payload(queue):
    import sqlite3

    image = {"mediaType": "image/png", "base64": "A" * 1000, "name": "x.png", "savedPath": ""}
    queue.enqueue("c", "a", _msg("look", [image, image]))
    snap = queue.snapshot("c")
    assert snap["items"][0]["attachments"] == 2
    assert "payload" not in snap["items"][0] and "AAAA" not in str(snap)
    with sqlite3.connect(queue._path) as conn:
        conn.execute("UPDATE queue SET payload='not json' WHERE id='a'")
    assert queue.snapshot("c")["items"][0]["attachments"] == 2


def test_a_queue_database_from_before_the_attachment_count_is_upgraded(tmp_path):
    import sqlite3

    path = tmp_path / "queue.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE queue (id TEXT PRIMARY KEY, context_id TEXT NOT NULL, seq INTEGER NOT NULL, "
            "created_at REAL NOT NULL, text TEXT NOT NULL, payload TEXT NOT NULL)")
    q = MessageQueue(path)
    q.enqueue("c", "a", _msg("hi"))
    assert q.snapshot("c")["items"][0]["attachments"] == 0


def test_a_message_nobody_came_back_for_expires(queue, monkeypatch):
    queue.enqueue("c", "a", _msg("old"))
    queue.pause("c", "stopped")
    monkeypatch.setattr(chat_queue, "QUEUE_TTL_SECONDS", -1)
    assert queue.snapshot("c") == {"items": [], "paused": False, "reason": "", "max": MAX_QUEUED}
    queue.enqueue("c", "b", _msg("old"))
    assert queue.head("c") is None


def test_slash_commands_are_refused_by_the_server(queue, monkeypatch, api):
    client = api
    refused = client.post("/api/queue", json={"context_id": "c", "id": "a", "payload": _msg("  /jira list")})
    assert refused.status_code == 400 and "Slash" in refused.json()["detail"]
    client.post("/api/queue", json={"context_id": "c", "id": "b", "payload": _msg("fine")})
    edited = client.put("/api/queue/b", json={"context_id": "c", "text": "/jira list"})
    assert edited.status_code == 400
    assert queue.snapshot("c")["items"][0]["text"] == "fine"


# ── error paths that end in a clean [DONE] still pause the queue ──────────────

def test_a_queued_send_that_races_a_typed_send_puts_its_message_back(queue, monkeypatch, api):
    _hold_turns_open(monkeypatch)
    ctx = f"q-{uuid.uuid4().hex}"
    queue.enqueue(ctx, "a", _msg("first"))
    queue.enqueue(ctx, "b", _msg("second"))
    real_take = queue.take

    def take_then_a_typed_send_wins(context_id, item_id):
        taken = real_take(context_id, item_id)
        shared.chat_task_store.create_task("typed-send", context_id)
        return taken

    monkeypatch.setattr(queue, "take", take_then_a_typed_send_wins)
    refused = api.post("/api/chat", json={"message": "first", "context_id": ctx, "queued_id": "a"})
    assert refused.status_code == 409
    assert refused.json()["error"] == "turn_in_progress" and refused.json()["task_id"] == "typed-send"
    items = queue.snapshot(ctx)["items"]
    assert [i["id"] for i in items] == ["a", "b"]
    assert [i["text"] for i in items] == ["first", "second"]
    assert shared.chat_task_store.active_task_for(ctx) == "typed-send"
    shared.chat_task_store.mark_done("typed-send")


def test_a_taken_message_can_be_restored_in_place(queue):
    queue.enqueue("c", "a", _msg("first", [{"mediaType": "image/png", "base64": "x", "name": "", "savedPath": ""}]))
    queue.enqueue("c", "b", _msg("second"))
    taken = queue.take("c", "a")
    assert [i["id"] for i in queue.snapshot("c")["items"]] == ["b"]
    queue.restore("c", taken)
    queue.restore("c", taken)
    snap = queue.snapshot("c")
    assert [i["id"] for i in snap["items"]] == ["a", "b"] and snap["items"][0]["attachments"] == 1
    assert queue.head("c")["payload"]["text"] == "first"


def test_a_tool_budget_overflow_turn_pauses_the_queue(queue, monkeypatch, api):
    import types

    import tool_pipeline

    async def subscriber_ready(task_id, timeout):
        return True

    monkeypatch.setattr(shared.chat_task_store, "wait_for_subscriber", subscriber_ready)
    monkeypatch.setattr(
        tool_pipeline, "select_tools_with_budget",
        lambda *a, **k: types.SimpleNamespace(required_overflow=True, tools=[], omitted_names=[]))
    ctx = f"q-{uuid.uuid4().hex}"
    queue.enqueue(ctx, "a", _msg("next"))
    task_id = api.post("/api/chat", json={"message": "hello", "context_id": ctx}).json()["task_id"]
    assert _wait_for(lambda: shared.chat_task_store.is_done(task_id))
    assert "Tool budget overflow" in "".join(shared.chat_task_store.get_chunks(task_id))
    assert shared.chat_task_store.had_error(task_id) is True
    snap = queue.snapshot(ctx)
    assert snap["paused"] is True and snap["reason"] == "error"


def test_a_verifier_that_returns_nothing_flags_the_turn_as_failed():
    import agent_loop

    class Empty:
        def build_assistant_message(self, raw):
            return {"role": "assistant", "content": raw}

        async def stream_turn(self, model, system, msgs, tools):
            yield {"type": "done", "stop_reason": "end_turn", "tool_calls": [], "raw_content": "", "usage": {}}

    task_id = f"t-{uuid.uuid4().hex}"
    shared.chat_task_store.create_task(task_id, "c")

    async def go():
        return [c async for c in agent_loop.run_three_agent_loop(
            provider=Empty(), model="m", system="s", msgs=[{"role": "user", "content": "hi"}],
            normalized_tools=[], execute_tool=None, COM_BOUND_TOOLS=set(), TOOL_STATUS={},
            _tool_toast=lambda *a, **k: None, _SLACK_SAFE_MSG="__safe__", context_id="c", task_id=task_id)]

    chunks = asyncio.run(go())
    assert any('"stalled": true' in c for c in chunks)
    assert shared.chat_task_store.had_error(task_id) is True


# ── terminal tool failures, the direct router, and restore edge cases ─────────

class _ToolCallingProvider:
    context_window = 200_000

    def __init__(self):
        self.calls = 0

    def normalize_tool_schema(self, tool):
        return tool

    async def stream_turn(self, model, system, messages, tools):
        self.calls += 1
        if self.calls == 1 and self.three_agent:
            yield {"type": "text_delta", "text": "Use Slack."}
            yield {"type": "done", "stop_reason": "end_turn", "tool_calls": [], "raw_content": [], "usage": {}}
            return
        yield {
            "type": "done", "stop_reason": "tool_use",
            "tool_calls": [types.SimpleNamespace(name="slack_search_users", inputs={}, id="t1")],
            "raw_content": [], "usage": {},
        }

    def build_assistant_message(self, raw):
        return {"role": "assistant", "content": raw}

    def build_tool_result_message(self, calls, results):
        return {"role": "user", "content": json.dumps(results)}


def _run_tool_loop(monkeypatch, tool_result, three_agent):
    import agent_loop

    flagged = []
    monkeypatch.setattr(agent_loop, "_flag_turn_error", lambda task_id: flagged.append(task_id))
    provider = _ToolCallingProvider()
    provider.three_agent = three_agent
    tools = [{"name": "slack_search_users", "description": "", "input_schema": {"type": "object"}}]

    async def execute_tool(name, inputs):
        return tool_result

    async def collect():
        if three_agent:
            gen = agent_loop.run_three_agent_loop(
                provider, "model", "system", [{"role": "user", "content": "find Ada"}], tools,
                execute_tool, set(), {}, lambda *_: None, "safe", token_budget=0, task_id="turn-1",
                context_id="ctx-1")
        else:
            gen = agent_loop._single_agent_loop(
                provider, "model", "system", [{"role": "user", "content": "find Ada"}], tools,
                execute_tool, set(), {}, lambda *_: None, "safe", task_id="turn-1", context_id="ctx-1")
        return [chunk async for chunk in gen]

    chunks = asyncio.run(collect())
    assert chunks[-1] == "data: [DONE]\n\n"
    return flagged


@pytest.mark.parametrize("three_agent", [False, True])
def test_a_terminal_tool_failure_with_a_message_flags_the_turn(monkeypatch, three_agent):
    assert _run_tool_loop(monkeypatch, {"error": "team_access_not_granted"}, three_agent) == ["turn-1"]


def test_the_direct_router_turn_is_tied_to_its_task_so_a_failure_can_pause_the_queue(queue, monkeypatch, api):
    import agent_loop
    import skill_router

    seen = {}

    async def fake_loop(*args, **kwargs):
        seen.update(kwargs)
        yield "data: [DONE]\n\n"

    async def fake_direct(intent, execute_tool, user_message=""):
        return {"ok": True, "data": {"rows": []}}

    async def subscriber_ready(task_id, timeout):
        return True

    monkeypatch.setattr(shared.chat_task_store, "wait_for_subscriber", subscriber_ready)
    monkeypatch.setattr(skill_router, "match_intent", lambda message: {"tool": "list_events"})
    monkeypatch.setattr(skill_router, "execute_direct", fake_direct)
    monkeypatch.setattr(agent_loop, "_single_agent_loop", fake_loop)
    ctx = f"q-{uuid.uuid4().hex}"
    task_id = api.post("/api/chat", json={"message": "what is on today", "context_id": ctx}).json()["task_id"]
    assert _wait_for(lambda: shared.chat_task_store.is_done(task_id))
    assert seen.get("task_id") == task_id and seen.get("context_id") == ctx


def test_a_message_that_cannot_be_put_back_is_reported_not_called_busy(queue, monkeypatch, api):
    _hold_turns_open(monkeypatch)
    ctx = f"q-{uuid.uuid4().hex}"
    queue.enqueue(ctx, "a", _msg("first"))
    real_take = queue.take

    def take_then_a_typed_send_wins(context_id, item_id):
        taken = real_take(context_id, item_id)
        shared.chat_task_store.create_task("typed-send", context_id)
        return taken

    def restore_fails(context_id, taken):
        raise QueueError(503, "queue unavailable")

    monkeypatch.setattr(queue, "take", take_then_a_typed_send_wins)
    monkeypatch.setattr(queue, "restore", restore_fails)
    resp = api.post("/api/chat", json={"message": "first", "context_id": ctx, "queued_id": "a"})
    assert resp.status_code == 503
    assert resp.json()["error"] == "queue_restore_failed" and "send it again" in resp.json()["detail"]
    shared.chat_task_store.mark_done("typed-send")


def test_a_restored_message_stays_ahead_of_one_queued_while_it_was_out(queue):
    queue.enqueue("c", "a", _msg("first"))
    taken = queue.take("c", "a")
    queue.enqueue("c", "b", _msg("newer"))
    queue.enqueue("c", "c", _msg("newest"))
    queue.restore("c", taken)
    assert [i["id"] for i in queue.snapshot("c")["items"]] == ["a", "b", "c"]
    assert queue.head("c")["payload"]["text"] == "first"
