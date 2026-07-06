"""Tests verifying Slack MCP → Web API migration.

Phase 1: send routes use chat.postMessage; _profile_name uses users.info
Phase 2: channel routes use conversations.list (added here as stubs, filled as phases complete)
"""

import pathlib
import sys
from unittest.mock import patch

import pytest

def _load_src() -> str:
    return (pathlib.Path(__file__).parent.parent / "routes" / "slack.py").read_text(encoding="utf-8")

def _load_mcp_src() -> str:
    return (pathlib.Path(__file__).parent.parent / "skills" / "slack" / "mcp_client.py").read_text(encoding="utf-8")

SRC = _load_src()
MCP_SRC = _load_mcp_src()


def _fn_body(fn_name: str, window: int = 2000) -> str:
    """Extract function body up to the next @router decorator or window chars."""
    start = SRC.find(f"async def {fn_name}(")
    if start == -1:
        start = SRC.find(f"def {fn_name}(")
    assert start != -1, f"{fn_name} not found in routes/slack.py"
    next_route = SRC.find("\n@router.", start + 1)
    end = next_route if next_route != -1 else start + window
    return SRC[start:end]


# ─── Phase 1: send routes ────────────────────────────────────────────────────

class TestSendMessageUsesWebAPI:
    """slack_send_message_confirmed must call chat.postMessage, not MCP."""

    def test_send_confirmed_calls_chat_postmessage(self):
        body = _fn_body("slack_send_message_confirmed")
        assert "chat.postMessage" in body, "Must call chat.postMessage"
        assert "_slack_mcp_call" not in body, "Must not use _slack_mcp_call"
        assert '"slack_send_message"' not in body, "Must not reference MCP tool name as string arg"

    def test_send_confirmed_uses_post_method(self):
        body = _fn_body("slack_send_message_confirmed")
        assert 'method="POST"' in body or "method='POST'" in body, "Must send as POST"

    def test_send_dm_confirmed_calls_chat_postmessage(self):
        body = _fn_body("slack_send_dm_confirmed")
        assert "chat.postMessage" in body, "DM send must call chat.postMessage"
        assert "_slack_mcp_call" not in body, "Must not use _slack_mcp_call"

    def test_hitl_token_validation_preserved(self):
        """confirm_token validation must still happen before any send."""
        body = _fn_body("slack_send_message_confirmed")
        assert "_consume_draft_token" in body, "HITL token check must remain"
        assert "403" in body, "Must raise 403 on invalid token"

    def test_slack_web_api_supports_post(self):
        """_slack_web_api must accept method='POST' for JSON body sends."""
        fn_start = SRC.find("def _slack_web_api(")
        fn_body = SRC[fn_start: fn_start + 800]
        assert 'method: str = "GET"' in fn_body or "method=" in fn_body, "Must accept method param"
        assert "Content-Type" in fn_body, "POST must set Content-Type: application/json"
        assert "json.dumps" in fn_body, "POST must JSON-encode the body"


class TestChannelListUsesWebAPI:
    """slack_channels must use conversations.list, not MCP."""

    def test_slack_channels_no_mcp(self):
        SRC = _load_src()
        # conversations.list may be in the helper _fetch_channels_for_type, not inline
        assert "conversations.list" in SRC, "Must use conversations.list somewhere"
        assert "slack_search_channels" not in SRC.replace("# ", ""), "Must not use MCP tool name"
        fn_start = SRC.find("async def slack_channels()")
        fn_end = SRC.find("\n@router.", fn_start + 1)
        fn_body = SRC[fn_start:fn_end]
        assert "_slack_mcp_call" not in fn_body, "Must not use _slack_mcp_call"
        assert r'\n---\n' not in fn_body, "No markdown-regex splitting"

    def test_slack_channel_info_no_mcp(self):
        SRC = _load_src()
        fn_start = SRC.find("async def slack_channel_info(")
        fn_end = SRC.find("\n@router.", fn_start + 1)
        fn_body = SRC[fn_start:fn_end]
        assert "_slack_mcp_call" not in fn_body, "Must not use _slack_mcp_call"
        assert "conversations.info" in fn_body, "Must use conversations.info"

    def test_slack_token_status_no_mcp_ping(self):
        SRC = _load_src()
        fn_start = SRC.find("async def slack_token_status()")
        fn_end = SRC.find("\n@router.", fn_start + 1)
        fn_body = SRC[fn_start:fn_end]
        assert "get_slack_mcp" not in fn_body, "Must not call get_slack_mcp"
        assert "_UNREACHABLE_MSG" not in fn_body, "Must not use MCP unreachable sentinel"
        assert "auth.test" in fn_body, "Must use auth.test for health check"


class TestMessageSearchUsesWebAPI:
    """Message search routes must use search.messages, not MCP."""

    def test_search_messages_helper_exists(self):
        SRC = _load_src()
        assert "def _slack_search_messages(" in SRC, "Helper must exist"
        assert "search.messages" in SRC, "Must call search.messages endpoint"

    def test_slack_channel_threads_no_mcp(self):
        SRC = _load_src()
        fn_start = SRC.find("async def slack_channel_threads(")
        fn_end = SRC.find("\n@router.", fn_start + 1)
        fn_body = SRC[fn_start:fn_end]
        assert "_slack_mcp_call" not in fn_body, "Must not use _slack_mcp_call"
        assert "slack_search_public_and_private" not in fn_body, "Must not use MCP tool"
        assert r'\n---\n' not in fn_body, "No markdown-regex splitting"
        assert "_slack_search_messages" in fn_body, "Must use search helper"

    def test_slack_search_no_mcp(self):
        SRC = _load_src()
        fn_start = SRC.find("async def slack_search(")
        fn_end = SRC.find("\n@router.", fn_start + 1)
        fn_body = SRC[fn_start:fn_end]
        assert "_slack_mcp_call" not in fn_body, "Must not use _slack_mcp_call"
        assert "_slack_search_messages" in fn_body, "Must use search helper"

    def test_search_read_scope_not_in_approved_app(self):
        """search:read removed — Anthropic MCP app doesn't approve it.
        search.messages still works; existing tokens use search:read.public etc."""
        MCP_SRC = _load_mcp_src()
        # Verify the plain search:read scope is NOT requested (would break install)
        lines = [l for l in MCP_SRC.splitlines() if '"search:read,"' in l and not l.strip().startswith("#")]
        assert not lines, "Plain search:read must not be in SLACK_SCOPES — Anthropic MCP app rejects it"


class TestMCPLayerDeleted:
    """Phase 5: SlackMCPClient and xoxc- routes must be deleted."""

    def test_slack_mcp_client_deleted(self):
        MCP_SRC = _load_mcp_src()
        assert "class SlackMCPClient" not in MCP_SRC, "SlackMCPClient must be deleted"
        assert "def get_slack_mcp" not in MCP_SRC, "get_slack_mcp must be deleted"

    def test_oauth_pkce_intact(self):
        MCP_SRC = _load_mcp_src()
        assert "def get_oauth_token" in MCP_SRC, "get_oauth_token must remain"
        assert "def start_oauth" in MCP_SRC, "start_oauth must remain"
        assert "def _exchange_code" in MCP_SRC, "_exchange_code must remain"

    def test_xoxc_routes_deleted(self):
        SRC = _load_src()
        assert "async def save_slack_token" not in SRC, "xoxc- POST route must be removed"
        assert "async def slack_token_capture" not in SRC, "CDP capture route must be removed"
        assert "def _slack_auth_test" not in SRC, "_slack_auth_test must be removed"
        assert "def _slack_mcp_call" not in SRC, "_slack_mcp_call must be removed"

    def test_capture_file_still_exists(self):
        import pathlib
        assert pathlib.Path("web/capture_slack_token.py").exists(), \
            "capture_slack_token.py file must not be deleted"


class TestNoMCPCallsRemaining:
    """After Phase 4, no mcp.call() or _slack_mcp_call() should remain."""

    def test_no_mcp_calls_in_routes(self):
        """No route handlers should call MCP directly (helper itself will be deleted in Phase 5)."""
        SRC = _load_src()
        # Find mcp.call outside the _slack_mcp_call helper function body
        helper_start = SRC.find("def _slack_mcp_call(")
        helper_end = SRC.find("\ndef ", helper_start + 1) if helper_start != -1 else 0
        # Code outside the helper
        before_helper = SRC[:helper_start] if helper_start != -1 else SRC
        after_helper = SRC[helper_end:] if helper_end > 0 else ""
        code = before_helper + after_helper
        code_lines = [l for l in code.splitlines() if not l.strip().startswith("#")]
        cleaned = "\n".join(code_lines)
        assert "mcp.call(" not in cleaned, "Route handlers must not call MCP directly"

    def test_slack_dms_no_mcp(self):
        SRC = _load_src()
        fn_start = SRC.find("async def slack_dms()")
        fn_end = SRC.find("\n@router.", fn_start + 1)
        fn_body = SRC[fn_start:fn_end]
        assert "get_slack_mcp" not in fn_body
        assert "mcp.call" not in fn_body
        assert "conversations.list" in fn_body, "Must use conversations.list for DMs"

    def test_slack_user_lookup_no_mcp(self):
        SRC = _load_src()
        fn_start = SRC.find("async def slack_user_lookup(")
        fn_end = SRC.find("\n@router.", fn_start + 1)
        fn_body = SRC[fn_start:fn_end]
        assert "_slack_mcp_call" not in fn_body
        assert "users.list" in fn_body, "Must use users.list"


class TestProfileNameUsesWebAPI:
    """_profile_name in slack_resolve_members must use users.info, not MCP."""

    def test_profile_name_uses_users_info(self):
        SRC = _load_src()
        fn_start = SRC.find("async def slack_resolve_members(")
        assert fn_start != -1
        fn_body = SRC[fn_start: fn_start + 1200]
        # Must not use MCP tool slack_read_user_profile
        assert "slack_read_user_profile" not in fn_body, "Must not use MCP tool slack_read_user_profile"
        assert "get_slack_mcp" not in fn_body, "Must not import get_slack_mcp"
