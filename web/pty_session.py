"""A PTY session that owns its own reader and output buffer.

The reader thread starts with the session and runs until the process ends, so
output is captured whether or not a viewer is connected. A WebSocket handler
only subscribes and reads from a sequence number; it never touches the PTY.
"""

import asyncio
import bisect
import logging
import threading
import time

logger = logging.getLogger(__name__)

PTY_BUF_MAX = 5000  # max output chunks retained per session


class PtySession:
    def __init__(
        self, pty, max_chunks: int = PTY_BUF_MAX, start_offset: int = 0
    ):
        self.pty = pty
        self.done = False
        # ws_clients / ws_disconnected_at drive is_pty_viewed(): a server is only
        # protected from the idle reaper while its terminal is actually on-screen
        # (a live WebSocket), NOT merely while the attach process exists. Fresh
        # sessions start "recently seen" so the reaper's normal last_activity
        # grace covers the pre-connect window.
        self.ws_clients = 0
        self.ws_disconnected_at = time.time()
        self._max_chunks = max_chunks
        # Positions are absolute character offsets, not chunk indexes, so a
        # buffer rebuilt from another source (the PTY host) keeps the same
        # numbering. _starts[i] is the offset of _chunks[i]'s first character.
        self._chunks: list[str] = []
        self._starts: list[int] = []
        self._end = start_offset
        self._lock = threading.Lock()
        self._caught_up = threading.Condition(self._lock)
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []
        self._reader = threading.Thread(
            target=self._read_loop, name="pty-reader", daemon=True
        )
        self._reader.start()

    def _read_loop(self) -> None:
        try:
            while self.pty.isalive():
                try:
                    data = self.pty.read(4096)
                except (EOFError, OSError):
                    break
                if not data:
                    break
                self._append(data)
        except Exception:
            logger.exception("pty reader failed")
        finally:
            with self._lock:
                self.done = True
                self._caught_up.notify_all()
            self._notify()

    def _append(self, data: str) -> None:
        with self._lock:
            self._chunks.append(data)
            self._starts.append(self._end)
            self._end += len(data)
            excess = len(self._chunks) - self._max_chunks
            if excess > 0:
                del self._chunks[:excess]
                del self._starts[:excess]
            self._caught_up.notify_all()
        self._notify()

    def wait_for_offset(self, offset: int, timeout: float) -> bool:
        """Block until the buffer reaches offset (or the process ends)."""
        with self._caught_up:
            return self._caught_up.wait_for(
                lambda: self._end >= offset or self.done, timeout
            )

    def _notify(self) -> None:
        with self._lock:
            subs = list(self._subs)
        for loop, event in subs:
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                pass  # that viewer's event loop is already closed

    @property
    def first_offset(self) -> int:
        """Offset of the oldest retained character."""
        with self._lock:
            return self._starts[0] if self._starts else self._end

    def read_from(self, offset: int) -> tuple[str, int]:
        """Return (output at or after offset, end offset). An offset older than
        the retained window starts at the oldest retained character."""
        with self._lock:
            if not self._chunks or offset >= self._end:
                return "", self._end
            offset = max(offset, self._starts[0])
            i = bisect.bisect_right(self._starts, offset) - 1
            head = self._chunks[i][offset - self._starts[i] :]
            return head + "".join(self._chunks[i + 1 :]), self._end

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Event:
        """Event that is set whenever new output arrives or the process ends."""
        event = asyncio.Event()
        with self._lock:
            self._subs.append((loop, event))
        return event

    def unsubscribe(self, event: asyncio.Event) -> None:
        with self._lock:
            self._subs = [s for s in self._subs if s[1] is not event]

    def write(self, data: str) -> None:
        self.pty.write(data)

    def resize(self, cols: int, rows: int) -> None:
        self.pty.resize(cols, rows)

    def isalive(self) -> bool:
        return self.pty.isalive()

    def close(self) -> None:
        self.pty.close()
