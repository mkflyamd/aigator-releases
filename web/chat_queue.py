"""Messages a user typed while a turn was running, held per conversation until the turn ends.

The queue lives in sqlite so a reload, a second window or a restart sees the same chips. Nothing
here sends a message: the browser asks for the head, submits it as an ordinary chat request carrying
`queued_id`, and the chat route removes the entry in the same step that accepts the turn. A request
that is refused (a turn is still alive, or another window got there first) leaves the queue alone.
"""
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

_log = logging.getLogger(__name__)

MAX_QUEUED = 5
MAX_ITEM_BYTES = 6 * 1024 * 1024
MAX_TEXT_CHARS = 100_000
QUEUE_TTL_SECONDS = 24 * 3600  # a message nobody came back for is not sent a day later


class QueueError(Exception):
    def __init__(self, status: int, message: str, code: str = "queue_unavailable"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


class MessageQueue:
    def __init__(self, path):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, timeout=5)
        if not self._ready:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS queue (id TEXT PRIMARY KEY, context_id TEXT NOT NULL, "
                "seq INTEGER NOT NULL, created_at REAL NOT NULL, text TEXT NOT NULL, payload TEXT NOT NULL, "
                "attachments INTEGER NOT NULL DEFAULT 0)")
            if "attachments" not in {r[1] for r in conn.execute("PRAGMA table_info(queue)")}:
                conn.execute("ALTER TABLE queue ADD COLUMN attachments INTEGER NOT NULL DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS queue_context ON queue (context_id, seq)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS queue_state (context_id TEXT PRIMARY KEY, paused INTEGER NOT NULL, "
                "reason TEXT NOT NULL)")
            self._ready = True
        return conn

    def _run(self, work):
        with self._lock:
            try:
                conn = self._connect()
                try:
                    with conn:
                        return work(conn)
                finally:
                    conn.close()
            except (sqlite3.Error, OSError) as exc:
                _log.warning("message queue unavailable (%s)", type(exc).__name__)
                raise QueueError(503, "The message queue is unavailable right now. Try again.") from exc

    @staticmethod
    def _state(conn, context_id: str) -> tuple[bool, str]:
        row = conn.execute("SELECT paused, reason FROM queue_state WHERE context_id=?", (context_id,)).fetchone()
        return (bool(row[0]), row[1]) if row else (False, "")

    @staticmethod
    def _expire(conn) -> None:
        conn.execute("DELETE FROM queue WHERE created_at < ?", (time.time() - QUEUE_TTL_SECONDS,))
        conn.execute("DELETE FROM queue_state WHERE context_id NOT IN (SELECT context_id FROM queue)")

    def snapshot(self, context_id: str) -> dict:
        """What the chips need: each entry's text and attachment count, plus whether the queue is paused. Never the payload."""
        def work(conn):
            self._expire(conn)
            rows = conn.execute(
                "SELECT id, created_at, text, attachments FROM queue WHERE context_id=? ORDER BY seq", (context_id,)).fetchall()
            paused, reason = self._state(conn, context_id)
            items = [{"id": r[0], "created_at": r[1], "text": r[2], "attachments": r[3]} for r in rows]
            return {"items": items, "paused": paused, "reason": reason, "max": MAX_QUEUED}
        return self._run(work)

    def head(self, context_id: str) -> dict | None:
        """The next message to send, with its full payload; None while paused or empty."""
        def work(conn):
            self._expire(conn)
            if self._state(conn, context_id)[0]:
                return None
            row = conn.execute(
                "SELECT id, payload FROM queue WHERE context_id=? ORDER BY seq LIMIT 1", (context_id,)).fetchone()
            return {"id": row[0], "payload": json.loads(row[1])} if row else None
        return self._run(work)

    def enqueue(self, context_id: str, item_id: str, payload: dict) -> dict:
        if not item_id or not isinstance(payload, dict) or not isinstance(payload.get("text", ""), str):
            raise QueueError(400, "That message could not be queued.")
        text = payload.get("text", "")
        if not text.strip() and not payload.get("images"):
            raise QueueError(400, "There is nothing to queue.")
        if text.lstrip().startswith("/"):
            raise QueueError(400, "Slash commands cannot be queued. Send it when the reply finishes.")
        if len(text) > MAX_TEXT_CHARS:
            raise QueueError(413, "That message is too long to queue.")
        blob = json.dumps(payload)
        if len(blob) > MAX_ITEM_BYTES:
            raise QueueError(413, "That message and its attachments are too large to queue. Send it when the reply finishes.")

        def work(conn):
            self._expire(conn)
            existing = conn.execute("SELECT context_id FROM queue WHERE id=?", (item_id,)).fetchone()
            if existing:
                if existing[0] != context_id:
                    raise QueueError(409, "That message id is already in use.")
                return False
            count = conn.execute("SELECT COUNT(*) FROM queue WHERE context_id=?", (context_id,)).fetchone()[0]
            if count >= MAX_QUEUED:
                raise QueueError(429, f"The queue is full ({MAX_QUEUED} messages). Wait for one to send, or remove one.")
            seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM queue").fetchone()[0]
            conn.execute(
                "INSERT INTO queue (id, context_id, seq, created_at, text, payload, attachments) VALUES (?,?,?,?,?,?,?)",
                (item_id, context_id, seq, time.time(), text, blob, len(payload.get("images") or [])))
            return True
        created = self._run(work)
        return {"created": created}

    def edit(self, context_id: str, item_id: str, text: str) -> None:
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise QueueError(400, "That message could not be updated.")
        if text.lstrip().startswith("/"):
            raise QueueError(400, "Slash commands cannot be queued. Send it when the reply finishes.")

        def work(conn):
            row = conn.execute("SELECT payload FROM queue WHERE id=? AND context_id=?", (item_id, context_id)).fetchone()
            if not row:
                raise QueueError(409, "That message was already sent.")
            payload = json.loads(row[0])
            payload["text"] = text
            conn.execute("UPDATE queue SET text=?, payload=? WHERE id=?", (text, json.dumps(payload), item_id))
        self._run(work)

    def remove(self, context_id: str, item_id: str) -> bool:
        def work(conn):
            removed = conn.execute("DELETE FROM queue WHERE id=? AND context_id=?", (item_id, context_id)).rowcount > 0
            if conn.execute("SELECT 1 FROM queue WHERE context_id=? LIMIT 1", (context_id,)).fetchone() is None:
                conn.execute("DELETE FROM queue_state WHERE context_id=?", (context_id,))
            return removed
        return self._run(work)

    def take(self, context_id: str, item_id: str) -> dict | None:
        """Remove a message because the chat route is about to send it, and hand back the row so it can be restored.

        None when it is no longer queued (another window sent it). A paused queue refuses in the same transaction
        as the delete, so a send that raced a Stop or an error cannot slip a message through after the pause
        landed. Resume first, then send.
        """
        def work(conn):
            if self._state(conn, context_id)[0]:
                raise QueueError(409, "The queue is paused. Resume it to send this message.", code="queue_paused")
            row = conn.execute(
                "SELECT id, seq, created_at, text, payload, attachments FROM queue WHERE id=? AND context_id=?",
                (item_id, context_id)).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM queue WHERE id=?", (item_id,))
            if conn.execute("SELECT 1 FROM queue WHERE context_id=? LIMIT 1", (context_id,)).fetchone() is None:
                conn.execute("DELETE FROM queue_state WHERE context_id=?", (context_id,))
            return {"id": row[0], "seq": row[1], "created_at": row[2], "text": row[3], "payload": row[4], "attachments": row[5]}
        return self._run(work)

    def restore(self, context_id: str, taken: dict) -> None:
        """Put a taken message back in its original place (same id, same order) because the send did not happen."""
        self._run(lambda conn: conn.execute(
            "INSERT OR IGNORE INTO queue (id, context_id, seq, created_at, text, payload, attachments) VALUES (?,?,?,?,?,?,?)",
            (taken["id"], context_id, taken["seq"], taken["created_at"], taken["text"], taken["payload"], taken["attachments"])))

    def consume(self, context_id: str, item_id: str) -> bool:
        return self.take(context_id, item_id) is not None

    def clear(self, context_id: str) -> None:
        def work(conn):
            conn.execute("DELETE FROM queue WHERE context_id=?", (context_id,))
            conn.execute("DELETE FROM queue_state WHERE context_id=?", (context_id,))
        self._run(work)

    def pause(self, context_id: str, reason: str) -> None:
        self._run(lambda conn: conn.execute(
            "INSERT INTO queue_state (context_id, paused, reason) VALUES (?,1,?) "
            "ON CONFLICT(context_id) DO UPDATE SET paused=1, reason=excluded.reason", (context_id, reason)))

    def resume(self, context_id: str) -> None:
        self._run(lambda conn: conn.execute("DELETE FROM queue_state WHERE context_id=?", (context_id,)))

    def pause_if_queued(self, context_id: str, reason: str) -> None:
        """A stopped or failed turn holds back what the user queued behind it. Never raises: the turn's own ending comes first."""
        try:
            if self.snapshot(context_id)["items"]:
                self.pause(context_id, reason)
        except QueueError:
            pass


_default: MessageQueue | None = None
_default_lock = threading.Lock()


def get_queue() -> MessageQueue:
    global _default
    with _default_lock:
        if _default is None:
            from config import GATOR_DIR

            _default = MessageQueue(Path(GATOR_DIR) / "queue.db")
        return _default


def reset_queue(queue: MessageQueue | None = None) -> None:
    global _default
    with _default_lock:
        _default = queue
