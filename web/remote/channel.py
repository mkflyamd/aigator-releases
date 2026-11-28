"""The channel interface. The runner depends on this only; Teams is the first adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from relay import settings


class ChannelRefused(Exception):
    """The adapter would not post. The message is for the log, never sent to the channel."""


class PostUncertain(ChannelRefused):
    """The post got no answer, so the chat may have received it. A caller never sends the same text again."""


class AutosendOff(ChannelRefused):
    """The auto-send switch is off, in the user's settings or by the administrator's policy."""


def require_autosend() -> None:
    """Every adapter calls this before it sends. It does not check who the recipient is."""
    if not settings.self_chat_autosend_allowed():
        raise AutosendOff("posting to your own chat is switched off")


def teams_html(text: str) -> str:
    """Agent markdown as Teams HTML, so `**bold**` and a leading `>` do not show as raw characters."""
    from skills._rich_text import _markdown_to_html, render

    return render("teams", _markdown_to_html(text)).content


def slack_mrkdwn(text: str) -> str:
    """Agent markdown as Slack mrkdwn, escaped for Slack."""
    from skills._rich_text import _markdown_to_html, render

    return render("slack", _markdown_to_html(text, mrkdwn=True)).content


@dataclass(frozen=True)
class InboundMessage:
    id: str
    text: str
    created_at: float  # epoch seconds; 0.0 when the channel gave no usable timestamp
    attachments: bool = False
    reply_to: str | None = None  # id of the message this one quote-replies to, when the channel says


class Channel(Protocol):
    name: str

    def poll(self) -> list[InboundMessage]:
        """Recent messages, newest first."""

    def poll_replies(self) -> list[InboundMessage]:
        """Replies, newest first, that arrive somewhere `poll` does not list them (a Slack thread), each
        returned once, with `reply_to` set. Empty where a reply is an ordinary message (a Teams quote-reply)."""

    def post(self, text: str, reply_to: str | None = None) -> str:
        """Post to the user's own chat only. Returns the new message id."""

    def is_own_self_chat(self) -> bool: ...
