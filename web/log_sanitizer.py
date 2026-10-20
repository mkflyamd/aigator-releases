"""Central scrubber for text that is persisted to logs, telemetry and user-visible status messages.

Always removed: secrets, the user's home directory, tenant IDs, internal hostnames.
Privacy mode also removes every file path, every GUID, MCP server names, and replaces
telemetry tool/skill identifiers (see ``tool_label``). Outcomes and counts are kept.
Privacy mode is on when AIGATOR_PRIVACY_MODE=1, or privacy_mode is true in config.json,
and defaults to on in packaged builds (AIGATOR_MANAGED_LOGGING=1) unless set to false.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_KEY_VALUE = re.compile(
    r"""(?ix)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd)
        (["']?\s*[:=]\s*["']?)([^\s"',&;]+)"""
)
_USER_DIR = re.compile(r"(?i)((?:[A-Za-z]:)?[\\/](?:Users|home)[\\/])[^\\/\s\"']+")
_GUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_GUID = re.compile(rf"(?i)\b{_GUID_PATTERN}\b")
_TENANT = re.compile(rf"(?i)(\btenant(?:[_ -]?id)?|\btid|microsoftonline\.com)([\"']?\s*[:=/]\s*[\"']?)({_GUID_PATTERN})")
_INTERNAL_HOST = re.compile(r"(?i)\b(?:[a-z0-9-]+\.)+(?:amd\.com|corp|local|internal|intranet|lan)\b")
_UNC_HOST = re.compile(r"\\\\[A-Za-z0-9._-]+(?=\\)")
_WIN_PATH = re.compile(r"[A-Za-z]:[\\/][^\s\"'<>|*?]*")
_POSIX_PATH = re.compile(r"(?<![\w:/.])/(?:[\w.@~-]+/)+[\w.@~-]*")
_TOOL_NAME = re.compile(r"\bmcp[_-]{1,2}[\w-]+", re.I)

_cached_privacy: bool | None = None


def privacy_mode() -> bool:
    global _cached_privacy
    env = os.environ.get("AIGATOR_PRIVACY_MODE")
    if env is not None:
        return env.strip().lower() in {"1", "true", "yes", "on"}
    if _cached_privacy is None:
        value = None
        try:
            import config

            value = config._read_config_file().get("privacy_mode")
        except Exception:
            pass
        _cached_privacy = bool(value) if value is not None else os.environ.get("AIGATOR_MANAGED_LOGGING") == "1"
    return _cached_privacy


def refresh_privacy_mode() -> None:
    """Re-read the privacy_mode setting after config.json changes."""
    global _cached_privacy
    _cached_privacy = None


def tool_label(name: str | None) -> str | None:
    """Tool, skill or MCP server identifier for telemetry: hidden in privacy mode."""
    return "<tool>" if privacy_mode() and name else name


def sanitize(text: str | None) -> str | None:
    if not text:
        return text
    home = str(Path.home())
    for variant in {home, home.replace("\\", "/")}:
        text = text.replace(variant, "~")
    text = _USER_DIR.sub(r"\1<user>", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)} [redacted]", text)
    text = _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
    text = _TENANT.sub(lambda m: f"{m.group(1)}{m.group(2)}<tenant>", text)
    text = _UNC_HOST.sub(r"\\\\<host>", text)
    text = _INTERNAL_HOST.sub("<host>", text)
    if privacy_mode():
        text = _GUID.sub("<id>", text)
        text = _TOOL_NAME.sub("<tool>", text)
        text = _WIN_PATH.sub("<path>", text)
        text = _POSIX_PATH.sub("<path>", text)
    return text
