import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from fastapi import FastAPI
from routes.mcp_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_list_connections_empty():
    with patch("routes.mcp_routes.list_with_status", return_value=[]):
        r = client.get("/api/config/mcp")
    assert r.status_code == 200
    assert r.json() == {"connections": []}


def test_add_connection_missing_url():
    r = client.post("/api/config/mcp", json={"url": "", "auth_type": "none", "auth_value": ""})
    assert r.status_code == 400


def test_add_connection_success():
    with patch("routes.mcp_routes.add_or_update", return_value={"ok": True, "id": "mcp-crm", "name": "CRM", "tool_count": 3}):
        r = client.post("/api/config/mcp", json={"url": "http://host/mcp", "auth_type": "none", "auth_value": ""})
    assert r.status_code == 200
    assert r.json()["name"] == "CRM"


def test_delete_connection():
    with patch("routes.mcp_routes.remove", return_value={"ok": True}):
        r = client.delete("/api/config/mcp/mcp-crm")
    assert r.status_code == 200


def test_delete_connection_not_found():
    with patch("routes.mcp_routes.remove", return_value={"ok": False, "error": "Connection not found"}):
        r = client.delete("/api/config/mcp/mcp-missing")
    assert r.status_code == 404


def test_health_check():
    with patch("routes.mcp_routes.health_check", return_value={"ok": True, "latency_ms": 42}):
        r = client.post("/api/config/mcp/mcp-crm/health")
    assert r.status_code == 200
    assert r.json()["latency_ms"] == 42


def test_add_connection_stdio_success():
    with patch("routes.mcp_routes.add_or_update", return_value={"ok": True, "id": "mcp-playwright", "name": "playwright", "tool_count": 23}):
        r = client.post("/api/config/mcp", json={
            "transport": "stdio",
            "command": "npx",
            "args": ["@playwright/mcp@latest"],
            "env": {},
        })
    assert r.status_code == 200
    assert r.json()["name"] == "playwright"


def test_add_connection_stdio_missing_command():
    r = client.post("/api/config/mcp", json={
        "transport": "stdio",
        "command": "",
        "args": [],
    })
    assert r.status_code == 400


def test_add_connection_http_explicit_transport():
    """Sending transport=http explicitly works (backwards compat with no field also works)."""
    with patch("routes.mcp_routes.add_or_update", return_value={"ok": True, "id": "mcp-crm", "name": "CRM", "tool_count": 1}):
        r = client.post("/api/config/mcp", json={
            "transport": "http",
            "url": "http://host/mcp",
            "auth_type": "none",
            "auth_value": "",
        })
    assert r.status_code == 200


# ── Complete-secrets endpoint for a pending plugin connection (Increment
# 4b, 2026-08-07 milestone). ──────────────────────────────────────────────

def _pending_conn(**overrides):
    conn = {
        "id": "plugin:dd-plugin:datadog", "name": "datadog", "transport": "stdio",
        "enabled": False, "missing_secrets": ["DATADOG_API_KEY"], "plugin_id": "dd-plugin",
    }
    conn.update(overrides)
    return conn


def test_complete_secrets_not_found():
    with patch("routes.mcp_routes._load_connections", return_value=[]):
        r = client.post("/api/config/mcp/plugin:ghost:server/complete-secrets", json={"values": {}})
    assert r.status_code == 404


def test_complete_secrets_rejects_already_enabled_connection():
    enabled_conn = _pending_conn(enabled=True)
    with patch("routes.mcp_routes._load_connections", return_value=[enabled_conn]):
        r = client.post("/api/config/mcp/plugin:dd-plugin:datadog/complete-secrets", json={"values": {}})
    assert r.status_code == 400


def test_complete_secrets_success():
    pending = _pending_conn()
    with patch("routes.mcp_routes._load_connections", return_value=[pending]), \
         patch("routes.mcp_routes.complete_pending_secrets",
               return_value={"ok": True, "id": "plugin:dd-plugin:datadog", "tool_count": 2}) as mock_complete:
        r = client.post(
            "/api/config/mcp/plugin:dd-plugin:datadog/complete-secrets",
            json={"values": {"DATADOG_API_KEY": "secret123"}},
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    mock_complete.assert_called_once_with("plugin:dd-plugin:datadog", {"DATADOG_API_KEY": "secret123"})


def test_complete_secrets_failure_returns_200_ok_false():
    """A bad credential / connect failure is a 200 ok:false (mirrors
    add_connection's own auth_probe_failed convention) — not a 4xx/5xx —
    so the frontend can re-render the form inline with the error."""
    pending = _pending_conn()
    with patch("routes.mcp_routes._load_connections", return_value=[pending]), \
         patch("routes.mcp_routes.complete_pending_secrets",
               return_value={"ok": False, "error": "connect failed"}):
        r = client.post(
            "/api/config/mcp/plugin:dd-plugin:datadog/complete-secrets",
            json={"values": {"DATADOG_API_KEY": "wrong"}},
        )
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "connect failed"}
