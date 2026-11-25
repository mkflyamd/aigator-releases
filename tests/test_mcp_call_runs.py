"""An MCP tool call runs under the Run Supervisor: bounded, stoppable, and honest about what it left behind."""
import io
import json
import os
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import shared  # noqa: E402
import timeouts  # noqa: E402
from mcp import manager  # noqa: E402
from mcp.stdio_client import StdioMCPClient  # noqa: E402
from runs.records import RunStore  # noqa: E402
from runs.supervisor import RunSupervisor, reset_supervisor  # noqa: E402
from runs.turn import current_turn  # noqa: E402

SCHEMA = {"type": "object", "properties": {}}


@pytest.fixture
def sup(tmp_path):
    supervisor = RunSupervisor(RunStore(tmp_path / "runs.db"), max_abandoned_per_server=2)
    reset_supervisor(supervisor)
    yield supervisor
    reset_supervisor(None)


def _register(monkeypatch, transport="http", conn_id="mcp-demo"):
    monkeypatch.setattr(shared, "TOOL_DISPATCH", {})
    monkeypatch.setattr(shared, "TOOLS", [])
    monkeypatch.setattr(shared, "TOOL_STATUS", {})
    monkeypatch.setattr(shared, "SKILL_TOOLS_MAP", {})
    conn = {
        "id": conn_id, "name": "Demo", "transport": transport, "url": "https://demo.example.com/mcp",
        "command": "demo-mcp", "args": [], "env": {},
        "cached_tools": [{"name": "lookup", "description": "d", "input_schema": SCHEMA}],
    }
    manager._register(conn)
    (alias,) = [a for a in shared.TOOL_DISPATCH if "lookup" in a]
    return shared.TOOL_DISPATCH[alias]


class Hang:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, tool, arguments):
        self.entered.set()
        self.release.wait(10)
        return "late"


def _client(call):
    client = MagicMock()
    client.call.side_effect = call
    return client


def test_a_call_leaves_a_thin_record_for_its_tab(monkeypatch, sup):
    handler = _register(monkeypatch)
    with patch("mcp.manager._client_for", return_value=_client(lambda t, a: "the secret answer")), \
            patch("mcp.manager._mark_health_result"):
        result = handler(_context_id="tab-1", query="the secret question")
    assert result == {"result": "the secret answer"}
    (record,) = sup.list("tab-1")
    assert record["kind"] == "mcp_call" and record["state"] == "finished"
    assert record["facts"]["server"] == "Demo" and record["facts"]["tool"] == "lookup"
    assert "secret" not in json.dumps(record)


def test_a_tool_error_still_reaches_the_model_as_before(monkeypatch, sup):
    handler = _register(monkeypatch)

    def refuse(tool, arguments):
        raise RuntimeError("auth_error:Demo:token expired")

    with patch("mcp.manager._client_for", return_value=_client(refuse)):
        result = handler(_context_id="tab-1")
    assert result["_mcp_auth_error"] is True and "token expired" in result["error"]


def test_a_call_past_its_budget_tells_the_model_what_is_known(monkeypatch, sup):
    handler = _register(monkeypatch)
    hang = Hang()
    with timeouts.override("mcp", run_ms=150), patch("mcp.manager._client_for", return_value=_client(hang)), \
            patch("mcp.manager._mark_health_result"):
        result = handler(_context_id="tab-1")
    hang.release.set()
    assert "still running" in result["error"] and "may still complete" in result["error"]
    assert result["_mcp_call"]["state"] == "abandoned"
    assert sup.list("tab-1")[0]["state"] == "abandoned"


def test_a_stopped_turn_walks_away_from_the_call_and_sends_a_cancel_notice(monkeypatch, sup):
    handler = _register(monkeypatch, transport="stdio")
    hang = Hang()
    client = _client(hang)
    out = {}

    def run():
        token = current_turn.set("turn-1")
        try:
            with patch("mcp.manager._client_for", return_value=client), patch("mcp.manager._mark_health_result"):
                out["result"] = handler(_context_id="tab-1")
        finally:
            current_turn.reset(token)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert hang.entered.wait(5)
    started = time.monotonic()
    assert len(sup.cancel_turn("turn-1")) == 1
    thread.join(5)
    hang.release.set()
    assert time.monotonic() - started < 2
    assert "stopped" in out["result"]["error"]
    client.cancel_active_call.assert_called_once_with("stopped")


def test_a_timed_out_stdio_server_is_released_so_the_next_call_starts_fresh(monkeypatch, sup):
    handler = _register(monkeypatch, transport="stdio")
    hang = Hang()
    with timeouts.override("mcp", run_ms=150), patch("mcp.manager._client_for", return_value=_client(hang)), \
            patch("mcp.manager.release_from_pool") as release, patch("mcp.manager._mark_health_result"):
        handler(_context_id="tab-1")
    hang.release.set()
    release.assert_called_once()


def test_a_server_at_its_abandoned_limit_is_marked_unhealthy_and_gets_no_more_calls(monkeypatch, sup):
    handler = _register(monkeypatch)
    hangs = [Hang(), Hang()]
    with timeouts.override("mcp", run_ms=100), patch("mcp.manager._mark_health_result") as mark:
        for hang in hangs:
            with patch("mcp.manager._client_for", return_value=_client(hang)):
                handler(_context_id="tab-1")
        mark.assert_called_once()
        assert mark.call_args.args[0] == "mcp-demo" and mark.call_args.kwargs["ok"] is False

        untouched = _client(lambda t, a: "never sent")
        with patch("mcp.manager._client_for", return_value=untouched):
            refused = handler(_context_id="tab-1")
        untouched.call.assert_not_called()
        assert "no new call was sent" in refused["error"]

        for hang in hangs:
            hang.release.set()
        deadline = time.monotonic() + 5
        while sup.abandoned_count("mcp-demo") and time.monotonic() < deadline:
            time.sleep(0.01)
        with patch("mcp.manager._client_for", return_value=_client(lambda t, a: "ok")):
            assert handler(_context_id="tab-1") == {"result": "ok"}


# ── the stdio cancel notice ─────────────────────────────────────────────────

class _Stdin(io.StringIO):
    pass


def _stdio_client():
    client = object.__new__(StdioMCPClient)
    client._name = "demo"
    client._cfg = {"name": "demo"}
    client._next_id = 7
    client._active_call_id = None
    client._proc = MagicMock()
    client._proc.poll.return_value = None
    client._proc.stdin = _Stdin()
    return client


def test_stdio_cancel_names_the_request_that_is_in_flight():
    client = _stdio_client()
    seen = {}

    def send(method, params=None, timeout=None):
        seen["id"] = client._active_call_id
        client.cancel_active_call("stopped")
        return {"result": {"content": [{"type": "text", "text": "x"}]}}

    with patch.object(StdioMCPClient, "_send", side_effect=send), patch("mcp.audit.schedule_mcp_call"):
        client.call("lookup", {})
    sent = [json.loads(line) for line in client._proc.stdin.getvalue().splitlines()]
    assert sent == [{"jsonrpc": "2.0", "method": "notifications/cancelled",
                     "params": {"requestId": seen["id"], "reason": "stopped"}}]
    assert client._active_call_id is None


def test_stdio_cancel_with_nothing_in_flight_sends_nothing():
    client = _stdio_client()
    client.cancel_active_call("stopped")
    assert client._proc.stdin.getvalue() == ""
