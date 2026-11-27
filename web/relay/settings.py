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


def _load() -> dict:
    try:
        found = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _save(data: dict) -> None:
    try:
        agent_suspend._write_atomic(settings_file(), json.dumps(data))
    except OSError:
        logger.warning("could not save the relay settings", exc_info=True)


def admin_allows_messaging() -> bool:
    return policy.load_policy().agent_messaging == "allow"


def user_allows_messaging() -> bool:
    return _load().get("agent_messaging", True) is not False


def messaging_allowed() -> bool:
    return admin_allows_messaging() and user_allows_messaging()


def set_user_messaging(enabled: bool) -> None:
    with _lock:
        data = _load()
        data["agent_messaging"] = bool(enabled)
        _save(data)


def opted_out(endpoint_id: str) -> bool:
    opted = _load().get("opted_out", [])
    return isinstance(opted, list) and endpoint_id in opted


def set_opted_out(endpoint_id: str, value: bool) -> None:
    with _lock:
        data = _load()
        opted = {e for e in data.get("opted_out", []) if isinstance(e, str)}
        opted.add(endpoint_id) if value else opted.discard(endpoint_id)
        data["opted_out"] = sorted(opted)
        _save(data)
