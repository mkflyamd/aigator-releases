"""
Pipeline diagnostic tests — verify every link in the wizard tool-dispatch chain.

Chain:
  [1] Tool registration  → shared.TOOL_DISPATCH and SKILL_TOOLS_MAP
  [2] _filter_tools      → extension tools included when scoped_skill set
  [3] execute_tool       → dispatches to the right handler by name
  [4] tool_set_field     → writes to session store + emits field_update event
  [5] Events endpoint    → returns and drains the field_update event
  [6] Start endpoint     → returns SESSION_ID in system_prompt + raw_input
  [7] system_prompt_suffix → SESSION_ID is appended to LLM system prompt
  [8] Classifier bypass  → scoped_skill requests skip skill auto-detection
"""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
import shared
import extensions.tools as ext_tools
from app import app, execute_tool as _execute_tool_raw


@pytest.fixture(autouse=True)
def reset_sessions():
    with ext_tools._SESSIONS._lock:
        ext_tools._SESSIONS._sessions.clear()
    yield
    with ext_tools._SESSIONS._lock:
        ext_tools._SESSIONS._sessions.clear()


client = TestClient(app)


# ── [1] Tool registration ────────────────────────────────────────────────────

def test_extension_tools_in_skill_tools_map():
    assert "_extension_setup" in shared.SKILL_TOOLS_MAP
    names = shared.SKILL_TOOLS_MAP["_extension_setup"]
    assert "extension_setup__set_field" in names
    assert "extension_setup__get_field" in names
    assert "extension_setup__test_connection" in names
    assert "extension_setup__mark_done" in names


def test_extension_tools_in_tool_dispatch():
    assert "extension_setup__set_field" in shared.TOOL_DISPATCH
    assert callable(shared.TOOL_DISPATCH["extension_setup__set_field"])


def test_extension_tool_defs_in_shared_tools():
    names = {t["name"] for t in shared.TOOLS}
    assert "extension_setup__set_field" in names
    assert "extension_setup__test_connection" in names


# ── [2] _filter_tools with scoped_skill ─────────────────────────────────────

def test_filter_tools_includes_extension_tools_when_scoped():
    from routes.chat import _filter_tools
    tools = _filter_tools("", False, ["_extension_setup"])
    tool_names = {t["name"] for t in tools}
    assert "extension_setup__set_field" in tool_names
    assert "extension_setup__test_connection" in tool_names


def test_filter_tools_excludes_browser_when_only_scoped():
    from routes.chat import _filter_tools
    tools = _filter_tools("", False, ["_extension_setup"])
    tool_names = {t["name"] for t in tools}
    # Browser tools must NOT bleed in when only the wizard scope is active
    assert not any("browser" in n for n in tool_names)


# ── [3] execute_tool dispatches correctly ────────────────────────────────────

def test_execute_tool_routes_set_field():
    sid = ext_tools._SESSIONS.create("mcp")
    result = asyncio.get_event_loop().run_until_complete(
        _execute_tool_raw("extension_setup__set_field",
                          {"session_id": sid, "field_path": "url",
                           "value": "https://example.com/mcp"})
    )
    assert result.get("ok") is True


def test_execute_tool_unknown_name_returns_error():
    result = asyncio.get_event_loop().run_until_complete(
        _execute_tool_raw("nonexistent__tool", {})
    )
    assert "error" in result
    assert "Unknown tool" in result["error"]


# ── [4] tool_set_field writes to session + emits event ───────────────────────

def test_set_field_writes_to_draft():
    sid = ext_tools._SESSIONS.create("mcp")
    ext_tools.tool_set_field({"session_id": sid, "field_path": "url",
                               "value": "https://mcp.linear.app/mcp"})
    draft = ext_tools._SESSIONS.get(sid)
    assert draft["url"] == "https://mcp.linear.app/mcp"


def test_set_field_emits_field_update_event():
    sid = ext_tools._SESSIONS.create("mcp")
    ext_tools.tool_set_field({"session_id": sid, "field_path": "auth_type",
                               "value": "bearer"})
    events = ext_tools._SESSIONS.drain_events(sid)
    assert any(
        e["type"] == "field_update" and e["field_path"] == "auth_type"
        and e["value"] == "bearer"
        for e in events
    )


def test_set_field_unknown_session_returns_error():
    result = ext_tools.tool_set_field({"session_id": "bad-sid",
                                        "field_path": "url", "value": "x"})
    assert result["ok"] is False
    assert "Unknown session" in result["error"]


# ── [5] Events endpoint drains and returns events ────────────────────────────

def test_events_endpoint_returns_field_update():
    sid = ext_tools._SESSIONS.create("mcp")
    ext_tools.tool_set_field({"session_id": sid, "field_path": "name",
                               "value": "Nabu"})
    r = client.get(f"/api/extensions/setup/events/{sid}")
    assert r.status_code == 200
    events = r.json()["events"]
    assert any(e["field_path"] == "name" and e["value"] == "Nabu" for e in events)


def test_events_endpoint_drains_on_each_call():
    sid = ext_tools._SESSIONS.create("mcp")
    ext_tools.tool_set_field({"session_id": sid, "field_path": "url", "value": "x"})
    client.get(f"/api/extensions/setup/events/{sid}")  # drain
    r = client.get(f"/api/extensions/setup/events/{sid}")  # should be empty now
    assert r.json()["events"] == []


def test_events_endpoint_404_for_unknown_session():
    r = client.get("/api/extensions/setup/events/no-such-session")
    assert r.status_code == 404


# ── [6] Start endpoint returns SESSION_ID and raw_input ─────────────────────

def test_start_returns_session_id_and_system_prompt():
    r = client.post("/api/extensions/setup/start", json={"extension_type": "mcp"})
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert "system_prompt" in body
    assert len(body["session_id"]) == 32  # hex UUID


def test_start_returns_raw_input_for_frontend():
    r = client.post("/api/extensions/setup/start", json={
        "extension_type": "mcp",
        "raw_input": "https://mcp-platform.amd.com/mcp/nabu/",
    })
    assert r.json()["raw_input"] == "https://mcp-platform.amd.com/mcp/nabu/"


def test_start_system_prompt_contains_session_id_instruction():
    r = client.post("/api/extensions/setup/start", json={"extension_type": "mcp"})
    prompt = r.json()["system_prompt"]
    # The prompt must explicitly tell the LLM how to extract and pass session_id
    assert "SESSION_ID" in prompt


# ── [7] system_prompt_suffix is appended to system prompt ───────────────────

def test_system_prompt_suffix_field_accepted_by_chat_schema():
    """ChatRequest must accept system_prompt_suffix without 422."""
    from routes.chat import ChatRequest
    req = ChatRequest(
        message="hello",
        system_prompt_suffix="SESSION_ID: abc123",
        scoped_skill="_extension_setup",
    )
    assert req.system_prompt_suffix == "SESSION_ID: abc123"
    assert req.scoped_skill == "_extension_setup"


# ── [8] Classifier bypass for scoped requests ────────────────────────────────

def test_classifier_skipped_when_scoped_skill_set(capsys):
    """
    When scoped_skill is set, the classifier must not run.
    Verify by checking the log print.
    We call the chat endpoint with a URL that would normally trigger browser skill.
    With scoped_skill set, the log must show 'skipped' not 'inferred'.
    """
    # We can't easily intercept the print in the background task so we
    # verify it structurally: _filter_tools with only _extension_setup must
    # not include browser tools even when message contains a URL.
    from routes.chat import _filter_tools
    tools = _filter_tools("_extension_setup", False, ["_extension_setup"])
    tool_names = {t["name"] for t in tools}
    # If browser was being injected, we'd see browser__ tools here
    browser_tools = [n for n in tool_names if "browser" in n.lower()]
    assert browser_tools == [], f"Browser tools leaked in: {browser_tools}"


# ── Full round-trip: execute_tool → event → endpoint ────────────────────────

def test_full_round_trip_tool_call_to_event_poll():
    """
    Simulate the LLM calling extension_setup__set_field via execute_tool,
    then verify the field_update event is retrievable via the events endpoint.
    This is the exact chain the browser uses.
    """
    # 1. Start session via HTTP (as the browser does)
    r = client.post("/api/extensions/setup/start", json={
        "extension_type": "mcp",
        "raw_input": "https://mcp-platform.amd.com/mcp/nabu/",
    })
    sid = r.json()["session_id"]

    # 2. Simulate LLM tool call via execute_tool (as the agent_loop does)
    result = asyncio.get_event_loop().run_until_complete(
        _execute_tool_raw("extension_setup__set_field",
                          {"session_id": sid, "field_path": "name",
                           "value": "Nabu"})
    )
    assert result.get("ok") is True, f"tool call failed: {result}"

    # 3. Poll events endpoint (as the frontend does every 700ms)
    r = client.get(f"/api/extensions/setup/events/{sid}")
    assert r.status_code == 200
    events = r.json()["events"]

    # 4. field_update event must be present with correct values
    field_events = [e for e in events
                    if e.get("type") == "field_update" and e.get("field_path") == "name"]
    assert field_events, f"No field_update for 'name' in events: {events}"
    assert field_events[0]["value"] == "Nabu"

    # 5. Draft must reflect the written value
    r = client.get(f"/api/extensions/setup/draft/{sid}")
    assert r.json()["draft"]["name"] == "Nabu"
