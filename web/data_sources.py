"""Which data source a tool call touches, and which sources a tab has approved."""
from __future__ import annotations

import re
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
    flow_id: str = ""  # id used by the admin blocked_data_flows policy


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
# Page content from a browser run: untrusted, but gated by the browser's own per-call card, not a source card.
_BROWSER_TOOLS = frozenset({"browser_task", "browser_navigate", "browser_search"})
_DENY_WINDOW_S = 10.0


def _native_source(tool_name: str) -> Source | None:
    for skill_id, label in _NATIVE_SOURCES.items():
        if tool_name in shared.SKILL_TOOLS_MAP.get(skill_id, ()):
            return Source(key=f"data:{label}", label=label, kind="data", flow_id=skill_id.removeprefix("m365-"))
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
    return Source(key=f"mcp:{best}", label=label, kind="data", flow_id="mcp")


def source_for_call(tool_name: str, inputs: dict | None) -> Source | None:
    if tool_name == "fetch_webpage":
        host = (urlparse(str((inputs or {}).get("url", ""))).hostname or "").lower()
        if not host:
            return None
        return Source(key=f"web:{host}", label=f"the website {host}", kind="web", flow_id="web")
    return _native_source(tool_name) or _mcp_source(tool_name)


def is_untrusted(tool_name: str) -> bool:
    return tool_name in _WEB_TOOLS or tool_name in _BROWSER_TOOLS or _native_source(tool_name) is not None or _mcp_source(tool_name) is not None


def mark_direct_data(tool_name: str, data):
    """Mark data fetched by the direct skill router before it goes into a user-role message."""
    if not is_untrusted(tool_name):
        return data
    import content_guard
    marked, _removed = content_guard.mark_untrusted(data if isinstance(data, dict) else {"result": data})
    return marked


_CARD_URL_MAX = 200


def prompt_for(source: Source, tool_name: str, inputs: dict | None = None) -> dict:
    if source.kind == "web":
        url = str((inputs or {}).get("url", ""))
        if len(url) > _CARD_URL_MAX:
            url = url[:_CARD_URL_MAX] + "..."
        shown = f" Address: {url}" if url else ""
        action = (f"AI Gator wants to open {source.label}, which this tab has not used yet.{shown} "
                  "Allowed for this tab only.")
    else:
        action = (
            f"AI Gator wants to use {source.label} (tool: {tool_name}). "
            "This stays allowed until you close this tab."
        )
    return {
        "title": f"Allow access to {source.label}?",
        "action": action,
        "allow_label": "Allow for this tab",
        "deny_label": "Deny",
    }


def draft_destination(draft_kind: str) -> str:
    """Integration a draft sends to, e.g. "email-reply" -> "email", "calendar-write" -> "calendar"."""
    return draft_kind.split("-", 1)[0]


def blocked_flow(source_ids, draft_kind: str) -> str | None:
    """Return the admin-blocked "source>destination" rule this draft would break, or None."""
    from sandbox.policy import load_policy

    destination = draft_destination(draft_kind)
    for rule in load_policy().blocked_data_flows:
        rule_source, rule_destination = rule.split(">")
        if rule_destination in ("*", destination) and (rule_source == "*" and source_ids or rule_source in source_ids):
            return rule
    return None


_SENSITIVE_MARKER = re.compile(
    r"\b(?:highly\s+confidential|confidential|internal\s+use\s+only|proprietary|amd\s+restricted)\b", re.I)
_SENSITIVE_FIELDS = ("subject", "body", "message", "comment", "description", "summary", "text")


def sensitivity_markers(data: dict) -> list[str]:
    """Classification words found in the draft text, so the approval card can warn the user."""
    found: dict[str, str] = {}
    for field in _SENSITIVE_FIELDS:
        value = data.get(field)
        if isinstance(value, str):
            for match in _SENSITIVE_MARKER.finditer(value):
                found.setdefault(match.group(0).lower(), match.group(0))
    return sorted(found.values(), key=str.lower)


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
