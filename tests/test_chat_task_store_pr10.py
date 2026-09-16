"""Regression tests for lossless chat task-stream subscription and replay."""

import asyncio
import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from chat_task_store import ChatTaskStore


def test_subscribe_with_boundary_returns_queue_and_boundary():
    store = ChatTaskStore()
    task_id = "task-1"
    store.create_task(task_id, "ctx-1")
    store.append_chunk(task_id, "chunk-0\n")
    store.append_chunk(task_id, "chunk-1\n")

    q, boundary = store.subscribe_with_boundary(task_id)
    assert q is not None
    assert boundary == 2  # two chunks were already buffered


def test_subscribe_with_boundary_boundary_equals_chunk_count():
    """The boundary must be exactly len(chunks) at subscribe time — any chunk
    appended AFTER has seq >= boundary, any chunk appended BEFORE has seq <
    boundary."""
    store = ChatTaskStore()
    task_id = "task-1"
    store.create_task(task_id, "ctx-1")
    for i in range(5):
        store.append_chunk(task_id, f"chunk-{i}\n")

    q, boundary = store.subscribe_with_boundary(task_id)
    assert boundary == 5


def test_chunk_appended_after_subscribe_wakes_consumer_and_stays_in_buffer():
    """The live queue is a wake signal; task chunks remain authoritative."""
    store = ChatTaskStore()
    task_id = "task-1"
    store.create_task(task_id, "ctx-1")
    store.append_chunk(task_id, "old-chunk\n")

    q, boundary = store.subscribe_with_boundary(task_id)
    assert boundary == 1

    # Append a chunk AFTER subscribe — it wakes the consumer, which drains
    # the actual text from the append-only task buffer by sequence.
    store.append_chunk(task_id, "new-chunk\n")
    queued = asyncio.run(_drain(q))
    assert queued == ["__WAKE__"]
    assert store.get_chunks(task_id, from_seq=boundary) == ["new-chunk\n"]


def test_subscribe_still_works_for_legacy_callers():
    """The old subscribe() method (no boundary) must still return just the
    queue, for any caller that doesn't need the replay boundary."""
    store = ChatTaskStore()
    task_id = "task-1"
    store.create_task(task_id, "ctx-1")
    store.append_chunk(task_id, "chunk-0\n")

    q = store.subscribe(task_id)
    assert q is not None


def test_unknown_task_returns_none_queue_and_zero_boundary():
    store = ChatTaskStore()
    q, boundary = store.subscribe_with_boundary("nonexistent")
    assert q is None
    assert boundary == 0


def test_first_sse_subscription_releases_producer_barrier():
    """The producer must not emit its first token before the UI subscribes."""
    store = ChatTaskStore()
    task_id = "task-subscriber-ready"
    store.create_task(task_id, "ctx-1")

    async def _wait_then_subscribe():
        waiting = asyncio.create_task(store.wait_for_subscriber(task_id, timeout=0.5))
        await asyncio.sleep(0)
        assert not waiting.done()
        queue, _ = store.subscribe_with_boundary(task_id)
        assert queue is not None
        return await waiting

    assert asyncio.run(_wait_then_subscribe()) is True


def test_subscriber_barrier_has_bounded_non_sse_fallback():
    store = ChatTaskStore()
    task_id = "task-no-subscriber"
    store.create_task(task_id, "ctx-1")

    assert asyncio.run(store.wait_for_subscriber(task_id, timeout=0.001)) is False


def test_stream_integrity_covers_all_text_deltas_without_storing_text():
    store = ChatTaskStore()
    task_id = "task-integrity"
    store.create_task(task_id, "ctx-1")
    store.append_chunk(task_id, 'data: {"token":"Let "}\n\n')
    store.append_chunk(task_id, 'data: {"thinking":"hidden"}\n\n')
    store.append_chunk(task_id, 'data: {"token":"me check"}\n\n')

    integrity = store.stream_integrity(task_id)
    expected = "Let me check".encode("utf-8")
    assert integrity == {
        "token_events": 2,
        "utf8_bytes": len(expected),
        "sha256": hashlib.sha256(expected).hexdigest(),
    }


async def _drain(q, timeout=0.5):
    """Drain all currently-queued items without blocking."""
    out = []
    try:
        while True:
            item = await asyncio.wait_for(q.get(), timeout=timeout)
            out.append(item)
    except asyncio.TimeoutError:
        pass
    return out


def test_no_duplicate_when_chunk_appended_between_subscribe_and_replay():
    """The core race scenario: a chunk is appended AFTER subscribe but BEFORE
    the caller reads the replay snapshot. The bounded snapshot excludes that
    queued chunk, so it is delivered exactly once from the task buffer."""
    store = ChatTaskStore()
    task_id = "task-1"
    store.create_task(task_id, "ctx-1")
    store.append_chunk(task_id, "chunk-0\n")
    store.append_chunk(task_id, "chunk-1\n")

    # Subscribe — boundary captures that 2 chunks exist.
    q, boundary = store.subscribe_with_boundary(task_id)
    assert boundary == 2

    # Now a chunk is appended (the race window). It is in chunks[] and wakes
    # the subscriber, but is never copied into the bounded queue itself.
    store.append_chunk(task_id, "chunk-2\n")

    # Replay is bounded to the immutable pre-subscription snapshot.
    replayed = store.get_chunks(task_id, from_seq=0, to_seq=boundary)
    assert replayed == ["chunk-0\n", "chunk-1\n"]

    queued_items = asyncio.run(_drain(q))
    assert queued_items == ["__WAKE__"]
    assert store.get_chunks(task_id, from_seq=boundary) == ["chunk-2\n"]


def test_slow_subscriber_never_loses_chunks_when_wake_queue_is_full():
    """A full one-slot wake queue coalesces signals, never response data."""
    store = ChatTaskStore()
    task_id = "task-slow-subscriber"
    store.create_task(task_id, "ctx-1")
    queue, boundary = store.subscribe_with_boundary(task_id)
    assert boundary == 0

    for i in range(500):
        store.append_chunk(task_id, f"chunk-{i}\n")

    assert queue.qsize() == 1
    assert asyncio.run(queue.get()) == "__WAKE__"
    assert store.get_chunks(task_id, from_seq=boundary) == [
        f"chunk-{i}\n" for i in range(500)
    ]
