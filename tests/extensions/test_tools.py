import pytest
from extensions.sessions import SessionStore
from extensions import tools as t


@pytest.fixture(autouse=True)
def reset_store(monkeypatch):
    monkeypatch.setattr(t, "_SESSIONS", SessionStore())


def test_set_and_get_field_round_trip():
    sid = t._SESSIONS.create("mcp")
    t.tool_set_field({"session_id": sid, "field_path": "url", "value": "https://x"})
    assert t.tool_get_field({"session_id": sid, "field_path": "url"}) == {"value": "https://x"}


def test_set_field_emits_field_update_event():
    sid = t._SESSIONS.create("mcp")
    t.tool_set_field({"session_id": sid, "field_path": "name", "value": "Atlassian"})
    events = t._SESSIONS.drain_events(sid)
    assert any(e["type"] == "field_update" and e["field_path"] == "name" for e in events)


def test_highlight_field_emits_highlight_event():
    sid = t._SESSIONS.create("mcp")
    t.tool_highlight_field({"session_id": sid, "field_path": "auth_value"})
    events = t._SESSIONS.drain_events(sid)
    assert events[-1] == {"type": "highlight", "field_path": "auth_value"}


def test_test_connection_uses_adapter():
    sid = t._SESSIONS.create("mcp")
    t._SESSIONS.set(sid, "url", "https://x")
    t._SESSIONS.set(sid, "auth_type", "bearer")
    t._SESSIONS.set(sid, "auth_value", "tok")
    from unittest.mock import patch
    from extensions.base import TestResult
    with patch("extensions.tools.get_adapter") as ga:
        ga.return_value.test_connection.return_value = TestResult(ok=True, detail="Found 3 tools", tool_count=3)
        out = t.tool_test_connection({"session_id": sid})
        assert out["ok"] is True
        assert out["tool_count"] == 3


def test_normalize_input_writes_parsed_fields_to_draft():
    sid = t._SESSIONS.create("mcp")
    from unittest.mock import patch
    with patch("extensions.tools.get_adapter") as ga:
        ga.return_value.normalize.return_value = {"url": "https://x", "auth_type": "bearer"}
        t.tool_normalize_input({"session_id": sid, "raw": "https://x"})
    draft = t._SESSIONS.get(sid)
    assert draft["url"] == "https://x"
    assert draft["auth_type"] == "bearer"


def test_normalize_input_unknown_session_returns_error():
    result = t.tool_normalize_input({"session_id": "no-such-sid", "raw": "https://x"})
    assert result["ok"] is False
    assert "Unknown session" in result["error"]


def test_test_connection_unknown_session_returns_error():
    result = t.tool_test_connection({"session_id": "no-such-sid"})
    assert result["ok"] is False
    assert "Unknown session" in result["error"]


def test_set_field_unknown_session_returns_error():
    result = t.tool_set_field({"session_id": "no-such", "field_path": "url", "value": "x"})
    assert result["ok"] is False
    assert "Unknown session" in result["error"]


def test_highlight_field_unknown_session_returns_error():
    result = t.tool_highlight_field({"session_id": "no-such", "field_path": "auth_value"})
    assert result["ok"] is False
    assert "Unknown session" in result["error"]
