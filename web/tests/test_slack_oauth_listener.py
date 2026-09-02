"""Regression guards for Slack OAuth callback listener startup (#169)."""

from pathlib import Path


MCP = (Path(__file__).parent.parent / "skills" / "slack" / "mcp_client.py").read_text(
    encoding="utf-8"
)
ROUTE = (Path(__file__).parent.parent / "routes" / "slack.py").read_text(encoding="utf-8")
APP = (Path(__file__).parent.parent / "static" / "app.js").read_text(encoding="utf-8")
CALLBACK = (Path(__file__).parent.parent / "oauth" / "callback_server.py").read_text(encoding="utf-8")


def test_slack_oauth_binds_shared_listener_before_saving_pkce():
    start = MCP.index("def start_oauth(")
    body = MCP[start : MCP.index("\ndef _exchange_code", start)]
    assert "stop_all()" in body
    assert "start_callback_listener" in body
    assert body.index("start_callback_listener") < body.index("_save_pkce")
    assert "port_candidates=[_CALLBACK_PORT]" in body
    assert 'return {"error":' in body
    assert body.index("_save_pkce") < body.index("listener_ready.set()")
    assert "ready_event=listener_ready" in body
    assert "ready_event.wait(_TIMEOUT_SECONDS)" in CALLBACK


def test_slack_oauth_startup_error_is_an_http_error_and_visible_to_users():
    route_start = ROUTE.index("async def slack_oauth_start()")
    route_body = ROUTE[route_start : ROUTE.index("\n\n#", route_start)]
    assert "status_code=503" in route_body
    assert "detail=result[\"error\"]" in route_body
    assert "if (!res.ok) throw new Error(d.detail" in APP
