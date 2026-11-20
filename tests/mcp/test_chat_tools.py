# tests/mcp/test_chat_tools.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

from unittest.mock import patch
from mcp.normalizer import NormalizeResult


def test_analyze_tool_returns_structured_text():
    import importlib

    tools = importlib.import_module("skills._always_on.tools")

    fake = NormalizeResult(
        ok=True,
        transport="stdio",
        name="playwright",
        command="npx",
        args=["@playwright/mcp@latest"],
        source="json_mcpservers",
        confidence="high",
        prerequisite_warning="npx must be installed",
    )

    with patch("skills._always_on.tools._normalize_mcp", return_value=fake):
        result = tools.TOOL_HANDLERS["analyze_mcp_server"](raw_input="any text")

    assert "playwright" in result
    assert "stdio" in result or "local" in result.lower()
    assert "npx" in result


def test_analyze_tool_failure_returns_error_text():
    import importlib

    tools = importlib.import_module("skills._always_on.tools")

    fake = NormalizeResult(ok=False, error="unrecognized format")
    with patch("skills._always_on.tools._normalize_mcp", return_value=fake):
        result = tools.TOOL_HANDLERS["analyze_mcp_server"](raw_input="garbage")

    assert "couldn't" in result.lower() or "unrecognized" in result.lower()


def test_connect_tool_calls_save_endpoint():
    import importlib

    tools = importlib.import_module("skills._always_on.tools")

    with patch(
        "skills._always_on.tools._save_mcp_connection",
        return_value={"ok": True, "name": "playwright", "tool_count": 3},
    ) as mock_save:
        result = tools.TOOL_HANDLERS["connect_mcp_server"](
            transport="stdio",
            name="playwright",
            command="npx",
            args=["@playwright/mcp@latest"],
            url="",
            auth_type="none",
            auth_value="",
            env={},
        )

    mock_save.assert_called_once()
    assert "playwright" in result
    assert "3" in result


def test_connect_tool_saves_in_process_without_http():
    import importlib

    tools = importlib.import_module("skills._always_on.tools")

    with patch("urllib.request.urlopen", side_effect=OSError("no HTTP allowed")), patch(
        "routes.mcp_routes.add_or_update",
        return_value={"ok": True, "name": "playwright", "tool_count": 3},
    ) as mock_add:
        result = tools.TOOL_HANDLERS["connect_mcp_server"](
            transport="stdio",
            name="playwright",
            command="npx",
            args=["@playwright/mcp@latest"],
        )

    mock_add.assert_called_once()
    assert mock_add.call_args.args[0]["command"] == "npx"
    assert "added successfully" in result
    assert "3 tools" in result


def test_connect_tool_surfaces_validation_errors():
    import importlib

    tools = importlib.import_module("skills._always_on.tools")

    with patch("routes.mcp_routes.add_or_update") as mock_add:
        missing_url = tools.TOOL_HANDLERS["connect_mcp_server"](transport="http", name="x")
        bad_basic = tools.TOOL_HANDLERS["connect_mcp_server"](
            transport="http",
            name="x",
            url="https://mcp.example.com/mcp",
            auth_type="basic",
            auth_value="aigator-fake-api-key",
        )
        missing_command = tools.TOOL_HANDLERS["connect_mcp_server"](transport="stdio", name="x")

    mock_add.assert_not_called()
    assert "URL is required" in missing_url
    assert "identifier:secret" in bad_basic
    assert "command is required" in missing_command
