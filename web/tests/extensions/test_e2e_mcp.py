"""End-to-end: start session → simulate assistant tool calls → commit → connection persisted."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import app


@pytest.fixture(autouse=True)
def reset_sessions():
    """Clear the shared _SESSIONS store before each test to prevent state leak."""
    import extensions.tools as ext_tools
    with ext_tools._SESSIONS._lock:
        ext_tools._SESSIONS._sessions.clear()
    yield
    with ext_tools._SESSIONS._lock:
        ext_tools._SESSIONS._sessions.clear()


def test_atlassian_url_prefill_and_commit():
    client = TestClient(app)
    r = client.post("/api/extensions/setup/start", json={
        "extension_type": "mcp",
        "raw_input": "https://mcp.atlassian.com/v1/mcp",
    })
    assert r.status_code == 200
    init = r.json()
    sid = init["session_id"]
    assert init["initial_field_state"]["url"] == "https://mcp.atlassian.com/v1/mcp"
    assert init["initial_field_state"]["auth_type"] == "oauth2"
    assert init["initial_field_state"]["name"].lower().startswith("atlassian")

    from extensions.tools import tool_set_field
    tool_set_field({"session_id": sid, "field_path": "oauth_provider_id",
                    "value": "mcp-atlassian-xyz"})

    with patch("mcp.manager.add_or_update") as upd:
        upd.return_value = {"ok": True, "id": "mcp-atlassian", "tool_count": 47}
        r = client.post("/api/extensions/setup/commit", json={"session_id": sid})
    # commit probes first (_dry_run=True) then installs — 2 calls expected
    assert upd.call_count == 2
    assert r.status_code == 200
    assert r.json()["connection_id"] == "mcp-atlassian"

    r = client.get(f"/api/extensions/setup/draft/{sid}")
    assert r.status_code == 404


def test_failed_install_returns_400_and_keeps_session():
    client = TestClient(app)
    r = client.post("/api/extensions/setup/start", json={"extension_type": "mcp"})
    sid = r.json()["session_id"]
    from extensions.tools import tool_set_field
    tool_set_field({"session_id": sid, "field_path": "url", "value": "https://bad.example/mcp"})
    tool_set_field({"session_id": sid, "field_path": "auth_type", "value": "bearer"})
    tool_set_field({"session_id": sid, "field_path": "auth_value", "value": "bad"})
    with patch("mcp.manager.add_or_update") as upd:
        # First call is the probe (_dry_run=True) — returns ok so probe passes.
        # Second call is the install — returns the auth failure.
        upd.side_effect = [
            {"ok": True, "tool_count": 1},    # probe: connected, 1 tool
            {"ok": False, "error": "HTTP 401 invalid_token"},  # install: fails
        ]
        r = client.post("/api/extensions/setup/commit", json={"session_id": sid})
    assert upd.call_count == 2
    assert r.status_code == 400
    assert "401" in r.json()["detail"]
    # Session preserved so the user can correct and retry.
    r = client.get(f"/api/extensions/setup/draft/{sid}")
    assert r.status_code == 200
