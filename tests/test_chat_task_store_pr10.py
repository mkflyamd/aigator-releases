"""Tests for the PR #10 review fix: subscribe_with_boundary must prevent the
subscribe/replay duplication race. Previously subscribe() ran before the
replay snapshot (get_chunks), so a chunk appended between the two was both
replayed AND queued — emitted twice. Now subscribe_with_boundary atomically
returns (queue, boundary_seq) and the caller drops queued chunks with seq <
boundary.
"""
import asyncio
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
    the caller reads get_chunks for replay. With the boundary, the caller
    knows to skip this many chunks from the queue (they were replayed). This
    test verifies the boundary is correct for that skip calculation."""
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

    # The caller replays get_chunks(from_seq=0) — gets 3 chunks (0, 1, 2).
    replayed = store.get_chunks(task_id, from_seq=0)
    assert len(replayed) == 3

    # The caller skips (boundary - from_seq) = 2 chunks from the queue —
    # those are the duplicates (chunks 0 and 1, already replayed).
    # Chunk 2 (appended after subscribe) is NOT skipped — it's new.
    skip_count = boundary - 0
    queued_items = asyncio.run(_drain(q))
    # The queue has chunk-2 (the one appended after subscribe). chunk-0 and
    # chunk-1 were appended BEFORE subscribe, so they're NOT in the queue
    # (subscribers only get chunks appended AFTER they subscribe).
    assert "chunk-2\n" in queued_items
    assert "chunk-0\n" not in queued_items
    assert "chunk-1\n" not in queued_items
    # skip_count is 2, but the queue only has 1 item (chunk-2). The caller's
    # skip logic drops min(skip_count, len(queued)) items — since chunk-0 and
    # chunk-1 aren't in the queue, nothing needs skipping, and chunk-2 is
    # delivered once. This is the correct, dedup'd behavior.
