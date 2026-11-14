"""Regression coverage for explicit direct and Atlassian MCP setup."""

from pathlib import Path


ROOT = Path(__file__).parent.parent
CONFIG = (ROOT / "routes" / "config_routes.py").read_text(encoding="utf-8")
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def test_direct_jira_save_does_not_silently_create_an_mcp_connection():
    start = CONFIG.index("def save_jira_pat(")
    end = CONFIG.index("class JiraExtraSitesRequest", start)
    save_body = CONFIG[start:end]

    assert "add_or_update" not in save_body
    assert "cloud-atlassian" not in save_body
    assert "Direct API credentials are intentionally site-specific" in save_body


def test_no_api_token_cloud_mcp_remains():
    for source in (CONFIG, APP, INDEX):
        assert "cloud-mcp" not in source
        assert "Cloud MCP" not in source
    assert "cloud-atlassian" not in CONFIG
    assert "amd.com" not in CONFIG


def test_apps_ui_exposes_direct_and_atlassian_mcp_choices():
    assert "Direct site access" in INDEX
    assert "Optional MCP access" in INDEX
    assert "Connect Atlassian MCP" in INDEX
    assert "choose a site" in INDEX
    assert "Atlassian MCP is the explicit Atlassian SSO/site-selection path" in APP


def test_saved_atlassian_mcp_connection_gets_a_clean_name():
    start = APP.index("async function _nextAtlassianMcpName")
    helper = APP[start : APP.index("async function loadAtlassianStatus", start)]
    assert "'Atlassian MCP'" in helper
    assert "`Atlassian MCP ${n}`" in helper
    assert "name: await _nextAtlassianMcpName()," in APP
    assert "provider_id || '').slice" not in APP


def test_connecting_animation_uses_gator_greens_only():
    start = STYLE.index(".atlassian-mcp-connect--connecting {")
    end = STYLE.index("@keyframes atlassian-mcp-edge-spin", start)
    block = STYLE[start:end]

    for brand_color in ("#4a154b", "#36c5f0", "#2eb67d", "#ecb22e", "#e01e5a"):
        assert brand_color not in block
    assert "var(--accent" in block


def test_connecting_mcp_buttons_offer_cancel():
    helper = APP[APP.index("function _setAtlassianMcpConnectState") : APP.index("async function loadAtlassianStatus")]
    assert "atlassian-mcp-cancel" in helper
    assert "onCancel" in helper
    # A child of the disabled button would never receive the click.
    assert "button.parentElement" in helper
    assert "textContent = '×'" in helper
    assert "aria-label" in helper
    assert INDEX.count('class="atlassian-mcp-wrap"') == 1
    assert ".atlassian-mcp-cancel {" in STYLE
    assert "position: absolute" in STYLE[STYLE.index(".atlassian-mcp-cancel {") :][:300]

    connect_handler = APP[APP.index("atlassianAddSiteBtn.addEventListener('click'") : APP.index("/* ── GitHub")]
    assert "new AbortController()" in connect_handler
    assert "popup.close()" in connect_handler


def test_mcp_buttons_have_connecting_and_connected_feedback():
    assert "atlassian-mcp-connect" in INDEX
    assert "_setAtlassianMcpConnectState" in APP
    assert "atlassian-mcp-connect--connecting" in APP
    assert "atlassian-mcp-connect--connected" in APP
    assert "Atlassian MCP Connected ✓" in APP
    assert "@property --atlassian-mcp-angle" in STYLE
    assert "atlassian-mcp-edge-spin" in STYLE
