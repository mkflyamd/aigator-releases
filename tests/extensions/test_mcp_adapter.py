from unittest.mock import patch, MagicMock
from extensions.mcp_adapter import MCPAdapter


def test_normalize_delegates_to_normalizer():
    a = MCPAdapter()
    fake = MagicMock(ok=True)
    fake.to_entry.return_value = {"url": "https://x/y", "transport": "http"}
    with patch("extensions.mcp_adapter.normalize", return_value=fake):
        result = a.normalize("https://x/y")
        assert result["url"] == "https://x/y"


def test_prefill_from_url_recognises_atlassian():
    a = MCPAdapter()
    result = a.prefill_from_url("https://mcp.atlassian.com/v1/mcp")
    assert result["url"] == "https://mcp.atlassian.com/v1/mcp"
    assert result["auth_type"] == "oauth2"
    assert result["name"].lower().startswith("atlassian")


def test_test_connection_returns_tool_count_on_success():
    a = MCPAdapter()
    with patch("mcp.manager.add_or_update",
               return_value={"ok": True, "tool_count": 47, "name": "Atlassian"}):
        r = a.test_connection({"transport": "http", "url": "https://x",
                               "auth_type": "bearer", "auth_value": "tok"})
        assert r.ok is True
        assert r.tool_count == 47
        assert "47" in r.detail


def test_test_connection_returns_error_detail_on_failure():
    a = MCPAdapter()
    with patch("mcp.manager.add_or_update",
               return_value={"ok": False, "error": "HTTP 401 invalid_token"}):
        r = a.test_connection({"transport": "http", "url": "https://x"})
        assert r.ok is False
        assert "401" in r.detail


def test_test_connection_passes_dry_run_flag():
    a = MCPAdapter()
    with patch("mcp.manager.add_or_update", return_value={"ok": True, "tool_count": 0}) as upd:
        a.test_connection({"url": "https://x"})
        call_arg = upd.call_args[0][0]
        assert call_arg.get("_dry_run") is True


def test_install_strips_dry_run_flag():
    a = MCPAdapter()
    with patch("mcp.manager.add_or_update",
               return_value={"ok": True, "id": "mcp-x"}) as upd:
        a.install({"url": "https://x", "_dry_run": True})
        call_arg = upd.call_args[0][0]
        assert "_dry_run" not in call_arg
