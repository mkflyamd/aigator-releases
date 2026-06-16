# tests/mcp/test_chat_tools.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

from unittest.mock import patch
from mcp.normalizer import NormalizeResult


def test_analyze_tool_returns_structured_text():
    import importlib
    tools = importlib.import_module("skills._always_on.tools")

    fake = NormalizeResult(ok=True, transport="stdio", name="playwright",
                           command="npx", args=["@playwright/mcp@latest"],
                           source="json_mcpservers", confidence="high",
                           prerequisite_warning="npx must be installed")

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

    with patch("skills._always_on.tools._save_mcp_connection", return_value={"ok": True, "name": "playwright", "tool_count": 3}) as mock_save:
        result = tools.TOOL_HANDLERS["connect_mcp_server"](
            transport="stdio", name="playwright",
            command="npx", args=["@playwright/mcp@latest"],
            url="", auth_type="none", auth_value="", env={},
        )

    mock_save.assert_called_once()
    assert "playwright" in result
    assert "3" in result
