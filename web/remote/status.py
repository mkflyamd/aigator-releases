"""What the Remote control switch shows, and the rules for starting and stopping the window."""

from __future__ import annotations

import time
from typing import Callable

from config import load_config
from relay import settings as relay_settings
from remote.master import CHANNELS, WARN_SECONDS, Master
from remote.settings import SWITCH_KEYS
from remote.state import State

WARN_HOUR_SECONDS = 3600.0
REASONS = {
    "not_set_up": "Turn on Teams or Slack in Settings first.",
    "replies_blocked_admin": "Your administrator has switched off replies to your own chat, so remote control cannot answer you.",
    "replies_off": "Replies to your own chat are off. Turn them on in Settings first.",
    "stopped_from_chat": "You stopped remote control from chat.",
    "expiring": "The time is up. Stopping your remote sessions.",
    "expired": "Remote control reached its 12 hour limit and turned off.",
}


def _enabled_channels(config: dict) -> list[str]:
    return [name for name, key in zip(CHANNELS, SWITCH_KEYS) if config.get(key)]


def blocker(config: dict | None = None) -> str | None:
    """Why remote control cannot start now, as a state name, or None."""
    config = load_config() if config is None else config
    if not _enabled_channels(config):
        return "not_set_up"
    if not relay_settings.admin_allows_self_chat_autosend():
        return "replies_blocked_admin"
    if not relay_settings.user_allows_self_chat_autosend():
        return "replies_off"
    return None


def reason(state: str) -> str | None:
    return REASONS.get(state)


def compute(state: State, clock: Callable[[], float] = time.time, config: dict | None = None) -> dict:
    config = load_config() if config is None else config
    master = Master(state, clock)
    record = master.record()
    enabled = _enabled_channels(config)
    window = master.active()
    channels = [
        {
            "name": name,
            "enabled": name in enabled,
            "armed": window and name in enabled and not state.disarmed(name),
        }
        for name in CHANNELS
    ]
    now = clock()
    if record is not None and not window:
        pending = any(state.channel_value(name, "expiry_handled") != record["deadline"] for name in enabled)
        name = "expiring" if pending else "expired"
    elif window:
        remaining = master.remaining()
        blocked = blocker(config)
        if blocked in ("replies_blocked_admin", "replies_off"):
            name = blocked
        elif not any(c["armed"] for c in channels):
            name = "stopped_from_chat" if enabled else "not_set_up"
        elif remaining <= WARN_SECONDS:
            name = "warn_15m"
        elif remaining <= WARN_HOUR_SECONDS:
            name = "warn_1h"
        else:
            name = "on"
    else:
        name = blocker(config) or "off"
    return {
        "state": name,
        "reason": reason(name),
        "channels": channels,
        "armed_at": record["armed_at"] if window else None,
        "expires_at": record["deadline"] if record is not None else None,
        "now": now,
    }


def arm(state: State, clock: Callable[[], float] = time.time) -> str | None:
    """Starts the window. Returns the state that refused it, or None when it is running."""
    blocked = blocker()
    if blocked:
        return blocked
    Master(state, clock).arm()
    return None


def restart(state: State, clock: Callable[[], float] = time.time) -> str | None:
    """Gives the window a fresh 12 hours. Returns the state that refused it, leaving the current
    window as it is, or None when the new window is running."""
    blocked = blocker()
    if blocked:
        return blocked
    Master(state, clock).restart()
    return None


def disarm(state: State, clock: Callable[[], float] = time.time) -> None:
    Master(state, clock).disarm()
