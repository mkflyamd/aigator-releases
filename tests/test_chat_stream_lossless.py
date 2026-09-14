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
