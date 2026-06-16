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
