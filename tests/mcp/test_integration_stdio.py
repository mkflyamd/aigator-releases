"""End-to-end smoke test for the stdio MCP transport.

Exercises the FULL path through the FastAPI route handler with no mocks:
  1. POST /api/config/mcp with a real stdio payload that spawns
     tests/mcp/fixtures/fake_mcp_server.py under sys.executable.
  2. GET /api/config/mcp — confirm the new connection is listed.
  3. Invoke the registered tool through shared.TOOL_DISPATCH (the same
     mechanism the agent loop uses) — confirm the echo response round-trips.
  4. DELETE /api/config/mcp/{id} — confirm it's gone.

Config storage is isolated to a tmp_path so the test never pollutes the
real ~/.config/teamspoc/config.json.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


FIXTURE = str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Redirect config persistence to a tmp file for the duration of the test."""
    import config
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_FILE", cfg_file)
    return cfg_file


@pytest.fixture
def app_client(isolated_config):
    """A FastAPI TestClient with the MCP router mounted."""
    from routes.mcp_routes import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_stdio_end_to_end_smoke(app_client):
    """Add → list → invoke tool → delete, all over the real subprocess path."""
    import shared
    from mcp.manager import _unregister

    created_id = None
    try:
        # 1. POST: connect to a real subprocess MCP server.
        payload = {
            "transport": "stdio",
            "command": sys.executable,
            "args": [FIXTURE],
            "env": {},
        }
        r = app_client.post("/api/config/mcp", json=payload)
        assert r.status_code == 200, f"POST failed: {r.status_code} {r.text}"
        data = r.json()
        assert data["ok"] is True
        assert data["name"] == "fake"
        assert data["tool_count"] == 1
        created_id = data["id"]
        assert created_id == "mcp-fake"

        # 2. GET: the new connection appears in the list with transport=stdio.
        r = app_client.get("/api/config/mcp")
        assert r.status_code == 200
        listing = r.json()["connections"]
        match = next((c for c in listing if c["id"] == created_id), None)
        assert match is not None, f"Connection not in list: {listing}"
        assert match["transport"] == "stdio"
        assert match["tool_count"] == 1
        assert match["command"] == sys.executable

        # 3. Invoke the registered tool through shared.TOOL_DISPATCH —
        #    same mechanism the agent loop uses to call MCP tools.
        tool_key = f"{created_id}__echo"
        assert tool_key in shared.TOOL_DISPATCH, (
            f"Tool not registered. Available: {list(shared.TOOL_DISPATCH)}"
        )
        handler = shared.TOOL_DISPATCH[tool_key]
        result = handler(text="hello-world")
        assert isinstance(result, dict)
        assert "result" in result, f"Tool returned error: {result}"
        # The fake echoes the args dict stringified.
        assert "hello-world" in result["result"]

        # 4. DELETE: connection and its tools are gone.
        r = app_client.delete(f"/api/config/mcp/{created_id}")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r = app_client.get("/api/config/mcp")
        assert r.status_code == 200
        listing = r.json()["connections"]
        assert not any(c["id"] == created_id for c in listing), (
            f"Connection survived DELETE: {listing}"
        )
        assert tool_key not in shared.TOOL_DISPATCH

    finally:
        # Belt-and-suspenders cleanup so a mid-test failure can't pollute
        # the shared registries for sibling tests.
        if created_id is not None:
            _unregister(created_id)
