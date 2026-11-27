"""The channel interface. The runner depends on this only; Teams is the first adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from relay import settings


class ChannelRefused(Exception):
    """The adapter would not post. The message is for the log, never sent to the channel."""


class AutosendOff(ChannelRefused):
    """The auto-send switch is off, in the user's settings or by the administrator's policy."""


def require_autosend() -> None:
    """Every adapter calls this before it sends. It does not check who the recipient is."""
    if not settings.self_chat_autosend_allowed():
        raise AutosendOff("posting to your own chat is switched off")


@dataclass(frozen=True)
class InboundMessage:
    id: str
    text: str
    created_at: float  # epoch seconds; 0.0 when the channel gave no usable timestamp


class Channel(Protocol):
    name: str

    def poll(self) -> list[InboundMessage]:
        """Recent messages, newest first."""

    def post(self, text: str, reply_to: str | None = None) -> str:
        """Post to the user's own chat only. Returns the new message id."""

    def is_own_self_chat(self) -> bool: ...
