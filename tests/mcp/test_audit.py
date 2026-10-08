"""MCP transport audit coverage and duplicate-suppression tests."""
import time
from unittest.mock import AsyncMock

from mcp import audit
from mcp.generic_client import GenericMCPClient
import turn_telemetry


def test_direct_mcp_call_schedules_namespaced_record(monkeypatch):
    captured = []
    monkeypatch.setattr(turn_telemetry, "schedule_tool_call", lambda *args, **kwargs: captured.append((args, kwargs)))

    audit.schedule_mcp_call(
        {"id": "mcp-calendar"}, "manage_event", "success", time.perf_counter()
    )

    assert captured[0][0][0] == "mcp-calendar__manage_event"
    assert captured[0][0][1] == "success"


def test_model_selected_mcp_call_is_not_double_recorded(monkeypatch):
    captured = []
    monkeypatch.setattr(turn_telemetry, "schedule_tool_call", lambda *args, **kwargs: captured.append((args, kwargs)))
    token = turn_telemetry.mcp_audit_suppressed.set(True)
    try:
        audit.schedule_mcp_call(
            {"id": "mcp-calendar"}, "manage_event", "success", time.perf_counter()
        )
    finally:
        turn_telemetry.mcp_audit_suppressed.reset(token)

    assert captured == []


def test_generic_client_call_audits_without_changing_result(monkeypatch):
    client = GenericMCPClient.__new__(GenericMCPClient)
    client._cfg = {"id": "mcp-test"}
    client._async_call = AsyncMock(return_value="original-result")
    captured = []
    monkeypatch.setattr(audit, "schedule_mcp_call", lambda *args, **kwargs: captured.append((args, kwargs)))

    result = client.call("read_item", {"id": "123"})

    assert result == "original-result"
    assert captured[0][0][1:3] == ("read_item", "success")
