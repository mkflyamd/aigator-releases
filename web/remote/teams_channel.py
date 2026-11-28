"""Teams "Chat with yourself" adapter. Posts only to that one chat, only text that starts
with "[Gator", so Gator's own replies can never read back as a command."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from remote.channel import ChannelRefused, InboundMessage, require_autosend, teams_html
from remote.commands import SYSTEM_PREFIX
from remote.state import State

_log = logging.getLogger(__name__)

SELF_CHAT_ID = "48:notes"
_FRACTION = re.compile(r"(\.\d{6})\d+")
_QUOTE = re.compile(
    r"<blockquote\b[^>]*itemtype=[\"']http://schema\.skype\.com/Reply[\"'][^>]*>.*?</blockquote>",
    re.IGNORECASE | re.DOTALL,
)
_ITEM_ID = re.compile(r"itemid=[\"']([^\"']+)[\"']", re.IGNORECASE)


def fetch_messages(chat_id: str) -> list[dict]:
    """Blocking. Recent messages of one chat, newest first, as the Teams route returns them."""
    from routes.teams import _get_my_mri, _get_my_name, _get_skype_module, _normalize_skype_messages

    skype = _get_skype_module()
    skype_token, messaging_service = skype.get_auth()
    raw, _ = skype.read_messages(chat_id, skype_token, messaging_service, limit=10)
    return _normalize_skype_messages(raw, _get_my_mri(), _get_my_name())


def send_message(chat_id: str, content: str) -> str:
    """Blocking. Sends through the same route the Teams pane uses; returns the message id."""
    from routes.teams import TeamsSendRequest, tp_teams_send

    return str(tp_teams_send(chat_id, TeamsSendRequest(message=content)).get("message_id") or "")


def _epoch(composetime: str) -> float:
    """Unix seconds. A missing or unreadable time is 0.0, which the runner never runs untagged."""
    if not composetime:
        return 0.0
    try:
        stamp = datetime.fromisoformat(_FRACTION.sub(r"\1", composetime.replace("Z", "+00:00")))
    except ValueError:
        return 0.0
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def _quoted_id(body_html: str) -> str | None:
    """The id of the message a Teams quote-reply is answering, or None when the message quotes nothing."""
    match = _QUOTE.search(body_html)
    found = _ITEM_ID.search(match.group(0)) if match else None
    return found.group(1) if found else None


def _text(raw: dict) -> str:
    """The message as typed. A quote-reply carries the quoted message and its sender as a blockquote
    in front of the reply; that is not part of the command."""
    from skills._m365.helpers import html_to_text

    body_html = _QUOTE.sub("", raw.get("body_html") or "")
    typed = html_to_text(body_html).strip() if body_html.strip() else ""
    return typed or ("" if _QUOTE.search(raw.get("body_html") or "") else (raw.get("body") or "").strip())


class TeamsSelfChat:
    name = "teams"

    def __init__(self, chat_id: str = SELF_CHAT_ID, state: State | None = None):
        self._chat_id = chat_id
        self._state = state or State()

    def is_own_self_chat(self) -> bool:
        return self._chat_id == SELF_CHAT_ID

    def poll(self) -> list[InboundMessage]:
        return [
            InboundMessage(
                id=str(raw.get("id", "")),
                text=_text(raw),
                created_at=_epoch(raw.get("created_at", "")),
                attachments=bool(raw.get("attachments")),
                reply_to=_quoted_id(raw.get("body_html") or ""),
            )
            for raw in fetch_messages(self._chat_id)
            if raw.get("message_type") == "message"
        ]

    def poll_replies(self) -> list[InboundMessage]:
        return []

    def post(self, text: str, reply_to: str | None = None) -> str:
        if not self.is_own_self_chat():
            _log.warning("Remote control refused to post: %s is not the own self-chat", self._chat_id)
            raise ChannelRefused("not the own self-chat")
        if not text.lstrip().startswith(SYSTEM_PREFIX):
            raise ChannelRefused(f"replies must start with {SYSTEM_PREFIX}")
        require_autosend()
        content = teams_html(text)
        try:
            message_id = send_message(self._chat_id, content)
        except Exception as exc:
            raise ChannelRefused(str(exc)) from exc
        if message_id:
            self._state.record_post(self.name, message_id)
        return message_id
