"""Slack self-DM adapter. Posts only to the user's own DM with themselves, only text that
starts with the crocodile marker, so Gator's own replies can never read back as a command. Slack message
ids are `ts` strings such as "1700000000.000200"; they are kept as strings and `float(ts)`
is the message time."""

from __future__ import annotations

import logging

from remote.channel import ChannelRefused, InboundMessage, require_autosend, slack_mrkdwn
from remote.commands import is_own_message
from remote.state import State

_log = logging.getLogger(__name__)

HISTORY_LIMIT = 10


def _api(endpoint: str, params: dict | None = None, method: str = "GET") -> dict:
    """Blocking. The Slack Web API with the stored user token."""
    from routes.slack import _slack_web_api

    return _slack_web_api(endpoint, params, method=method)


def _own_user_id() -> str:
    from skills.slack.mcp_client import _load_token

    stored = _load_token().get("user") or ""
    if stored:
        return stored
    return str(_api("auth.test").get("user_id") or "")


def _unescape(text: str) -> str:
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _epoch(ts: str) -> float:
    """Unix seconds from a Slack ts. An unreadable ts is 0.0, which the runner never runs untagged."""
    try:
        return float(ts)
    except (TypeError, ValueError):
        return 0.0


class SlackSelfDM:
    name = "slack"

    def __init__(self, channel_id: str | None = None, state: State | None = None):
        self._channel_id = channel_id
        self._state = state or State()
        self._verified: str | None = None

    def _resolve_channel(self) -> str:
        if self._channel_id:
            return self._channel_id
        own = _own_user_id()
        opened = _api("conversations.open", {"users": own}, method="POST") if own else {}
        channel = (opened.get("channel") or {}).get("id") if opened.get("ok") else None
        if not channel:
            raise RuntimeError(f"Slack could not open the self-DM: {opened.get('error', 'no user id')}")
        self._channel_id = str(channel)
        return self._channel_id

    def is_own_self_chat(self) -> bool:
        """True only for a one-to-one DM whose other member is the signed-in user. A positive
        answer is cached: a conversation's membership does not change."""
        try:
            channel = self._resolve_channel()
        except Exception as exc:
            _log.warning("Remote control could not find the Slack self-DM: %s", exc)
            return False
        if channel == self._verified:
            return True
        try:
            info = _api("conversations.info", {"channel": channel})
            own = _own_user_id()
        except Exception as exc:
            _log.warning("Remote control could not verify the Slack self-DM: %s", exc)
            return False
        details = info.get("channel") or {}
        if info.get("ok") and own and details.get("is_im") and details.get("user") == own:
            self._verified = channel
            return True
        return False

    def poll(self) -> list[InboundMessage]:
        channel = self._resolve_channel()
        data = _api("conversations.history", {"channel": channel, "limit": HISTORY_LIMIT})
        if not data.get("ok"):
            raise RuntimeError(f"Slack history failed: {data.get('error', 'unknown')}")
        own = _own_user_id()
        if not own:
            _log.warning("Remote control could not tell who the Slack user is, so it read no messages")
            return []
        return [
            InboundMessage(
                id=str(raw["ts"]),
                text=_unescape(raw.get("text") or "").strip(),
                created_at=_epoch(raw["ts"]),
                attachments=bool(raw.get("files")),
            )
            for raw in data.get("messages", [])
            if raw.get("ts")
            and raw.get("subtype") in (None, "file_share")
            and raw.get("user") == own
            and not raw.get("bot_id")
            and not raw.get("app_id")
        ]

    def post(self, text: str, reply_to: str | None = None) -> str:
        if not self.is_own_self_chat():
            _log.warning("Remote control refused to post: %s is not the own self-DM", self._channel_id)
            raise ChannelRefused("not the own self-DM")
        if not is_own_message(text):
            raise ChannelRefused("replies must start with the crocodile marker")
        require_autosend()
        sent = _api("chat.postMessage", {"channel": self._channel_id, "text": slack_mrkdwn(text)}, method="POST")
        if not sent.get("ok"):
            raise ChannelRefused(f"Slack error: {sent.get('error', 'unknown')}")
        message_id = str(sent.get("ts") or "")
        if message_id:
            self._state.record_post(self.name, message_id)
        return message_id
