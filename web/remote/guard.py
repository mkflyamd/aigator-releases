"""Human-inbound guard rails: armed flag, command rate limit, stop-all registry.

Components depend on this small interface only, so the cross-agent relay can share it
or replace it with an adapter later."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable

_log = logging.getLogger(__name__)

RATE_LIMIT = 20
RATE_WINDOW_SECONDS = 600.0
SLOW_NOTICE_SECONDS = 30.0


def limit(value: float | Callable[[], float]) -> float:
    """A limit that is either fixed or read fresh each time (from Settings)."""
    return value() if callable(value) else value


class Guard:
    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        rate_limit: int = RATE_LIMIT,
        rate_window: float = RATE_WINDOW_SECONDS,
    ):
        self._clock = clock
        self._rate_limit = rate_limit
        self._rate_window = rate_window
        self._armed = False
        self.epoch = 0
        self._events: deque[float] = deque()
        self._slow_notice_at: float | None = None
        self._dropped = 0
        self._stops: dict[str, Callable[[], None]] = {}
        self._lock = threading.Lock()

    def arm(self) -> None:
        self._armed = True

    def disarm(self) -> None:
        """`epoch` counts the times Remote control was turned off: work begun in an earlier epoch is not carried
        out in a later one, even when it is armed again by then."""
        if self._armed:
            self.epoch += 1
        self._armed = False
        with self._lock:
            self._dropped = 0

    @property
    def armed(self) -> bool:
        return self._armed

    def allow_command(self) -> bool:
        now = self._clock()
        with self._lock:
            while self._events and now - self._events[0] >= self._rate_window:
                self._events.popleft()
            if len(self._events) >= self._rate_limit:
                return False
            self._events.append(now)
            return True

    @property
    def armed_max_seconds(self) -> float:
        return limit(self._armed_max)

    def wait_seconds(self) -> float:
        """How long until the command rate window has room again."""
        now = self._clock()
        with self._lock:
            return max(0.0, self._rate_window - (now - self._events[0])) if self._events else 0.0

    def drop(self) -> int:
        """Count a dropped command. Returns how many to announce now, or 0 while a notice went out in the last
        30 seconds; the ones held back are counted in the next notice."""
        with self._lock:
            self._dropped += 1
        return self.dropped_to_announce()

    def dropped_to_announce(self) -> int:
        now = self._clock()
        with self._lock:
            if not self._dropped:
                return 0
            if self._slow_notice_at is not None and now - self._slow_notice_at < SLOW_NOTICE_SECONDS:
                return 0
            count, self._dropped, self._slow_notice_at = self._dropped, 0, now
            return count

    def register_stop(self, key: str, stop: Callable[[], None]) -> None:
        self._stops[key] = stop

    def unregister_stop(self, key: str) -> None:
        self._stops.pop(key, None)

    def stop_all(self) -> None:
        for key, stop in list(self._stops.items()):
            try:
                stop()
            except Exception:
                _log.warning("stop-all: could not stop %s", key, exc_info=True)
        self._stops.clear()
        self.disarm()
