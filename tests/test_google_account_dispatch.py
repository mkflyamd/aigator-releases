import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import MagicMock, patch

from skills import _drafts

_SCHEMA = {
    "type": "object",
    "properties": {"user_google_email": {"type": "string"}, "query": {"type": "string"}},
}


def setup_function(function):
    _drafts._pending_drafts.clear()


def _handler(tool_name, schema=_SCHEMA):
    import mcp.manager as M
    import shared

    conn = {
        "id": "mcp-google-workspace",
        "name": "Google Workspace",
        "transport": "http",
        "url": "http://127.0.0.1:8080/mcp",
        "command": "uvx",
        "args": ["workspace-mcp", "--transport", "streamable-http"],
        "cached_tools": [{"name": tool_name, "description": "t", "input_schema": schema}],
    }
    shared.TOOL_DISPATCH.clear()
    shared.TOOLS.clear()
    shared.TOOL_STATUS.clear()
    shared.SKILL_TOOLS_MAP.pop(conn["id"], None)
    M._register(conn)
    namespaced = next(iter(shared.SKILL_TOOLS_MAP[conn["id"]]))
    return shared.TOOL_DISPATCH[namespaced]


def _cfg(accounts):
    return patch("config.load_config", return_value={"google_accounts": accounts})


def test_unlisted_email_is_rewritten_to_default_before_the_call():
    handler = _handler("search_gmail_messages")
    client = MagicMock()
    client.call.return_value = '{"messages": []}'
    with _cfg(["me@example.test"]), patch("mcp.manager._client_for", return_value=client):
        handler(query="is:unread", user_google_email="someone.else@example.test")
    assert "me@example.test" in str(client.call.call_args)
    assert "someone.else@example.test" not in str(client.call.call_args)


def test_missing_email_is_filled_with_default():
    handler = _handler("search_gmail_messages")
    client = MagicMock()
    client.call.return_value = "{}"
    with _cfg(["me@example.test"]), patch("mcp.manager._client_for", return_value=client):
        handler(query="x")
    assert "me@example.test" in str(client.call.call_args)


def test_listed_second_account_is_kept():
    handler = _handler("search_gmail_messages")
    client = MagicMock()
    client.call.return_value = "{}"
    with _cfg(["me@example.test", "work@example.test"]), patch("mcp.manager._client_for", return_value=client):
        handler(query="x", user_google_email="work@example.test")
    assert "work@example.test" in str(client.call.call_args)


def test_no_account_configured_returns_actionable_error_without_calling_client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_MCP_CREDENTIALS_DIR", str(tmp_path))
    handler = _handler("search_gmail_messages")
    with _cfg([]), patch("mcp.manager._client_for") as client_for:
        result = handler(query="x")
    client_for.assert_not_called()
    assert "Settings" in result["error"]


def test_approval_card_stores_the_resolved_email():
    handler = _handler("send_gmail_message")
    with _cfg(["me@example.test"]), patch("mcp.manager._client_for") as client_for:
        result = handler(to="a@example.test", subject="Hi", body="Hello", user_google_email="wrong@example.test")
    client_for.assert_not_called()
    draft = _drafts.get_draft(result["data"]["draft_id"])
    assert draft["params"]["arguments"]["user_google_email"] == "me@example.test"


def test_tool_without_email_param_is_untouched():
    handler = _handler("search_gmail_messages", {"type": "object", "properties": {"query": {"type": "string"}}})
    client = MagicMock()
    client.call.return_value = "{}"
    with _cfg(["me@example.test"]), patch("mcp.manager._client_for", return_value=client):
        handler(query="x")
    assert "user_google_email" not in str(client.call.call_args)
