"""What the user and the administrator allow. The admin policy always wins."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import agent_suspend
from sandbox import policy

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def settings_file() -> Path:
    return agent_suspend.STATE_FILE.parent / "relay" / "settings.json"


def _load() -> dict | None:
    """No file yet means the defaults. A file that exists but cannot be trusted returns None:
    callers then deny, because it may hold opt-outs the user relied on."""
    try:
        text = settings_file().read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return None
    try:
        found = json.loads(text)
    except ValueError:
        return None
    if not isinstance(found, dict):
        return None
    opted = found.get("opted_out", [])
    for key in ("agent_messaging", "self_chat_autosend"):
        if key in found and not isinstance(found[key], bool):
            return None
    if not isinstance(opted, list) or not all(isinstance(e, str) for e in opted):
        return None
    return found


def _save(data: dict) -> None:
    try:
        agent_suspend._write_atomic(settings_file(), json.dumps(data))
    except OSError:
        logger.warning("could not save the relay settings", exc_info=True)


def admin_allows_messaging() -> bool:
    return policy.load_policy().agent_messaging == "allow"


def user_allows_messaging() -> bool:
    data = _load()
    return data is not None and data.get("agent_messaging", True) is not False


def messaging_allowed() -> bool:
    return admin_allows_messaging() and user_allows_messaging()


def set_user_messaging(enabled: bool) -> None:
    """The user's own switch: it also repairs a file that could not be trusted."""
    with _lock:
        data = _load() or {}
        data["agent_messaging"] = bool(enabled)
        _save(data)


def admin_allows_self_chat_autosend() -> bool:
    return policy.load_policy().self_chat_autosend == "allow"


def user_allows_self_chat_autosend() -> bool:
    data = _load()
    return data is not None and data.get("self_chat_autosend", False) is True


def self_chat_autosend_allowed() -> bool:
    """True only when the administrator and the user both allow Gator to post to the user's own
    Teams/Slack self-chat without asking. Off by default. Anything else stays draft-only."""
    return admin_allows_self_chat_autosend() and user_allows_self_chat_autosend()


def set_user_self_chat_autosend(enabled: bool) -> None:
    with _lock:
        data = _load()
        if data is None:
            data = {"agent_messaging": False}
        data["self_chat_autosend"] = bool(enabled)
        _save(data)


def opted_out(endpoint_id: str) -> bool:
    data = _load()
    return data is None or endpoint_id in data.get("opted_out", [])


def set_opted_out(endpoint_id: str, value: bool) -> None:
    with _lock:
        data = _load()
        if data is None:
            data = {"agent_messaging": False}
        opted = set(data.get("opted_out", []))
        opted.add(endpoint_id) if value else opted.discard(endpoint_id)
        data["opted_out"] = sorted(opted)
        _save(data)
