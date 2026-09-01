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
import time
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


def _poll_until_connected(app_client, created_id, timeout=10.0):
    """Stdio connect is async (background worker discovers tools + updates
    the record; POST returns immediately with status=connecting) — poll GET
    like the real UI does until the worker finishes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        listing = app_client.get("/api/config/mcp").json()["connections"]
        match = next((c for c in listing if c["id"] == created_id), None)
        if match is not None and match.get("connect_status") != "connecting":
            return match
        time.sleep(0.05)
    raise AssertionError(f"Connection {created_id} never left 'connecting' status within {timeout}s")


def test_stdio_end_to_end_smoke(app_client):
    """Add → list → invoke tool → delete, all over the real subprocess path."""
    import shared
    from mcp.manager import _unregister

    created_id = None
    try:
        # 1. POST: connect to a real subprocess MCP server. Stdio connects
        # are async — this returns immediately with status=connecting;
        # the id is derived from the pre-connect command guess, not the
        # server's self-reported name (that's only known once the
        # background worker completes — see step 2).
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
        assert data["status"] == "connecting"
        created_id = data["id"]

        # 2. Poll GET until the background connect finishes, then confirm
        # the connection is listed with transport=stdio and the real
        # server-reported name/tool_count.
        match = _poll_until_connected(app_client, created_id)
        assert match["name"] == "fake"
        assert match["transport"] == "stdio"
        assert match["tool_count"] == 1
        # PR #10 review fix: command/args/url are now returned as _hint fields
        # (masked) rather than raw — sys.executable has no placeholder syntax
        # so _command_hint passes it through verbatim, but the field is named
        # command_hint now.
        assert match["command_hint"] == sys.executable

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
