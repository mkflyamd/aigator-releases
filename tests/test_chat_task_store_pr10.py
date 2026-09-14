"""Tests for the PR #10 review fix: subscribe_with_boundary must prevent the
subscribe/replay duplication race. Previously subscribe() ran before the
replay snapshot (get_chunks), so a chunk appended between the two was both
replayed AND queued — emitted twice. Now subscribe_with_boundary atomically
returns (queue, boundary_seq) and the caller drops queued chunks with seq <
boundary.
"""

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


def test_chunk_appended_after_subscribe_is_queued_and_not_in_boundary():
    """A chunk appended after subscribe_with_boundary must be in the queue but
    NOT counted in the boundary — the caller uses boundary to skip
    already-replayed chunks, so this chunk (seq >= boundary) must NOT be
    skipped."""
    store = ChatTaskStore()
    task_id = "task-1"
    store.create_task(task_id, "ctx-1")
    store.append_chunk(task_id, "old-chunk\n")

    q, boundary = store.subscribe_with_boundary(task_id)
    assert boundary == 1

    # Append a chunk AFTER subscribe — it must be queued.
    store.append_chunk(task_id, "new-chunk\n")
    queued = asyncio.run(_drain(q))
    assert "new-chunk\n" in queued


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
    queued chunk, so it is delivered exactly once by the live queue."""
    store = ChatTaskStore()
    task_id = "task-1"
    store.create_task(task_id, "ctx-1")
    store.append_chunk(task_id, "chunk-0\n")
    store.append_chunk(task_id, "chunk-1\n")

    # Subscribe — boundary captures that 2 chunks exist.
    q, boundary = store.subscribe_with_boundary(task_id)
    assert boundary == 2

    # Now a chunk is appended (the race window). It's queued AND in chunks[].
    store.append_chunk(task_id, "chunk-2\n")

    # Replay is bounded to the immutable pre-subscription snapshot.
    replayed = store.get_chunks(task_id, from_seq=0, to_seq=boundary)
    assert replayed == ["chunk-0\n", "chunk-1\n"]

    queued_items = asyncio.run(_drain(q))
    # The queue has chunk-2 (the one appended after subscribe). chunk-0 and
    # chunk-1 were appended BEFORE subscribe, so they're NOT in the queue
    # (subscribers only get chunks appended AFTER they subscribe).
    assert "chunk-2\n" in queued_items
    assert "chunk-0\n" not in queued_items
    assert "chunk-1\n" not in queued_items


def test_bounded_replay_preserves_post_subscription_chunks():
    """New chunks belong to the live queue, never to a skip counter.

    This reproduces the first-token loss bug: replaying an unbounded chunks[]
    list and then discarding queued events can drop a real post-subscription
    token. The boundary cleanly separates the immutable replay snapshot from
    the live queue.
    """
    store = ChatTaskStore()
    task_id = "task-bounded-replay"
    store.create_task(task_id, "ctx-1")
    store.append_chunk(task_id, "old\n")

    queue, boundary = store.subscribe_with_boundary(task_id)
    assert boundary == 1
    store.append_chunk(task_id, "new\n")

    assert store.get_chunks(task_id, from_seq=0, to_seq=boundary) == ["old\n"]
    assert asyncio.run(queue.get()) == "new\n"
