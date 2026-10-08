"""Regression coverage for explicit direct, Cloud MCP, and Rovo MCP setup."""

from pathlib import Path


ROOT = Path(__file__).parent.parent
CONFIG = (ROOT / "routes" / "config_routes.py").read_text(encoding="utf-8")
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def test_direct_jira_save_does_not_silently_create_cloud_mcp():
    start = CONFIG.index("def save_jira_pat(")
    end = CONFIG.index("@router.post(\"/api/config/atlassian/cloud-mcp\"", start)
    save_body = CONFIG[start:end]

    assert "add_or_update" not in save_body
    assert "cloud-atlassian" not in save_body
    assert "Direct API credentials are intentionally site-specific" in save_body


def test_cloud_mcp_has_explicit_api_token_endpoint():
    assert '@router.post("/api/config/atlassian/cloud-mcp"' in CONFIG
    assert '"connection_id": "cloud-atlassian"' in CONFIG
    assert '"name": "Atlassian Cloud MCP · API token"' in CONFIG


def test_apps_ui_exposes_explicit_cloud_and_rovo_choices():
    assert "Direct site access" in INDEX
    assert "Optional MCP access" in INDEX
    assert "Cloud MCP" in INDEX
    assert "provider-selected" in INDEX
    assert "Connect Cloud MCP · API token (default site)" in INDEX
    assert "Connect Rovo MCP" in INDEX
    assert "choose a site" in INDEX
    assert "atlassianCloudMcpBtn.addEventListener" in APP
    assert "/api/config/atlassian/cloud-mcp" in APP
    assert "MCP site is provider-selected" in APP
    assert "Direct API site:" in APP
    assert "Rovo MCP is the explicit Atlassian SSO/site-selection path" in APP


def test_mcp_buttons_have_connecting_and_connected_feedback():
    assert "atlassian-mcp-connect" in INDEX
    assert "_setAtlassianMcpConnectState" in APP
    assert "atlassian-mcp-connect--connecting" in APP
    assert "atlassian-mcp-connect--connected" in APP
    assert "Cloud MCP Connected ✓" in APP
    assert "Rovo MCP Connected ✓" in APP
    assert "@property --atlassian-mcp-angle" in STYLE
    assert "atlassian-mcp-edge-spin" in STYLE
