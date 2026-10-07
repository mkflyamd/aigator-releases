"""Which data source a tool call touches, and which sources a tab has approved."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import shared


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    kind: str  # "data" or "web"


_NATIVE_SOURCES = {
    "email": "Outlook mail",
    "calendar": "Outlook calendar",
    "contacts": "Outlook contacts",
    "people": "the people directory",
    "teams": "Microsoft Teams",
    "onedrive": "SharePoint and OneDrive",
    "sharepoint": "SharePoint and OneDrive",
    "onenote": "OneNote",
    "m365-onenote": "OneNote",
    "jira": "Jira",
    "confluence": "Confluence",
    "slack": "Slack",
    "github": "GitHub",
}
_MCP_LABELS = {
    "mcp-google-workspace": "Google Workspace",
    "cloud-atlassian": "Atlassian (Jira and Confluence)",
}
_NOT_MCP_IDS = frozenset(_NATIVE_SOURCES) | {"_always_on", "_extension_setup"}
_WEB_TOOLS = frozenset({"fetch_webpage", "web_search"})
_DENY_WINDOW_S = 10.0


def _native_source(tool_name: str) -> Source | None:
    for skill_id, label in _NATIVE_SOURCES.items():
        if tool_name in shared.SKILL_TOOLS_MAP.get(skill_id, ()):
            return Source(key=f"data:{label}", label=label, kind="data")
    return None


def _mcp_source(tool_name: str) -> Source | None:
    if "__" not in tool_name:
        return None
    # An MCP server is registered under its own skill id plus smaller synthetic
    # groups (g-gmail, mcp-...-jira-read); the group holding the most tools is the server.
    best = None
    for skill_id, names in shared.SKILL_TOOLS_MAP.items():
        if skill_id in _NOT_MCP_IDS or tool_name not in names:
            continue
        if best is None or len(names) > len(shared.SKILL_TOOLS_MAP[best]):
            best = skill_id
    if best is None:
        return None
    label = _MCP_LABELS.get(best) or f"{best.removeprefix('mcp-')} (MCP server)"
    return Source(key=f"mcp:{best}", label=label, kind="data")


def source_for_call(tool_name: str, inputs: dict | None) -> Source | None:
    if tool_name == "fetch_webpage":
        host = (urlparse(str((inputs or {}).get("url", ""))).hostname or "").lower()
        if not host:
            return None
        return Source(key=f"web:{host}", label=f"the website {host}", kind="web")
    return _native_source(tool_name) or _mcp_source(tool_name)


def is_untrusted(tool_name: str) -> bool:
    return tool_name in _WEB_TOOLS or _native_source(tool_name) is not None or _mcp_source(tool_name) is not None


def prompt_for(source: Source, tool_name: str) -> dict:
    if source.kind == "web":
        action = f"AI Gator wants to open {source.label}, which this tab has not used yet. Allowed for this tab only."
    else:
        action = (
            f"AI Gator wants to read from {source.label} (tool: {tool_name}). "
            "This stays allowed until you close this tab."
        )
    return {
        "title": f"Allow access to {source.label}?",
        "action": action,
        "allow_label": "Allow for this tab",
        "deny_label": "Deny",
    }


_LOCK = threading.Lock()
_ALLOWED: set[tuple[str, str]] = set()
_DENIED: dict[tuple[str, str], float] = {}


def allow(context_id: str, key: str) -> None:
    with _LOCK:
        _ALLOWED.add((context_id, key))
        _DENIED.pop((context_id, key), None)


def is_allowed(context_id: str, key: str) -> bool:
    with _LOCK:
        return (context_id, key) in _ALLOWED


def deny(context_id: str, key: str) -> None:
    with _LOCK:
        _DENIED[(context_id, key)] = time.monotonic()


def recently_denied(context_id: str, key: str, window_s: float = _DENY_WINDOW_S) -> bool:
    with _LOCK:
        at = _DENIED.get((context_id, key))
    return at is not None and (time.monotonic() - at) < window_s


def end_for_tab(context_id: str) -> None:
    with _LOCK:
        _ALLOWED.difference_update({e for e in _ALLOWED if e[0] == context_id})
        for k in [k for k in _DENIED if k[0] == context_id]:
            del _DENIED[k]


def _reset() -> None:
    with _LOCK:
        _ALLOWED.clear()
        _DENIED.clear()
