"""Tests for the mcp_connection_status always-on tool (Option 2) and the
_is_plugin_bundled_skill detection helper (Option 1).

mcp_connection_status is built entirely on top of mcp.manager.list_with_status()'s
already-masked output — these tests patch that call point (never touch real
config.json) and assert the tool's output only ever surfaces the whitelisted,
non-secret fields.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web"))

from unittest.mock import patch


def _fixture_rows():
    """A representative list_with_status() fixture: one healthy connection,
    one plugin connection needing setup, one disabled connection with a
    connect_error, and secret-ish fields present exactly as list_with_status
    would mask them (never raw)."""
    return [
        {
            "id": "mcp-playwright",
            "name": "Playwright",
            "transport": "stdio",
            "enabled": True,
            "tool_count": 5,
            "connected": None,
            "command": "npx",
            "args": ["@playwright/mcp@latest"],
            "env_hint": {"SOME_TOKEN": "••••••••abcd"},
        },
        {
            "id": "mcp-datadog",
            "name": "Datadog",
            "transport": "http",
            "enabled": False,
            "tool_count": 0,
            "connected": None,
            "url": "https://mcp.datadoghq.com",
            "auth_type": "api_key",
            "auth_value_hint": "••••••••wxyz",
            "extra_headers_hint": {},
            "plugin_id": "datadog",
            "missing_secrets": ["DD_API_KEY", "DD_APPLICATION_KEY", "DD_MCP_DOMAIN", "DD_MCP_TOOLSETS"],
        },
        {
            "id": "mcp-broken",
            "name": "Broken Server",
            "transport": "http",
            "enabled": False,
            "tool_count": 0,
            "connected": None,
            "url": "https://example.com/mcp",
            "auth_type": "none",
            "auth_value_hint": "",
            "extra_headers_hint": {},
            "connect_error": "Connection refused",
        },
    ]


def _tools_module():
    import importlib
    return importlib.import_module("skills._always_on.tools")


# ── filter behavior ──────────────────────────────────────────────────────────

def test_filter_narrows_by_plugin_id_case_insensitive():
    tools = _tools_module()
    with patch("skills._always_on.tools._mcp_list_with_status", return_value=_fixture_rows()):
        result = tools.TOOL_HANDLERS["mcp_connection_status"](filter="DataDog")

    ids = [c["id"] for c in result["connections"]]
    assert ids == ["mcp-datadog"]


def test_filter_narrows_by_name():
    tools = _tools_module()
    with patch("skills._always_on.tools._mcp_list_with_status", return_value=_fixture_rows()):
        result = tools.TOOL_HANDLERS["mcp_connection_status"](filter="playwright")

    ids = [c["id"] for c in result["connections"]]
    assert ids == ["mcp-playwright"]


def test_filter_narrows_by_id_substring():
    tools = _tools_module()
    with patch("skills._always_on.tools._mcp_list_with_status", return_value=_fixture_rows()):
        result = tools.TOOL_HANDLERS["mcp_connection_status"](filter="broken")

    ids = [c["id"] for c in result["connections"]]
    assert ids == ["mcp-broken"]


def test_empty_filter_returns_all():
    tools = _tools_module()
    with patch("skills._always_on.tools._mcp_list_with_status", return_value=_fixture_rows()):
        result = tools.TOOL_HANDLERS["mcp_connection_status"](filter="")

    assert len(result["connections"]) == 3
    assert result["message"] is None


def test_no_filter_arg_returns_all():
    tools = _tools_module()
    with patch("skills._always_on.tools._mcp_list_with_status", return_value=_fixture_rows()):
        result = tools.TOOL_HANDLERS["mcp_connection_status"]()

    assert len(result["connections"]) == 3


def test_no_match_returns_not_installed_message():
    tools = _tools_module()
    with patch("skills._always_on.tools._mcp_list_with_status", return_value=_fixture_rows()):
        result = tools.TOOL_HANDLERS["mcp_connection_status"](filter="nonexistent-thing")

    assert result["connections"] == []
    assert "nonexistent-thing" in result["message"]
    assert "may not be installed" in result["message"]


# ── derived needs_setup / status ─────────────────────────────────────────────

def test_needs_setup_connection_reports_correct_status():
    tools = _tools_module()
    with patch("skills._always_on.tools._mcp_list_with_status", return_value=_fixture_rows()):
        result = tools.TOOL_HANDLERS["mcp_connection_status"](filter="datadog")

    conn = result["connections"][0]
    assert conn["needs_setup"] is True
    assert "Settings" in conn["status"] and "Connections" in conn["status"]
    assert "Complete setup" in conn["status"]
    assert conn["plugin_id"] == "datadog"
    assert set(conn["missing_secrets"]) == {
        "DD_API_KEY", "DD_APPLICATION_KEY", "DD_MCP_DOMAIN", "DD_MCP_TOOLSETS",
    }


def test_healthy_connection_reports_ready():
    tools = _tools_module()
    with patch("skills._always_on.tools._mcp_list_with_status", return_value=_fixture_rows()):
        result = tools.TOOL_HANDLERS["mcp_connection_status"](filter="playwright")

    conn = result["connections"][0]
    assert conn["needs_setup"] is False
    assert conn["status"] == "Ready"


def test_disabled_connection_with_error_reports_connection_error():
    tools = _tools_module()
    with patch("skills._always_on.tools._mcp_list_with_status", return_value=_fixture_rows()):
        result = tools.TOOL_HANDLERS["mcp_connection_status"](filter="broken")

    conn = result["connections"][0]
    assert conn["needs_setup"] is False  # no missing_secrets, so not "needs setup"
    assert "Connection refused" in conn["status"]
    assert conn["connect_error"] == "Connection refused"


def test_disabled_without_error_or_missing_secrets_reports_disabled():
    tools = _tools_module()
    row = {"id": "mcp-x", "name": "X", "enabled": False, "tool_count": 0}
    with patch("skills._always_on.tools._mcp_list_with_status", return_value=[row]):
        result = tools.TOOL_HANDLERS["mcp_connection_status"]()

    conn = result["connections"][0]
    assert conn["needs_setup"] is False
    assert conn["status"] == "Disabled"


# ── SECURITY: only whitelisted fields ever leave the tool ──────────────────

_WHITELISTED_KEYS = {
    "id", "name", "plugin_id", "enabled", "tool_count",
    "missing_secrets", "connect_error", "needs_setup", "status",
}
_FORBIDDEN_KEYS = {
    "auth_value", "auth_value_hint", "env", "env_hint",
    "extra_headers", "extra_headers_hint", "url", "command", "args",
    "transport", "connected", "oauth_provider_id",
}


def test_output_never_exposes_non_whitelisted_or_secret_fields():
    tools = _tools_module()
    with patch("skills._always_on.tools._mcp_list_with_status", return_value=_fixture_rows()):
        result = tools.TOOL_HANDLERS["mcp_connection_status"]()

    for conn in result["connections"]:
        extra_keys = set(conn.keys()) - _WHITELISTED_KEYS
        assert not extra_keys, f"Unexpected keys leaked from tool output: {extra_keys}"
        assert not (set(conn.keys()) & _FORBIDDEN_KEYS)
        # Even masked secret-hint strings from the fixture must not appear at all —
        # the tool should not have copied those keys over in the first place.
        assert "env_hint" not in conn
        assert "auth_value_hint" not in conn
        assert "extra_headers_hint" not in conn


# ── Option 1: _is_plugin_bundled_skill helper ───────────────────────────────

def _chat_module():
    import importlib
    return importlib.import_module("routes.chat")


def test_namespaced_plugin_skill_id_detected_via_heuristic_fallback():
    chat = _chat_module()
    with patch("marketplace.installer.load_installed", return_value=[]):
        assert chat._is_plugin_bundled_skill("datadog__skills-ddsetup") is True
        assert chat._is_plugin_bundled_skill("amd-skills__local-ai-use") is True


def test_native_skills_are_not_plugin_bundled():
    chat = _chat_module()
    with patch("marketplace.installer.load_installed", return_value=[]):
        assert chat._is_plugin_bundled_skill("email") is False
        assert chat._is_plugin_bundled_skill("jira") is False
        assert chat._is_plugin_bundled_skill("calendar") is False


def test_mcp_connection_id_not_misclassified_as_plugin_skill():
    chat = _chat_module()
    with patch("marketplace.installer.load_installed", return_value=[]):
        assert chat._is_plugin_bundled_skill("mcp-datadog") is False


def test_bare_id_single_skill_plugin_detected_via_registry():
    """A single-SKILL.md plugin registers under the bare plugin_id (no "__"),
    so the "__" heuristic alone would miss it — the installed-skills.json
    skill_ids registry is the primary signal that catches this case."""
    chat = _chat_module()
    fake_entries = [
        {"id": "solo-plugin", "skill_ids": ["solo-plugin"], "tier": "Verified"},
    ]
    with patch("marketplace.installer.load_installed", return_value=fake_entries):
        assert chat._is_plugin_bundled_skill("solo-plugin") is True


def test_regular_marketplace_skill_without_skill_ids_field_not_misclassified():
    """A regular (non-plugin-bundle) marketplace skill install has no
    skill_ids field on its record — must not be treated as plugin-bundled."""
    chat = _chat_module()
    fake_entries = [
        {"id": "some-native-authored-skill", "tier": "Community"},
    ]
    with patch("marketplace.installer.load_installed", return_value=fake_entries):
        assert chat._is_plugin_bundled_skill("some-native-authored-skill") is False


# ── connect_error sanitizer (never pipe a credential into the model) ─────────

def test_sanitize_connect_error_strips_url_userinfo():
    tools = _tools_module()
    out = tools._sanitize_connect_error("https://user:pw@mcp.example.com/v1")
    assert "user:pw" not in out
    assert "https://mcp.example.com/v1" in out


def test_sanitize_connect_error_redacts_sensitive_query_params():
    tools = _tools_module()
    out = tools._sanitize_connect_error(
        "is the server running at https://mcp.example.com/v1/mcp?api_key=SECRET123&x=1 ?"
    )
    assert "SECRET123" not in out
    assert "REDACTED" in out
    assert "x=1" in out  # non-sensitive param left intact


def test_sanitize_connect_error_leaves_plain_diagnostic_intact():
    tools = _tools_module()
    msg = "This server requires OAuth authentication."
    assert tools._sanitize_connect_error(msg) == msg
    assert tools._sanitize_connect_error("connection attempt timed out after 20s") == \
        "connection attempt timed out after 20s"


def test_sanitize_connect_error_truncates_overlong_input():
    tools = _tools_module()
    out = tools._sanitize_connect_error("x" * 500)
    assert len(out) <= tools._CE_MAX + 1  # +1 for the ellipsis char


def test_tool_output_connect_error_is_sanitized_no_secret_leaks_to_model():
    """A connection whose connect_error embeds a real credential in the URL must
    never reach the model's context via this tool — neither in the connect_error
    field nor the status string."""
    tools = _tools_module()
    rows = [{
        "id": "mcp-leaky", "name": "Leaky", "transport": "http",
        "enabled": False, "tool_count": 0, "connected": None,
        "url": "https://example.com/mcp",
        "connect_error": "connect failed: https://example.com/mcp?token=TOPSECRETVALUE&z=2",
    }]
    with patch("skills._always_on.tools._mcp_list_with_status", return_value=rows):
        result = tools.TOOL_HANDLERS["mcp_connection_status"]()

    conn = result["connections"][0]
    assert "TOPSECRETVALUE" not in conn["connect_error"]
    assert "TOPSECRETVALUE" not in conn["status"]
    assert "REDACTED" in conn["connect_error"]
