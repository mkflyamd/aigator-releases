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
