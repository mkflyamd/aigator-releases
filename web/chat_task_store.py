"""In-memory buffer store for chat tasks.

Each task buffers SSE chunks as they are generated so any tab can
connect or reconnect and replay missed chunks via Last-Event-ID.
"""

import asyncio
import logging
import time

_log = logging.getLogger(__name__)

TASK_TTL_SECONDS = 1800  # keep completed tasks 30 min
ZOMBIE_TTL_SECONDS = 3600  # force-expire stuck tasks after 60 min


class ChatTaskStore:
    def __init__(self):
        self._store: dict[str, dict] = {}
        self._running_tasks: set = set()  # strong refs to asyncio.Tasks to prevent GC

    def track_task(self, task_id: str, asyncio_task) -> None:
        """Keep a strong reference to an asyncio.Task so GC doesn't cancel it,
        and stash the task handle on the task record so `cancel()` can reach
        it later and actually stop the turn (not just flag it as cancelled).
        """
        self._running_tasks.add(asyncio_task)

        def _done_callback(t: "asyncio.Task") -> None:
            self._running_tasks.discard(t)
            # Always retrieve the task's exception (if any) so asyncio never logs
            # "Task exception was never retrieved" — this fires for a normal user
            # cancel (t.cancelled() is True; nothing further to do) as well as for
            # a genuine bug, which we still surface via logging instead of hiding it.
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                _log.exception(
                    "[chat_task_store] background task ended with exception",
                    exc_info=exc,
                )

        asyncio_task.add_done_callback(_done_callback)
        task = self._store.get(task_id)
        if task is not None:
            task["asyncio_task"] = asyncio_task

    # ── Write side ──────────────────────────────────────────────────────────

    def create_task(self, task_id: str, context_id: str) -> None:
        self._store[task_id] = {
            "chunks": [],
            "done": False,
            "cancelled": False,
            "context_id": context_id,
            "created_at": time.monotonic(),
            "subscribers": [],
        }

    def append_chunk(self, task_id: str, chunk: str) -> None:
        task = self._store.get(task_id)
        if task is None:
            return
        task["chunks"].append(chunk)
        for q in task["subscribers"]:
            try:
                q.put_nowait(chunk)
            except asyncio.QueueFull:
                pass  # slow consumer catches up via replay on reconnect

    def mark_done(self, task_id: str) -> None:
        task = self._store.get(task_id)
        if task is None:
            return
        task["done"] = True
        self._send_sentinel(task)

    def cancel(self, task_id: str) -> bool:
        task = self._store.get(task_id)
        if task is None or task["done"]:
            return False
        task["cancelled"] = True
        # Actually stop the background turn so it releases the per-context
        # turn lock (conversation_store.lock_for) promptly, instead of only
        # flagging it and waiting for its in-flight tool `await` to finish on
        # its own (which could take up to the 300s request timeout, leaving
        # the NEXT message on the same context silently blocked the whole
        # time). Cancelling raises asyncio.CancelledError at the task's
        # current await, unwinding the `async with lock_for(...)` block.
        asyncio_task = task.get("asyncio_task")
        if asyncio_task is not None and not asyncio_task.done():
            asyncio_task.cancel()
        self._send_sentinel(task)
        return True

    def _send_sentinel(self, task: dict) -> None:
        """Deliver __DONE__ to all subscribers. Must get through even if queue is full."""
        for q in task["subscribers"]:
            if q.full():
                # Evict the oldest data chunk to make room for the terminal sentinel.
                # A slow consumer can catch up via replay; losing __DONE__ hangs the stream.
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait("__DONE__")
            except asyncio.QueueFull:
                pass  # queue was refilled between evict and put — SSE timeout will close it

    # ── Read side ────────────────────────────────────────────────────────────

    def is_cancelled(self, task_id: str) -> bool:
        task = self._store.get(task_id)
        return task["cancelled"] if task else False

    def is_done(self, task_id: str) -> bool:
        task = self._store.get(task_id)
        return task["done"] if task else True  # unknown → treat as done (safe default)

    def get_chunks(self, task_id: str, from_seq: int = 0) -> list[str]:
        task = self._store.get(task_id)
        if task is None:
            return []
        return task["chunks"][from_seq:]

    def get_context_id(self, task_id: str) -> str | None:
        task = self._store.get(task_id)
        return task["context_id"] if task else None

    # ── Subscription (per SSE connection) ───────────────────────────────────

    def subscribe(self, task_id: str) -> "asyncio.Queue | None":
        """Subscribe to live chunks for a task. Returns the queue, or None if
        the task is unknown. See subscribe_with_boundary for the race-free
        variant — this method is retained for any caller that doesn't need a
        replay boundary (e.g. notification-only subscribers)."""
        q, _boundary = self._subscribe(task_id)
        return q

    def subscribe_with_boundary(
        self, task_id: str
    ) -> "tuple[asyncio.Queue | None, int]":
        """Atomically subscribe AND capture the replay boundary (current chunk
        count). Returns (queue, boundary_seq) or (None, 0) if the task is
        unknown.

        PR #10 review fix (subscribe/replay race): the previous flow was
            q = subscribe(task_id)         # start queueing live chunks
            for c in get_chunks(...): ...   # then snapshot replay
        A chunk appended between those two lines was BOTH in get_chunks()
        (appended to the chunks list) AND put_nowait'd into q (the subscriber
        was already registered), so it was emitted once during replay and
        again from the queue — duplicating tokens and, worse, side-effecting
        UI events ("tool started" fired twice).

        This method performs the subscribe and the boundary capture under no
        explicit lock, but relies on the fact that append_chunk is the ONLY
        writer to both chunks[] and subscribers' queues, and it does so
        synchronously (list.append then put_nowait in the same call frame).
        So any chunk appended AFTER this method returns will have seq >=
        boundary (the chunk count we just read), and any chunk appended
        BEFORE will have seq < boundary. The caller drops queued chunks with
        seq < boundary to avoid the duplicate. The chunks[] list read
        (len(task["chunks"])) happens-after the subscribers.append, and since
        both are ordinary in-process operations with no await between them,
        no append_chunk can slip in between (single-threaded asyncio event
        loop). This is the same property that makes the existing append_chunk
        fan-out safe.
        """
        return self._subscribe(task_id)

    def _subscribe(self, task_id: str) -> "tuple[asyncio.Queue | None, int]":
        task = self._store.get(task_id)
        if task is None:
            return None, 0
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        task["subscribers"].append(q)
        boundary = len(task["chunks"])
        return q, boundary

    def unsubscribe(self, task_id: str, q: "asyncio.Queue") -> None:
        task = self._store.get(task_id)
        if task is None:
            return
        try:
            task["subscribers"].remove(q)
        except ValueError:
            pass

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def cleanup_expired(self) -> int:
        now = time.monotonic()
        to_delete = []
        for task_id, task in self._store.items():
            age = now - task["created_at"]
            if (task["done"] or task["cancelled"]) and age > TASK_TTL_SECONDS:
                to_delete.append(task_id)
            elif (
                not task["done"] and not task["cancelled"] and age > ZOMBIE_TTL_SECONDS
            ):
                to_delete.append(task_id)
        for task_id in to_delete:
            del self._store[task_id]
        return len(to_delete)
