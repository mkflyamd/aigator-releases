"""One live turn per conversation: the store knows which turn is alive, and chat() refuses a
second turn on the same context (409 turn_in_progress) instead of queueing it behind the lock."""

import asyncio
import os
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import app  # noqa: E402,F401
import shared  # noqa: E402
from chat_task_store import ChatTaskStore  # noqa: E402
from routes import chat as chat_routes  # noqa: E402


async def _forever():
    await asyncio.sleep(1000)


async def test_a_context_with_a_running_task_has_an_active_turn():
    store = ChatTaskStore()
    store.create_task("t1", "ctx")
    store.track_task("t1", asyncio.create_task(_forever()))
    assert store.active_task_for("ctx") == "t1"
    assert store.active_task_for("other") is None
    store.cancel("t1")


async def test_a_stopped_turn_still_unwinding_is_still_active():
    store = ChatTaskStore()
    store.create_task("t1", "ctx")
    unwinding = asyncio.Event()

    async def turn():
        try:
            await asyncio.sleep(1000)
        except asyncio.CancelledError:
            unwinding.set()
            await asyncio.sleep(0.2)
            raise

    bg = asyncio.create_task(turn())
    store.track_task("t1", bg)
    await asyncio.sleep(0)
    store.cancel("t1")
    await unwinding.wait()
    assert store.is_cancelled("t1")
    assert store.active_task_for("ctx") == "t1"
    assert await store.wait_for_task_end("t1", timeout=2.0) is True
    assert store.active_task_for("ctx") is None


async def test_a_finished_turn_is_not_active():
    store = ChatTaskStore()
    store.create_task("t1", "ctx")

    async def turn():
        return None

    bg = asyncio.create_task(turn())
    store.track_task("t1", bg)
    await bg
    assert store.active_task_for("ctx") is None


async def test_wait_for_task_end_times_out_while_the_turn_is_alive():
    store = ChatTaskStore()
    store.create_task("t1", "ctx")
    store.track_task("t1", asyncio.create_task(_forever()))
    assert await store.wait_for_task_end("t1", timeout=0.05) is False
    store.cancel("t1")


async def test_a_reply_that_finished_on_its_own_is_not_active_even_while_its_task_unwinds():
    store = ChatTaskStore()
    store.create_task("t1", "ctx")
    bg = asyncio.create_task(_forever())
    store.track_task("t1", bg)
    store.mark_done("t1")
    assert not bg.done()
    assert store.active_task_for("ctx") is None
    bg.cancel()


async def test_a_stopped_turn_stays_active_after_its_done_flag_until_its_task_ends():
    store = ChatTaskStore()
    store.create_task("t1", "ctx")
    bg = asyncio.create_task(_forever())
    store.track_task("t1", bg)
    store.cancel("t1")
    store.mark_done("t1")
    assert store.active_task_for("ctx") == "t1"
    bg.cancel()
    await asyncio.gather(bg, return_exceptions=True)
    assert store.active_task_for("ctx") is None


def _client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(chat_routes, "_classify_skills_via_llm", lambda *a, **k: [])
    api = FastAPI()
    api.include_router(chat_routes.router)
    return TestClient(api)


def _slow_unwind(monkeypatch, seconds):
    async def waits_then_unwinds_slowly(task_id, timeout):
        try:
            await asyncio.sleep(1000)
        except asyncio.CancelledError:
            await asyncio.sleep(seconds)
            raise

    monkeypatch.setattr(shared.chat_task_store, "wait_for_subscriber", waits_then_unwinds_slowly)


def test_a_second_message_while_a_turn_runs_is_refused(monkeypatch):
    _slow_unwind(monkeypatch, 0)
    ctx = f"turn-{uuid.uuid4().hex}"
    with _client(monkeypatch) as client:
        first = client.post("/api/chat", json={"message": "hello", "context_id": ctx})
        assert first.status_code == 200
        second = client.post("/api/chat", json={"message": "again", "context_id": ctx})
        assert second.status_code == 409
        body = second.json()
        assert body["error"] == "turn_in_progress"
        assert body["task_id"] == first.json()["task_id"]
        other = client.post("/api/chat", json={"message": "hi", "context_id": f"turn-{uuid.uuid4().hex}"})
        assert other.status_code == 200
        for r in (first, other):
            client.post(f"/api/chat/{r.json()['task_id']}/cancel")


def test_send_right_after_stop_waits_for_the_old_turn_and_never_overlaps(monkeypatch):
    _slow_unwind(monkeypatch, 0.4)
    ctx = f"turn-{uuid.uuid4().hex}"
    with _client(monkeypatch) as client:
        first_id = client.post("/api/chat", json={"message": "hello", "context_id": ctx}).json()["task_id"]
        old = shared.chat_task_store._store[first_id]["asyncio_task"]
        client.post(f"/api/chat/{first_id}/cancel")
        started = time.monotonic()
        second = client.post("/api/chat", json={"message": "again", "context_id": ctx})
        assert second.status_code == 200
        assert second.json()["task_id"] != first_id
        assert old.done(), "the second turn was registered while the stopped one was still unwinding"
        assert time.monotonic() - started >= 0.3
        client.post(f"/api/chat/{second.json()['task_id']}/cancel")


def test_send_right_after_stop_is_refused_if_the_old_turn_will_not_unwind(monkeypatch):
    _slow_unwind(monkeypatch, 1.0)
    monkeypatch.setattr(chat_routes, "_STOP_UNWIND_GRACE_S", 0.05)
    ctx = f"turn-{uuid.uuid4().hex}"
    with _client(monkeypatch) as client:
        first_id = client.post("/api/chat", json={"message": "hello", "context_id": ctx}).json()["task_id"]
        client.post(f"/api/chat/{first_id}/cancel")
        second = client.post("/api/chat", json={"message": "again", "context_id": ctx})
        assert second.status_code == 409
        assert second.json()["task_id"] == first_id


def _hold_the_turn_lock(monkeypatch, unwind_seconds):
    """The turn really sits inside lock_for(context) and takes `unwind_seconds` to let go after Stop."""
    async def ready(task_id, timeout):
        return True

    async def stuck_holding_the_lock(*args, **kwargs):
        try:
            await asyncio.sleep(1000)
        except asyncio.CancelledError:
            await asyncio.sleep(unwind_seconds)
            raise

    monkeypatch.setattr(shared.chat_task_store, "wait_for_subscriber", ready)
    monkeypatch.setattr(shared.conversation_store, "get_window", stuck_holding_the_lock)


def test_two_sends_at_the_same_moment_start_exactly_one_turn(monkeypatch):
    _slow_unwind(monkeypatch, 0)
    ctx = f"turn-{uuid.uuid4().hex}"
    results = []
    barrier = threading.Barrier(2)
    with _client(monkeypatch) as client:
        def send(text):
            barrier.wait()
            results.append(client.post("/api/chat", json={"message": text, "context_id": ctx}))

        threads = [threading.Thread(target=send, args=(f"msg {i}",)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        assert sorted(r.status_code for r in results) == [200, 409]
        winner = next(r for r in results if r.status_code == 200).json()["task_id"]
        assert next(r for r in results if r.status_code == 409).json()["task_id"] == winner
        client.post(f"/api/chat/{winner}/cancel")


def test_resend_after_stop_waits_for_the_old_turn_that_holds_the_lock(monkeypatch):
    _hold_the_turn_lock(monkeypatch, 0.4)
    ctx = f"turn-{uuid.uuid4().hex}"
    with _client(monkeypatch) as client:
        first_id = client.post("/api/chat", json={"message": "hello", "context_id": ctx}).json()["task_id"]
        deadline = time.monotonic() + 5
        lock = shared.conversation_store.lock_for(ctx)
        while not lock.locked() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert lock.locked(), "the first turn never took the turn lock"
        old = shared.chat_task_store._store[first_id]["asyncio_task"]
        client.post(f"/api/chat/{first_id}/cancel")
        second = client.post("/api/chat", json={"message": "again", "context_id": ctx})
        assert second.status_code == 200
        assert old.done(), "the second turn was registered while the stopped one still held the lock"
        client.post(f"/api/chat/{second.json()['task_id']}/cancel")
