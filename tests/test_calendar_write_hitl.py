"""Tests for the workspace-mcp HITL gate.

The gate in web/mcp/manager.py intercepts destructive tools from the
workspace-mcp server (send_gmail_message, manage_event with delete/create/
update/rsvp, trash, spam, etc.) and parks the call in the draft store.
The actual MCP call only runs from the CSRF-gated /api/drafts/{id}/approve
endpoint.

These tests cover the gate predicate (_is_gated_tool), the summary helper,
and the end-to-end handler path: a gated tool returns a
{_draft: "calendar-write", ...} shape and NEVER reaches the MCP client.
Read-only tools and write tools on non-workspace-mcp servers pass through.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import patch, MagicMock

from skills import _drafts


def setup_function(function):
    _drafts._pending_drafts.clear()


def _ws_conn():
    """A workspace-mcp stdio connection record."""
    return {
        "id": "mcp-google-workspace",
        "name": "Google Workspace",
        "transport": "stdio",
        "command": "uvx",
        "args": ["workspace-mcp", "--tool-tier", "complete"],
        "env": {},
        "cached_tools": [],
    }


def _generic_conn():
    """A non-workspace-mcp connection."""
    return {
        "id": "mcp-acme",
        "name": "Acme",
        "transport": "http",
        "url": "https://acme.example.com/mcp",
        "cached_tools": [],
    }


# ── Predicate: _is_gated_tool ────────────────────────────────────────────────


def test_send_gmail_message_is_gated():
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("send_gmail_message", {}, conn) is True


def test_manage_event_delete_is_gated():
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("manage_event", {"action": "delete"}, conn) is True


def test_manage_event_create_is_gated():
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("manage_event", {"action": "create"}, conn) is True


def test_manage_event_update_is_gated():
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("manage_event", {"action": "update"}, conn) is True


def test_manage_event_rsvp_is_gated():
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("manage_event", {"action": "rsvp"}, conn) is True


def test_trash_thread_is_gated():
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("trash_thread", {}, conn) is True


def test_trash_message_is_gated():
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("trash_message", {}, conn) is True


def test_mark_thread_spam_is_gated():
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("mark_thread_spam", {}, conn) is True


def test_search_gmail_messages_is_not_gated():
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("search_gmail_messages", {}, conn) is False


def test_get_gmail_message_content_is_not_gated():
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("get_gmail_message_content", {}, conn) is False


def test_get_events_is_not_gated():
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("get_events", {}, conn) is False


def test_list_calendars_is_not_gated():
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("list_calendars", {}, conn) is False


def test_query_freebusy_is_not_gated():
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("query_freebusy", {}, conn) is False


def test_draft_gmail_message_is_not_gated():
    """draft_gmail_message creates a draft (not a send) — not gated."""
    from mcp.manager import _is_gated_tool
    conn = _ws_conn()
    assert _is_gated_tool("draft_gmail_message", {}, conn) is False


def test_gated_tool_on_non_workspace_server_is_not_gated():
    """A third-party MCP server exposing send_gmail_message must not be gated."""
    from mcp.manager import _is_gated_tool
    conn = _generic_conn()
    assert _is_gated_tool("send_gmail_message", {}, conn) is False
    assert _is_gated_tool("manage_event", {"action": "delete"}, conn) is False


def test_predicate_handles_missing_fields():
    from mcp.manager import _is_gated_tool
    conn = {"id": "x", "name": "X"}
    assert _is_gated_tool("send_gmail_message", {}, conn) is False


# ── Handler: gated tools return a draft and never reach the MCP client ───────


def _make_handler_for(conn, tool_name):
    """Build the MCP handler closure for a single tool via the real _register()."""
    import mcp.manager as M
    conn_with_tools = dict(conn)
    conn_with_tools["cached_tools"] = [{
        "name": tool_name,
        "description": f"test {tool_name}",
        "input_schema": {"type": "object", "properties": {}},
    }]
    import shared
    shared.TOOL_DISPATCH.clear()
    shared.TOOLS.clear()
    shared.TOOL_STATUS.clear()
    shared.SKILL_TOOLS_MAP.pop(conn_with_tools["id"], None)
    M._register(conn_with_tools)
    namespaced = next(iter(shared.SKILL_TOOLS_MAP[conn_with_tools["id"]]))
    return shared.TOOL_DISPATCH[namespaced], namespaced


def test_send_gmail_returns_draft_and_does_not_call_client():
    handler, _ = _make_handler_for(_ws_conn(), "send_gmail_message")
    with patch("mcp.manager._client_for") as mock_client_for:
        result = handler(to="alice@example.com", subject="Hi", body="Hello")
    mock_client_for.assert_not_called()
    assert isinstance(result, dict)
    assert result.get("_draft") == "calendar-write"
    data = result.get("data", {})
    assert "draft_id" in data
    assert data["tool"] == "send_gmail_message"
    assert "Send email" in data["action"]
    assert data["draft_id"] in _drafts._pending_drafts


def test_manage_event_delete_returns_draft():
    handler, _ = _make_handler_for(_ws_conn(), "manage_event")
    with patch("mcp.manager._client_for") as mock_client_for:
        result = handler(action="delete", event_id="evt_123")
    mock_client_for.assert_not_called()
    assert result.get("_draft") == "calendar-write"


def test_search_gmail_passes_through_and_calls_client():
    """Read-only tools must pass through to the MCP client normally."""
    handler, _ = _make_handler_for(_ws_conn(), "search_gmail_messages")
    mock_client = MagicMock()
    mock_client.call.return_value = '{"messages": []}'
    with patch("mcp.manager._client_for", return_value=mock_client) as mock_client_for:
        result = handler(query="is:unread", user_google_email="test@gmail.com")
    mock_client_for.assert_called_once()
    mock_client.call.assert_called_once()
    assert "_draft" not in result


def test_draft_captures_connection_id_and_arguments_for_replay():
    handler, _ = _make_handler_for(_ws_conn(), "send_gmail_message")
    with patch("mcp.manager._client_for"):
        result = handler(to="alice@example.com", subject="Test", body="Body")
    draft_id = result["data"]["draft_id"]
    draft = _drafts.get_draft(draft_id)
    assert draft is not None
    assert draft["type"] == "calendar-write"
    p = draft["params"]
    assert p["connection_id"] == "mcp-google-workspace"
    assert p["tool"] == "send_gmail_message"
    assert p["arguments"]["to"] == "alice@example.com"


# ── Summary helper ───────────────────────────────────────────────────────────


def test_summary_send_email():
    from mcp.manager import _summarize_gated_call
    s = _summarize_gated_call("send_gmail_message", {"to": "alice@example.com"})
    assert "alice@example.com" in s


def test_summary_manage_event_delete():
    from mcp.manager import _summarize_gated_call
    s = _summarize_gated_call("manage_event", {"action": "delete", "event_id": "evt_abc123"})
    assert "Delete" in s
    assert "evt_abc123" in s[:50] or "evt_abc" in s


def test_summary_manage_event_create():
    from mcp.manager import _summarize_gated_call
    s = _summarize_gated_call("manage_event", {"action": "create", "summary": "Team lunch"})
    assert "create" in s.lower()
    assert "Team lunch" in s
