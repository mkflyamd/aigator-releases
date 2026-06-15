import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

from fastapi.testclient import TestClient
from app import app


def test_start_returns_session_id_and_prompt():
    client = TestClient(app)
    r = client.post("/api/extensions/setup/start", json={"extension_type": "mcp"})
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert "system_prompt" in body
    assert body["initial_field_state"] == {"transport": "http"}
    assert "config_schema" in body


def test_start_with_raw_input_prefills_url():
    client = TestClient(app)
    r = client.post("/api/extensions/setup/start", json={
        "extension_type": "mcp",
        "raw_input": "https://mcp.atlassian.com/v1/mcp",
    })
    body = r.json()
    assert body["initial_field_state"].get("url") == "https://mcp.atlassian.com/v1/mcp"
    assert body["initial_field_state"].get("auth_type") == "oauth2"


def test_events_endpoint_drains_session_events():
    client = TestClient(app)
    r = client.post("/api/extensions/setup/start", json={"extension_type": "mcp"})
    sid = r.json()["session_id"]
    from extensions.tools import tool_set_field
    tool_set_field({"session_id": sid, "field_path": "name", "value": "Test"})
    r = client.get(f"/api/extensions/setup/events/{sid}")
    events = r.json()["events"]
    assert any(e["type"] == "field_update" and e["field_path"] == "name" for e in events)


def test_events_unknown_session_404():
    client = TestClient(app)
    r = client.get("/api/extensions/setup/events/does-not-exist")
    assert r.status_code == 404


def test_commit_unknown_session_returns_404():
    client = TestClient(app)
    r = client.post("/api/extensions/setup/commit", json={"session_id": "does-not-exist"})
    assert r.status_code == 404
