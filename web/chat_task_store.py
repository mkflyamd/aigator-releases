"""In-memory buffer store for chat tasks.

Each task buffers SSE chunks as they are generated so any tab can
connect or reconnect and replay missed chunks via Last-Event-ID.
"""

import asyncio
import time

TASK_TTL_SECONDS = 1800        # keep completed tasks 30 min
ZOMBIE_TTL_SECONDS = 3600      # force-expire stuck tasks after 60 min


class ChatTaskStore:
    def __init__(self):
        self._store: dict[str, dict] = {}
        self._running_tasks: set = set()  # strong refs to asyncio.Tasks to prevent GC

    def track_task(self, asyncio_task) -> None:
        """Keep a strong reference to an asyncio.Task so GC doesn't cancel it."""
        self._running_tasks.add(asyncio_task)
        asyncio_task.add_done_callback(self._running_tasks.discard)

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
        task = self._store.get(task_id)
        if task is None:
            return None
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        task["subscribers"].append(q)
        return q

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
            elif not task["done"] and not task["cancelled"] and age > ZOMBIE_TTL_SECONDS:
                to_delete.append(task_id)
        for task_id in to_delete:
            del self._store[task_id]
        return len(to_delete)
