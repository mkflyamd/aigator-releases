"""Adversarial tests for lossless chat SSE delivery to slow subscribers."""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from starlette.requests import Request

import shared
from chat_task_store import ChatTaskStore
from routes.chat import chat_stream


@pytest.mark.asyncio
async def test_sse_stream_drains_all_chunks_after_wake_queue_coalesces():
    """500 buffered deltas must reach one subscriber, not stop at queue size."""
    original_store = shared.chat_task_store
    store = ChatTaskStore()
    shared.chat_task_store = store
    task_id = "slow-subscriber"
    store.create_task(task_id, "ctx")
    request = Request(
        {"type": "http", "method": "GET", "headers": [], "query_string": b""}
    )

    async def _produce():
        await asyncio.sleep(0)
        for index in range(500):
            store.append_chunk(task_id, f'data: {{"token":"{index},"}}\n\n')
        store.append_chunk(task_id, "data: [DONE]\n\n")
        store.mark_done(task_id)

    try:
        response = await chat_stream(task_id, request)
        producer = asyncio.create_task(_produce())
        parts = []
        async for part in response.body_iterator:
            parts.append(part.decode() if isinstance(part, bytes) else part)
        await producer
        payload = "".join(parts)
    finally:
        shared.chat_task_store = original_store

    assert payload.count('"token"') == 500
    assert '"token":"499,"' in payload
    assert '"token_events": 500' in payload
    assert payload.endswith("data: [DONE]\n\n")


@pytest.mark.asyncio
async def test_sse_stream_drains_chunk_appended_while_suspended_at_a_yield():
    """Regression: the producer can append a new chunk and mark the task done
    while the generator is suspended at one of the yields inside the initial
    drain loop (each yield hands control back to the driving ASGI server,
    which is a point where the producer coroutine can run). Before the fix,
    resuming the for-loop over the stale, already-captured snapshot would
    finish immediately, see is_done() == True, and emit [DONE] without ever
    re-reading the chunk the producer appended during that window.
    """
    original_store = shared.chat_task_store
    store = ChatTaskStore()
    shared.chat_task_store = store
    task_id = "race-mid-snapshot"
    store.create_task(task_id, "ctx")
    store.append_chunk(task_id, 'data: {"token":"first"}\n\n')
    request = Request(
        {"type": "http", "method": "GET", "headers": [], "query_string": b""}
    )

    try:
        response = await chat_stream(task_id, request)
        body_iter = response.body_iterator

        # Drains the pre-existing snapshot (one chunk: "first"), suspending
        # the generator immediately after this yield — mid-for-loop, before
        # it has re-checked the buffer or is_done().
        first_part = await body_iter.__anext__()

        # Simulate the producer running while the consumer sits suspended at
        # that yield: append a new chunk and mark done, exactly as a real
        # producer finishing its turn between two SSE writes would.
        store.append_chunk(task_id, 'data: {"token":"second"}\n\n')
        store.append_chunk(task_id, "data: [DONE]\n\n")
        store.mark_done(task_id)

        parts = [first_part]
        async for part in body_iter:
            parts.append(part)
        payload = "".join(p.decode() if isinstance(p, bytes) else p for p in parts)
    finally:
        shared.chat_task_store = original_store

    assert '"token":"first"' in payload
    assert '"token":"second"' in payload, (
        "a chunk appended while the generator was suspended at a yield must "
        "still be drained before [DONE]"
    )
    assert '"token_events": 2' in payload
    assert payload.endswith("data: [DONE]\n\n")


@pytest.mark.asyncio
async def test_sse_stream_drains_chunk_when_marked_done_with_no_done_sentinel_chunk():
    """Regression: real producer code (web/routes/chat.py's idle-timeout /
    stall path in _run_and_buffer) calls mark_done() in its `finally` block
    BEFORE it appends a literal "data: [DONE]\\n\\n" chunk to the buffer (that
    append is conditional and happens afterward, if at all). So is_done() can
    flip True while the buffer contains real content but NO [DONE] sentinel at
    all. The consumer must still drain that content via the "buffer is
    genuinely empty, stop" branch (not the "found a literal [DONE] mid-loop"
    branch exercised by the test above) before synthesizing its own [DONE].
    """
    original_store = shared.chat_task_store
    store = ChatTaskStore()
    shared.chat_task_store = store
    task_id = "race-no-done-sentinel"
    store.create_task(task_id, "ctx")
    store.append_chunk(task_id, 'data: {"token":"first"}\n\n')
    request = Request(
        {"type": "http", "method": "GET", "headers": [], "query_string": b""}
    )

    try:
        response = await chat_stream(task_id, request)
        body_iter = response.body_iterator

        # Drains the pre-existing snapshot (one chunk: "first"), suspending
        # the generator immediately after this yield.
        first_part = await body_iter.__anext__()

        # Mirror the real _run_and_buffer idle-timeout ordering: append one
        # more real chunk, then mark_done() — with NO "[DONE]" chunk ever
        # appended to the buffer.
        store.append_chunk(task_id, 'data: {"token":"second"}\n\n')
        store.mark_done(task_id)

        parts = [first_part]
        async for part in body_iter:
            parts.append(part)
        payload = "".join(p.decode() if isinstance(p, bytes) else p for p in parts)
    finally:
        shared.chat_task_store = original_store

    assert '"token":"first"' in payload
    assert '"token":"second"' in payload, (
        "a chunk appended right before mark_done() (with no [DONE] sentinel "
        "ever appended) must still be drained before the stream terminates"
    )
    assert '"token_events": 2' in payload
    assert payload.endswith("data: [DONE]\n\n"), (
        "the consumer must synthesize its own [DONE] once is_done() is true "
        "and the buffer is stable, even if the producer never wrote a literal "
        "[DONE] sentinel chunk"
    )


@pytest.mark.asyncio
async def test_cancel_does_not_drop_a_chunk_racing_the_done_signal():
    """Regression: cancel()'s _send_done_signal REPLACES (clears, then
    overwrites) any pending __WAKE__ signal in the subscriber queue with
    __DONE__ — unlike mark_done(), which only ever coalesces a __WAKE__. If a
    real chunk is appended (queuing a __WAKE__) and then cancel() fires before
    the consumer is ever scheduled to observe that __WAKE__, the consumer's
    `await q.get()` resolves directly to "__DONE__" and — before this fix —
    terminated immediately without re-checking the buffer, silently dropping
    the chunk that was already committed to the authoritative buffer.
    """
    original_store = shared.chat_task_store
    store = ChatTaskStore()
    shared.chat_task_store = store
    task_id = "cancel-race"
    store.create_task(task_id, "ctx")
    store.append_chunk(task_id, 'data: {"token":"first"}\n\n')
    request = Request(
        {"type": "http", "method": "GET", "headers": [], "query_string": b""}
    )

    try:
        response = await chat_stream(task_id, request)
        body_iter = response.body_iterator
        parts: list = []

        async def _collect():
            async for part in body_iter:
                parts.append(part)

        consumer = asyncio.create_task(_collect())

        # Let the consumer drain "first" and settle into `await q.get()`
        # inside the main loop (not mid-drain at a yield).
        for _ in range(5):
            await asyncio.sleep(0)

        # Producer appends a real chunk (normal path: queues a __WAKE__),
        # then — in the same synchronous stretch, no await in between — the
        # user cancels. cancel()'s _send_done_signal drains the queue and
        # replaces whatever is there with __DONE__, all before the consumer
        # task is ever scheduled to observe the intermediate __WAKE__.
        store.append_chunk(task_id, 'data: {"token":"second"}\n\n')
        store.cancel(task_id)

        await asyncio.wait_for(consumer, timeout=2)
        payload = "".join(p.decode() if isinstance(p, bytes) else p for p in parts)
    finally:
        shared.chat_task_store = original_store

    assert '"token":"first"' in payload
    assert '"token":"second"' in payload, (
        "a chunk appended just before cancel() must still be drained before "
        "the stream honors the terminal __DONE__ signal"
    )
    assert payload.endswith("data: [DONE]\n\n")
