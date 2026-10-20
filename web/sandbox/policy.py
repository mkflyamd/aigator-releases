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
    marketplace_allowed_tiers: tuple[str, ...] = ("Native", "Verified", "Community", "Mine")   # every tier is allowed until an admin policy file narrows it; Mine = zip or folder the user picks locally
    require_pinned_installs: bool = False   # True = no URL downloads except SHA-pinned catalog plugins
    approved_digests: tuple[str, ...] | None = None   # None = off; a list = only these package digests install
    blocked_data_flows: tuple[str, ...] = ()   # "source>destination" pairs; a draft is refused after data from source was read
    block_bundle_stdio_mcp: bool = False   # True = stdio MCP servers from marketplace bundles do not start (they run unsandboxed)

    def as_dict(self) -> dict:
        return asdict(self)


DEFAULT_POLICY = Policy()
FAIL_CLOSED_POLICY = Policy(code_runner="enabled", network="deny", filesystem="strict", require_sandbox=True,
                            saved_permissions="deny", marketplace_allowed_tiers=("Native", "Verified"),
                            require_pinned_installs=True, block_bundle_stdio_mcp=True)
_ALLOWED = {
    "code_runner": {"enabled", "disabled"},
    "network": {"ask", "deny"},
    "filesystem": {"ask", "strict"},
    "saved_permissions": {"allow", "deny"},
}
_TIERS = {"Native", "Verified", "Community", "Mine"}
FLOW_SOURCES = {"*", "email", "calendar", "contacts", "people", "teams", "onedrive", "sharepoint", "onenote",
                "jira", "confluence", "slack", "github", "web", "mcp"}
FLOW_DESTINATIONS = {"*", "email", "calendar", "teams", "slack", "jira"}

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
    unknown = set(data) - set(_ALLOWED) - {"require_sandbox", "marketplace_allowed_tiers", "require_pinned_installs",
                                                  "approved_digests", "blocked_data_flows", "block_bundle_stdio_mcp"}
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
    if "require_pinned_installs" in data:
        if not isinstance(data["require_pinned_installs"], bool):
            raise ValueError("require_pinned_installs must be true or false")
        values["require_pinned_installs"] = data["require_pinned_installs"]
    if "block_bundle_stdio_mcp" in data:
        if not isinstance(data["block_bundle_stdio_mcp"], bool):
            raise ValueError("block_bundle_stdio_mcp must be true or false")
        values["block_bundle_stdio_mcp"] = data["block_bundle_stdio_mcp"]
    if "marketplace_allowed_tiers" in data:
        tiers = data["marketplace_allowed_tiers"]
        if not isinstance(tiers, list) or not tiers or not all(isinstance(t, str) and t in _TIERS for t in tiers):
            raise ValueError("invalid value for marketplace_allowed_tiers")
        values["marketplace_allowed_tiers"] = tuple(tiers)
    if "approved_digests" in data:
        digests = data["approved_digests"]
        if not isinstance(digests, list) or not all(isinstance(d, str) and d for d in digests):
            raise ValueError("invalid value for approved_digests")
        values["approved_digests"] = tuple(digests)
    if "blocked_data_flows" in data:
        flows = data["blocked_data_flows"]
        if not isinstance(flows, list) or not all(isinstance(f, str) and f.count(">") == 1 for f in flows):
            raise ValueError("invalid value for blocked_data_flows")
        for flow in flows:
            source, destination = (part.strip() for part in flow.split(">"))
            if source not in FLOW_SOURCES or destination not in FLOW_DESTINATIONS:
                raise ValueError("invalid value for blocked_data_flows")
        values["blocked_data_flows"] = tuple(f.replace(" ", "") for f in flows)
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
