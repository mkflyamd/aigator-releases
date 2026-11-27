"""The one remote-control window shared by Teams and Slack: armed for 12 hours, then off.

The deadline is a wall-clock time kept in the state file, so a restart neither extends nor
resets it, and a clock moved backwards counts as expired."""

from __future__ import annotations

import time
from typing import Callable

from remote.state import State

ARM_SECONDS = 12 * 3600.0
WARN_SECONDS = 15 * 60.0
CHANNELS = ("teams", "slack")


class Master:
    def __init__(self, state: State, clock: Callable[[], float] = time.time):
        self._state = state
        self._clock = clock

    def record(self) -> dict | None:
        """{armed_at, deadline}, or None when it was never armed or the stored record is unusable."""
        raw = self._state.master()
        if not raw:
            return None
        armed_at, deadline = raw.get("armed_at"), raw.get("deadline")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (armed_at, deadline)):
            return None
        return {"armed_at": float(armed_at), "deadline": min(float(deadline), float(armed_at) + ARM_SECONDS)}

    def active(self) -> bool:
        record = self.record()
        return record is not None and record["armed_at"] <= self._clock() < record["deadline"]

    def expired(self) -> bool:
        return self.record() is not None and not self.active()

    def remaining(self) -> float:
        record = self.record()
        return max(0.0, record["deadline"] - self._clock()) if record and self.active() else 0.0

    def arm(self) -> dict:
        """Starts a window unless one is running; a running window is never extended."""
        if self.active():
            return self.record()
        now = self._clock()
        record = {"armed_at": now, "deadline": now + ARM_SECONDS}
        self._state.set_master(record)
        for channel in CHANNELS:
            if self._state.disarmed(channel):
                self._state.set_disarmed(channel, False)
        return record

    def disarm(self) -> None:
        if self._state.master() is not None:
            self._state.set_master(None)
