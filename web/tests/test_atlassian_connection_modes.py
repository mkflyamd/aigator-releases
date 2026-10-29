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
    assert "Connect Cloud MCP · API token (primary site)" in INDEX
    assert "Connect Rovo MCP" in INDEX
    assert "choose a site" in INDEX
    assert "atlassianCloudMcpBtn.addEventListener('click', connectAtlassianCloudMcp)" in APP
    assert "/api/config/atlassian/cloud-mcp" in APP
    assert "MCP site is provider-selected" in APP
    assert "Direct API site:" in APP
    assert "Rovo MCP is the explicit Atlassian SSO/site-selection path" in APP


def test_direct_save_connects_cloud_mcp_after_both_saves_commit():
    start = APP.index("atlassianSaveBtn.addEventListener('click'")
    end = APP.index("async function connectAtlassianCloudMcp", start)
    save_handler = APP[start:end]

    assert save_handler.index("fetch('/api/config/confluence'") < save_handler.index(
        "await connectAtlassianCloudMcp()"
    )
    assert "atlassian.net" in save_handler


def test_cloud_mcp_connect_cannot_strand_the_connecting_state():
    start = APP.index("async function connectAtlassianCloudMcp")
    end = APP.index("// Rovo MCP is the explicit Atlassian SSO", start)
    handler = APP[start:end]

    assert "atlassianJiraUrlInput" not in handler
    assert "atlassianSiteValues('jira')" in handler
    # Anything that runs before `try` and throws leaves the button pulsing forever.
    before_try = handler[: handler.index("try {")]
    assert "atlassianSiteValues" not in before_try


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
    assert INDEX.count('class="atlassian-mcp-wrap"') == 2
    assert ".atlassian-mcp-cancel {" in STYLE
    assert "position: absolute" in STYLE[STYLE.index(".atlassian-mcp-cancel {") :][:300]

    cloud = APP[APP.index("async function connectAtlassianCloudMcp") : APP.index("// Rovo MCP is the explicit Atlassian SSO")]
    assert "new AbortController()" in cloud
    assert "signal" in cloud

    rovo = APP[APP.index("atlassianAddSiteBtn.addEventListener('click'") : APP.index("/* ── GitHub")]
    assert "new AbortController()" in rovo
    assert "popup.close()" in rovo


def test_mcp_buttons_have_connecting_and_connected_feedback():
    assert "atlassian-mcp-connect" in INDEX
    assert "_setAtlassianMcpConnectState" in APP
    assert "atlassian-mcp-connect--connecting" in APP
    assert "atlassian-mcp-connect--connected" in APP
    assert "Cloud MCP Connected ✓" in APP
    assert "Rovo MCP Connected ✓" in APP
    assert "@property --atlassian-mcp-angle" in STYLE
    assert "atlassian-mcp-edge-spin" in STYLE
