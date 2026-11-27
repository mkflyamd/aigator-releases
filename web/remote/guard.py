"""Human-inbound guard rails: absolute arm cap, command rate limit, stop-all registry.

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
ARMED_MAX_SECONDS = 24 * 3600.0


def limit(value: float | Callable[[], float]) -> float:
    """A limit that is either fixed or read fresh each time (from Settings)."""
    return value() if callable(value) else value


class Guard:
    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        rate_limit: int = RATE_LIMIT,
        rate_window: float = RATE_WINDOW_SECONDS,
        armed_max_seconds: float | Callable[[], float] = ARMED_MAX_SECONDS,
    ):
        self._clock = clock
        self._rate_limit = rate_limit
        self._rate_window = rate_window
        self._armed_max = armed_max_seconds
        self._armed_at: float | None = None
        self._events: deque[float] = deque()
        self._slow_notice_at: float | None = None
        self._stops: dict[str, Callable[[], None]] = {}
        self._lock = threading.Lock()

    def arm(self) -> None:
        self._armed_at = self._clock()

    def disarm(self) -> None:
        self._armed_at = None

    def expired(self) -> bool:
        return self._armed_at is not None and self._clock() - self._armed_at >= limit(self._armed_max)

    @property
    def armed(self) -> bool:
        return self._armed_at is not None and not self.expired()

    def allow_command(self) -> bool:
        now = self._clock()
        with self._lock:
            while self._events and now - self._events[0] >= self._rate_window:
                self._events.popleft()
            if len(self._events) >= self._rate_limit:
                return False
            self._events.append(now)
            return True

    def slow_down_due(self) -> bool:
        """True once per rate window, so a flood gets one notice rather than one per command."""
        now = self._clock()
        if self._slow_notice_at is not None and now - self._slow_notice_at < self._rate_window:
            return False
        self._slow_notice_at = now
        return True

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
