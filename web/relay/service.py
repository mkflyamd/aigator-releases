"""The one relay this backend runs."""

from __future__ import annotations

import threading

from .core import Relay
from .terminal_adapter import TerminalAdapter

_lock = threading.Lock()
_relay: Relay | None = None


def get_relay() -> Relay:
    global _relay
    with _lock:
        if _relay is None:
            _relay = Relay()
            _relay.register(TerminalAdapter())
        return _relay
