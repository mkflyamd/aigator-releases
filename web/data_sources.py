"""Which data source a tool call touches, and which sources a tab has approved."""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import shared
from permissions import actions


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    kind: str  # "data" or "web"
    flow_id: str = ""  # id used by the admin blocked_data_flows policy
    action: str = ""  # permissions.actions type the grant is filed under; "" for websites
    per_call: bool = False  # True = no tab or saved grant exists, every call gets its own card


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
}
_NOT_MCP_IDS = frozenset(_NATIVE_SOURCES) | {"_always_on", "_extension_setup"}
_WEB_TOOLS = frozenset({"fetch_webpage", "web_search"})
# Page content from a browser run: untrusted, but gated by the browser's own per-call card, not a source card.
_BROWSER_TOOLS = frozenset({"browser_task", "browser_navigate", "browser_search"})
_DENY_WINDOW_S = 10.0


def _data_source(prefix: str, label: str, flow_id: str, gate: str | None) -> Source:
    if gate is None:
        return Source(key=f"{prefix}:{actions.IRREVERSIBLE}", label=label, kind="data", flow_id=flow_id,
                      action=actions.IRREVERSIBLE, per_call=True)
    return Source(key=f"{prefix}:{gate}", label=label, kind="data", flow_id=flow_id, action=gate)


def _native_source(tool_name: str, inputs: dict | None = None) -> Source | None:
    for skill_id, label in _NATIVE_SOURCES.items():
        if tool_name in shared.SKILL_TOOLS_MAP.get(skill_id, ()):
            return _data_source(f"data:{label}", label, skill_id.removeprefix("m365-"),
                                actions.gate_action(tool_name, inputs))
    return None


def _mcp_gate(tool_name: str, inputs: dict | None) -> str | None:
    """The action type an MCP call is filed under. Only a tool the server says is read-only, or one that is parked
    as an approval card, can be remembered; everything else asks on every call."""
    classify = shared.MCP_TOOL_CLASSIFIERS.get(tool_name)
    kind = classify(inputs or {}) if classify else "other"
    return {"read": actions.READ, "draft": actions.WRITE_PRIVATE}.get(kind)


def _mcp_source(tool_name: str, inputs: dict | None = None) -> Source | None:
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
    return _data_source(f"mcp:{best}", label, "mcp", _mcp_gate(tool_name, inputs))


# Tools that run a command, start a sign-in or probe a server on the model's say-so. Each call gets its own card and is
# refused in an unattended run. tool -> (label, card title, what the call does).
_PER_CALL_TOOLS = {
    "connect_mcp_server": (
        "an MCP server connection",
        "Connect this MCP server?",
        "connect an MCP server. A local command is started on this computer with your access, and a web address "
        "receives any credential given here",
    ),
    "extension_setup__test_connection": (
        "the extension setup",
        "Test this connection?",
        "test the connection filled in on the setup form. This starts the command or contacts the address entered there",
    ),
    "extension_setup__start_oauth_flow": (
        "the extension setup",
        "Start this sign-in?",
        "start a sign-in with the server at the address below",
    ),
}
_HIDDEN_ON_CARD = {"connect_mcp_server": frozenset({"auth_value"})}
URL_TOOLS = frozenset({"fetch_webpage", "extension_setup__fetch_doc"})


def _is_public_image_fetch(tool_name: str, inputs: dict | None) -> bool:
    """fetch_image reaches Microsoft, Teams and Slack with the user's own sign-in; any other address is a website."""
    if tool_name != "fetch_image":
        return False
    inputs = inputs or {}
    url = str(inputs.get("url") or "")
    if not url.startswith(("http://", "https://")) or (inputs.get("page_id") and inputs.get("filename")):
        return False
    from skills.fetch_image.tools import _detect_source
    return _detect_source(url) == "auto"


def fetches_website(tool_name: str, inputs: dict | None) -> bool:
    return tool_name in URL_TOOLS or _is_public_image_fetch(tool_name, inputs)


def source_for_call(tool_name: str, inputs: dict | None) -> Source | None:
    if fetches_website(tool_name, inputs):
        host = (urlparse(str((inputs or {}).get("url", ""))).hostname or "").lower()
        if not host:
            return None
        return Source(key=f"web:{host}", label=f"the website {host}", kind="web", flow_id="web")
    if tool_name in _PER_CALL_TOOLS:
        return Source(key=f"setup:{tool_name}", label=_PER_CALL_TOOLS[tool_name][0], kind="data",
                      action=actions.IRREVERSIBLE, per_call=True)
    return _native_source(tool_name, inputs) or _mcp_source(tool_name, inputs)


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


_STAYS_ALLOWED = "This stays allowed until you close this tab."


_CARD_VALUE_MAX = 1000
_CARD_KEY_MAX = 100
_CONTROL_CHARS = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u2028\u2029\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u061c\u180e\u00ad]")


def _schema_keys(tool_name: str) -> frozenset | None:
    """The arguments a built-in tool declares. Anything else the model adds is dropped before the tool runs, so it
    stays off the card. None when the tool declares none, or is an MCP tool whose server receives every argument."""
    if "__" in tool_name and not tool_name.startswith("extension_setup__"):
        return None
    for tool in shared.TOOLS:
        if tool.get("name") == tool_name:
            props = (tool.get("input_schema") or {}).get("properties")
            return frozenset(props) if isinstance(props, dict) and props else None
    return None


def _call_details(inputs: dict | None, tool_name: str = "") -> str:
    """The call's arguments for the approval card, on one line. Each value is cut on its own, so a long value cannot
    push a later argument such as the recipient out of sight."""
    if not inputs:
        return ""
    declared = _schema_keys(tool_name) if tool_name else None
    hidden = _HIDDEN_ON_CARD.get(tool_name, ())
    parts = []
    for key, value in inputs.items():
        if declared is not None and key not in declared:
            continue
        if key in hidden:
            value = "(hidden)" if value else ""
        text = _CONTROL_CHARS.sub(" ", json.dumps(value, default=str, ensure_ascii=False))
        if len(text) > _CARD_VALUE_MAX:
            text = f"{text[:_CARD_VALUE_MAX]}... ({len(text) - _CARD_VALUE_MAX} more characters not shown)"
        name = _CONTROL_CHARS.sub(" ", json.dumps(str(key), ensure_ascii=False))[:_CARD_KEY_MAX]
        parts.append(f"{name}: {text}")
    return "\nDetails: {" + ", ".join(parts) + "}"


def prompt_for(source: Source, tool_name: str, inputs: dict | None = None) -> dict:
    if source.kind == "web":
        url = str((inputs or {}).get("url", ""))
        if len(url) > _CARD_URL_MAX:
            url = url[:_CARD_URL_MAX] + "..."
        shown = "\nAddress: " + url if url else ""
        action = f"AI Gator wants to open {source.label}, which this tab has not used yet.{shown}"
    elif source.per_call and tool_name in _PER_CALL_TOOLS:
        _label, title, what = _PER_CALL_TOOLS[tool_name]
        return {
            "title": title,
            "action": (f"AI Gator wants to {what} (tool: {tool_name}). You are asked every time."
                       f"{_call_details(inputs, tool_name)}"),
            "allow_label": "Allow this time",
            "deny_label": "Deny",
        }
    elif source.per_call:
        return {
            "title": f"Allow this change in {source.label}?",
            "action": (
                f"AI Gator wants to make a change in {source.label} (tool: {tool_name}) that notifies other people "
                f"or cannot be undone. You are asked every time.{_call_details(inputs, tool_name)}"
            ),
            "allow_label": "Allow this time",
            "deny_label": "Deny",
        }
    elif source.action == actions.READ:
        action = f"AI Gator wants to read from {source.label} (tool: {tool_name}). {_STAYS_ALLOWED}"
    else:
        what = ("save a draft or a private change in" if source.action == actions.WRITE_PRIVATE
                else "change shared content in")
        return {
            "title": f"Allow changes in {source.label}?",
            "action": f"AI Gator wants to {what} {source.label} (tool: {tool_name}). {_STAYS_ALLOWED}",
            "allow_label": "Allow for this tab",
            "deny_label": "Deny",
        }
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
_SENSITIVE_FIELDS = (
    "subject", "body", "message", "comment", "description", "summary", "text", "arguments_text",
)


def _json_strings(text: str) -> list[str]:
    """The string values inside JSON text, unescaped, so a \\n cannot hide a word boundary."""
    try:
        parsed = json.loads(text)
    except ValueError:
        return [text]
    out: list[str] = []
    stack = [parsed]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            out.extend(k for k in item if isinstance(k, str))
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return out


def sensitivity_markers(data: dict) -> list[str]:
    """Classification words found in the draft text, so the approval card can warn the user."""
    found: dict[str, str] = {}
    for field in _SENSITIVE_FIELDS:
        value = data.get(field)
        if isinstance(value, str):
            texts = _json_strings(value) if field == "arguments_text" else [value]
            for text in texts:
                for match in _SENSITIVE_MARKER.finditer(text):
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


def allowed_with_prefix(context_id: str, prefix: str) -> list[str]:
    """Keys under prefix this tab has approved, with the prefix removed."""
    with _LOCK:
        return sorted(k[len(prefix):] for c, k in _ALLOWED if c == context_id and k.startswith(prefix))


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
