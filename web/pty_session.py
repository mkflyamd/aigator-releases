"""A PTY session that owns its own reader and output buffer.

The reader thread starts with the session and runs until the process ends, so
output is captured whether or not a viewer is connected. A WebSocket handler
only subscribes and reads from a sequence number; it never touches the PTY.
"""

import asyncio
import bisect
import logging
import re
import threading
import time

logger = logging.getLogger(__name__)

PTY_BUF_MAX = 5000  # max output chunks retained per session
PTY_SIZES_MAX = 2000  # max recorded resizes retained per session

# An escape sequence that has started but not ended at the end of the text read so far.
# A sequence split across two chunks prints its tail as plain text when the replay starts
# at the second chunk; holding the unfinished part back keeps every chunk boundary clean.
_UNFINISHED_ESCAPE = re.compile(
    r"\x1b(?:"
    r"|\[[0-?]*[ -/]*"  # CSI still missing its final byte
    r"|[ -/]+"  # ESC plus intermediates, e.g. ESC ( before the charset
    r"|[\]PX^_][^\x07\x1b]*(?:\x1b)?"  # OSC/DCS/SOS/PM/APC body still missing its terminator
    r")\Z"
)
_HOLD_MAX = 4096  # an unfinished sequence longer than this is not held back
_HOLD_FLUSH_SECONDS = 0.05  # a held-back tail (a lone ESC) is released after this long


def _complete_prefix_length(text: str) -> int:
    """Length of the part of text that does not end inside an escape sequence."""
    start = max(0, len(text) - _HOLD_MAX)
    if "\x1b" not in text[start:]:
        return len(text)
    match = _UNFINISHED_ESCAPE.search(text, start)
    return match.start() if match else len(text)


class PtySession:
    def __init__(
        self,
        pty,
        max_chunks: int = PTY_BUF_MAX,
        start_offset: int = 0,
        initial_size: tuple[int, int] | None = None,
    ):
        self.pty = pty
        self.done = False
        # When this PTY (or, for an adopted one, its backend-side wrapper) came
        # into being. Agent handoff uses it to ignore transcripts that predate
        # the session.
        self.created_at = time.time()
        self.meta: dict[str, str] | None = None
        # ws_clients / ws_disconnected_at drive is_pty_viewed(): a server is only
        # protected from the idle reaper while its terminal is actually on-screen
        # (a live WebSocket), NOT merely while the attach process exists. Fresh
        # sessions start "recently seen" so the reaper's normal last_activity
        # grace covers the pre-connect window.
        self.ws_clients = 0
        # Connections whose tab reported itself not visible (a background tab). A
        # client that never reports visibility is counted as viewing.
        self.ws_hidden: set = set()
        # The viewer whose window size the PTY follows: the last one to attach or type.
        self.size_owner = None
        # When a person last typed into this terminal (0 = never). Input Gator injects itself
        # does not count, so a message is never pasted over what the user is typing.
        self.last_user_input = 0.0
        self.ws_disconnected_at = time.time()
        self._max_chunks = max_chunks
        # Positions are absolute character offsets, not chunk indexes, so a
        # buffer rebuilt from another source (the PTY host) keeps the same
        # numbering. _starts[i] is the offset of _chunks[i]'s first character.
        self._chunks: list[str] = []
        self._starts: list[int] = []
        self._end = start_offset
        # Output read but not yet stored because it ends inside an escape sequence.
        self._held = ""
        self._held_gen = 0
        self._lock = threading.Lock()
        self._caught_up = threading.Condition(self._lock)
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []
        # Every size the PTY has had, as (n, offset, cols, rows): the stream from offset on
        # was drawn for that size. A replay needs them to lay the output out as it was drawn.
        self._sizes: list[tuple[int, int, int, int]] = []
        self._size_n = 0
        if initial_size:
            self._record_size_locked(start_offset, *initial_size)
        # A mirror of a PTY in another process learns that PTY's sizes from the host.
        set_listener = getattr(pty, "set_size_listener", None)
        self._sizes_come_from_host = set_listener is not None
        if set_listener:
            set_listener(self._record_remote_size)
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
                self._release_held_locked()
                self.done = True
                self._caught_up.notify_all()
            self._notify()

    def _append(self, data: str) -> None:
        with self._lock:
            text = self._held + data
            cut = _complete_prefix_length(text)
            self._held = text[cut:]
            self._held_gen += 1
            gen = self._held_gen
            if cut:
                self._store_locked(text[:cut])
            self._caught_up.notify_all()
            held = bool(self._held)
        if held:
            timer = threading.Timer(_HOLD_FLUSH_SECONDS, self._flush_held, (gen,))
            timer.daemon = True
            timer.start()
        self._notify()

    def _flush_held(self, gen: int) -> None:
        with self._lock:
            if gen != self._held_gen or not self._held:
                return
            self._release_held_locked()
            self._caught_up.notify_all()
        self._notify()

    def _release_held_locked(self) -> None:
        if self._held:
            self._store_locked(self._held)
            self._held = ""
            self._held_gen += 1

    def _store_locked(self, text: str) -> None:
        self._chunks.append(text)
        self._starts.append(self._end)
        self._end += len(text)
        excess = len(self._chunks) - self._max_chunks
        if excess > 0:
            del self._chunks[:excess]
            del self._starts[:excess]
            self._prune_sizes_locked()

    def _record_size_locked(self, offset: int, cols: int, rows: int) -> bool:
        if self._sizes and self._sizes[-1][2:] == (cols, rows):
            return False
        self._size_n += 1
        self._sizes.append((self._size_n, offset, cols, rows))
        self._prune_sizes_locked()
        return True

    def _prune_sizes_locked(self) -> None:
        # Keep the last size from before the retained window: it is the size the window starts at.
        first = self._starts[0] if self._starts else self._end
        keep_from = 0
        while keep_from + 1 < len(self._sizes) and self._sizes[keep_from + 1][1] <= first:
            keep_from += 1
        keep_from = max(keep_from, len(self._sizes) - PTY_SIZES_MAX)
        if keep_from:
            del self._sizes[:keep_from]

    def _record_remote_size(self, offset: int, cols: int, rows: int) -> None:
        with self._lock:
            if self._sizes and offset < self._sizes[-1][1]:
                return
            recorded = self._record_size_locked(offset, cols, rows)
            if recorded:
                self._caught_up.notify_all()
        if recorded:
            self._notify()

    def size_at(self, offset: int) -> tuple[int, int] | None:
        """The (cols, rows) the stream was drawn for at this offset."""
        with self._lock:
            size = None
            for _, off, cols, rows in self._sizes:
                if off > offset:
                    break
                size = (cols, rows)
            return size

    def size_events(self, after: int, upto: int) -> list[tuple[int, int, int]]:
        """(offset, cols, rows) for every resize strictly between after and upto."""
        with self._lock:
            return [
                (off, cols, rows)
                for _, off, cols, rows in self._sizes
                if after < off < upto
            ]

    def sizes_after(self, n: int) -> list[tuple[int, int, int, int]]:
        """(n, offset, cols, rows) for every recorded resize newer than n."""
        with self._lock:
            return [s for s in self._sizes if s[0] > n]

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
        if self._sizes_come_from_host:
            return
        with self._lock:
            recorded = self._record_size_locked(self._end, cols, rows)
            if recorded:
                self._caught_up.notify_all()
        if recorded:
            self._notify()

    def isalive(self) -> bool:
        return self.pty.isalive()

    def close(self) -> None:
        self.pty.close()
