"""The chat window: after `@gator hi`, untagged messages in the own chat count as commands until
WINDOW_SECONDS of quiet. Persisted per channel, so a restart neither forgets an open window nor
revives an expired one."""

from __future__ import annotations

from typing import Callable

from remote.commands import WINDOW_SECONDS
from remote.state import State


class ChatWindow:
    def __init__(self, channel: str, state: State, clock: Callable[[], float], seconds: float = WINDOW_SECONDS):
        self._channel = channel
        self._state = state
        self._clock = clock
        self._seconds = seconds
        if self.expired():
            state.clear_window(channel)

    def is_open(self) -> bool:
        window = self._state.window(self._channel)
        return window is not None and self._clock() < window[1]

    def expired(self) -> bool:
        window = self._state.window(self._channel)
        return window is not None and self._clock() >= window[1]

    def opened_at(self) -> float:
        window = self._state.window(self._channel)
        return window[0] if window else 0.0

    def open(self, message_time: float) -> bool:
        """`message_time` is the channel's timestamp of the greeting; messages older than it never count.
        Returns whether the chat was already open, in which case the greeting only extends it."""
        was_open = self.is_open()
        if was_open:
            self.extend()
            return True
        now = self._clock()
        self._state.set_window(self._channel, message_time if message_time > 0 else now, now + self._seconds)
        return False

    def extend(self) -> None:
        window = self._state.window(self._channel)
        if window is not None:
            self._state.set_window(self._channel, window[0], self._clock() + self._seconds)

    def close(self) -> None:
        self._state.clear_window(self._channel)
