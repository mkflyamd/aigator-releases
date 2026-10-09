"""Machine-wide, admin-controlled sandbox policy.

One JSON file, read on each run (mtime cached):
  Windows  %ProgramData%\\AIGator\\sandbox-policy.json  (inherits the admin-only ProgramData ACL; not checked)
  macOS    /Library/Application Support/AIGator/sandbox-policy.json
  Linux    /etc/aigator/sandbox-policy.json
Missing file: defaults. Present but unreadable, invalid, or (POSIX) not
root-owned or group/world-writable: fail closed (network deny, filesystem
strict, sandbox required), logged once per reason.
"""
from __future__ import annotations

import json
import logging
import os
import stat
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Policy:
    code_runner: str = "enabled"   # enabled | disabled
    network: str = "ask"           # ask | deny
    filesystem: str = "ask"        # ask | strict
    require_sandbox: bool = False
    saved_permissions: str = "allow"   # allow | deny

    def as_dict(self) -> dict:
        return asdict(self)


DEFAULT_POLICY = Policy()
FAIL_CLOSED_POLICY = Policy(code_runner="enabled", network="deny", filesystem="strict", require_sandbox=True,
                            saved_permissions="deny")
_ALLOWED = {
    "code_runner": {"enabled", "disabled"},
    "network": {"ask", "deny"},
    "filesystem": {"ask", "strict"},
    "saved_permissions": {"allow", "deny"},
}

_LOCK = threading.Lock()
_CACHE: tuple[tuple, Policy] | None = None
_LOGGED: set[str] = set()


def platform_policy_path(platform: str | None = None) -> Path:
    platform = platform or sys.platform
    if platform == "win32":
        return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "AIGator" / "sandbox-policy.json"
    if platform == "darwin":
        return Path("/Library/Application Support/AIGator/sandbox-policy.json")
    return Path("/etc/aigator/sandbox-policy.json")


def policy_path() -> Path:
    """The policy file for this OS (tests replace this function)."""
    return platform_policy_path()


def _is_posix() -> bool:
    return os.name == "posix"


def _posix_owner_ok(st) -> bool:
    return st.st_uid == 0 and not (st.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def _fail_closed(reason: str) -> Policy:
    if reason not in _LOGGED:
        _LOGGED.add(reason)
        _log.error("sandbox policy file %s; failing closed (network deny, filesystem strict, sandbox required)", reason)
    return FAIL_CLOSED_POLICY


def parse_policy(text: str) -> Policy:
    """Strict parse. Raises ValueError for anything but a known-good policy."""
    try:
        data = json.loads(text)
    except RecursionError as exc:  # hostile deeply nested JSON
        raise ValueError("policy is nested too deeply") from exc
    if not isinstance(data, dict):
        raise ValueError("policy must be a JSON object")
    unknown = set(data) - set(_ALLOWED) - {"require_sandbox"}
    if unknown:  # a typo must not silently select the weakest default
        raise ValueError("policy has unknown keys")
    values: dict = {}
    for key, allowed in _ALLOWED.items():
        if key in data:
            value = data[key]
            if not isinstance(value, str) or value not in allowed:
                raise ValueError(f"invalid value for {key}")
            values[key] = value
    if "require_sandbox" in data:
        if not isinstance(data["require_sandbox"], bool):
            raise ValueError("require_sandbox must be true or false")
        values["require_sandbox"] = data["require_sandbox"]
    return Policy(**values)


def load_policy() -> Policy:
    global _CACHE
    path = policy_path()
    try:
        st = path.stat()
    except FileNotFoundError:
        return DEFAULT_POLICY
    except OSError as exc:
        return _fail_closed(f"is unreadable ({type(exc).__name__})")
    if _is_posix() and not _posix_owner_ok(st):
        return _fail_closed("is not root-owned or is group/world-writable")
    stamp = (str(path), st.st_mtime_ns, st.st_size)
    with _LOCK:
        if _CACHE is not None and _CACHE[0] == stamp:
            return _CACHE[1]
    try:
        policy = parse_policy(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return _fail_closed(f"is invalid ({type(exc).__name__})")
    with _LOCK:
        _CACHE = (stamp, policy)
    return policy


def _reset_cache() -> None:
    global _CACHE
    with _LOCK:
        _CACHE = None
    _LOGGED.clear()
