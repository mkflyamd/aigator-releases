"""An MCP tool call runs under the Run Supervisor: bounded, stoppable, and honest about what it left behind."""
import asyncio
import io
import json
import os
import queue
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import shared  # noqa: E402
import timeouts  # noqa: E402
import turn_telemetry  # noqa: E402
from mcp import manager  # noqa: E402
from mcp import stdio_client  # noqa: E402
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


def _register(monkeypatch, transport="http", conn_id="mcp-demo", tools=("lookup",), **overrides):
    monkeypatch.setattr(shared, "TOOL_DISPATCH", {})
    monkeypatch.setattr(shared, "TOOLS", [])
    monkeypatch.setattr(shared, "TOOL_STATUS", {})
    monkeypatch.setattr(shared, "SKILL_TOOLS_MAP", {})
    conn = {
        "id": conn_id, "name": "Demo", "transport": transport, "url": "https://demo.example.com/mcp",
        "command": "demo-mcp", "args": [], "env": {},
        "cached_tools": [{"name": t, "description": "d", "input_schema": SCHEMA} for t in tools],
        **overrides,
    }
    manager._register(conn)
    handlers = {t: shared.TOOL_DISPATCH[next(a for a in shared.TOOL_DISPATCH if t in a)] for t in tools}
    return handlers[tools[0]] if len(tools) == 1 else handlers


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
    client.in_flight.return_value = 0
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


def test_a_stopped_turn_walks_away_cancels_its_own_request_and_releases_the_process(monkeypatch, sup):
    handler = _register(monkeypatch, transport="stdio")
    hang = Hang()
    client = MagicMock(spec=StdioMCPClient)
    client.in_flight.return_value = 0

    def call(tool, arguments, on_request=None):
        on_request(41)
        return hang(tool, arguments)

    client.call.side_effect = call
    out = {}

    def run():
        token = current_turn.set("turn-1")
        try:
            with patch("mcp.manager._client_for", return_value=client), patch("mcp.manager._mark_health_result"),                     patch("mcp.manager.release_from_pool") as release:
                out["result"] = handler(_context_id="tab-1")
                out["release"] = release
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
    client.cancel_request.assert_called_once_with(41, "stopped")
    out["release"].assert_called_once()
    assert out["release"].call_args.args[1] is client


def test_a_timed_out_stdio_server_is_released_so_the_next_call_starts_fresh(monkeypatch, sup):
    handler = _register(monkeypatch, transport="stdio")
    hang = Hang()
    with timeouts.override("mcp", run_ms=150), patch("mcp.manager._client_for", return_value=_client(hang)), \
            patch("mcp.manager.release_from_pool") as release, patch("mcp.manager._mark_health_result"):
        handler(_context_id="tab-1")
    hang.release.set()
    release.assert_called_once()


def test_a_stdio_server_that_times_out_on_its_own_says_the_call_may_still_have_happened(monkeypatch, sup):
    handler = _register(monkeypatch, transport="stdio")

    def stalled(tool, arguments):
        raise TimeoutError("MCP server did not respond within 30.0s")

    with patch("mcp.manager._client_for", return_value=_client(stalled)), patch("mcp.manager.release_from_pool"):
        result = handler(_context_id="tab-1")
    assert "check before running it again" in result["error"]


def test_audit_suppression_holds_inside_the_worker_so_a_call_is_counted_once(monkeypatch, sup):
    handler = _register(monkeypatch)
    token = turn_telemetry.mcp_audit_suppressed.set(True)
    try:
        with patch("mcp.manager._client_for",
                   return_value=_client(lambda t, a: str(turn_telemetry.mcp_audit_suppressed.get()))):
            assert handler(_context_id="tab-1") == {"result": "True"}
    finally:
        turn_telemetry.mcp_audit_suppressed.reset(token)


def test_the_turn_id_reaches_the_record_when_the_tool_runs_through_to_thread(monkeypatch, sup):
    handler = _register(monkeypatch)

    async def run():
        token = current_turn.set("turn-9")
        try:
            return await asyncio.to_thread(handler, _context_id="tab-1")
        finally:
            current_turn.reset(token)

    with patch("mcp.manager._client_for", return_value=_client(lambda t, a: "ok")):
        assert asyncio.run(run()) == {"result": "ok"}
    assert sup.list("tab-1")[0]["turn_id"] == "turn-9"


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
    client._timeout = 5
    client._next_id = 7
    client._id_lock = threading.Lock()
    client._pending = {}
    client._eof = False
    client._stderr_lines = []
    client._stderr_reader = None
    client._proc = MagicMock()
    client._proc.poll.return_value = None
    client._proc.stdin = _Stdin()
    return client


def test_stdio_cancel_names_only_the_request_it_was_given():
    client = _stdio_client()
    with patch("mcp.audit.schedule_mcp_call"):
        ids, _, threads = _start_calls(client, 2)
        assert ids == [[7], [8]]
        client.cancel_request(ids[1][0], "stopped")
        client._route(_reply(7, "for a"))
        for thread in threads:
            thread.join(5)
    notices = [json.loads(line) for line in client._proc.stdin.getvalue().splitlines()
               if "notifications/cancelled" in line]
    assert notices == [{"jsonrpc": "2.0", "method": "notifications/cancelled",
                        "params": {"requestId": 8, "reason": "stopped"}}]


def _reply(request_id, text):
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text}]}}) + "\n"


def _start_calls(client, count):
    ids = [[] for _ in range(count)]
    outcomes = [{} for _ in range(count)]
    threads = []

    def run(slot):
        try:
            outcomes[slot]["value"] = client.call("lookup", {}, on_request=ids[slot].append)
        except Exception as exc:  # noqa: BLE001 - the test reads what each call ended with
            outcomes[slot]["error"] = exc

    for slot in range(count):
        thread = threading.Thread(target=run, args=(slot,), daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while not ids[slot] and time.monotonic() < deadline:
            time.sleep(0.005)
        threads.append(thread)
    return ids, outcomes, threads


def test_each_call_on_a_shared_stdio_process_gets_only_the_reply_with_its_own_id():
    client = _stdio_client()
    with patch("mcp.audit.schedule_mcp_call"):
        ids, outcomes, threads = _start_calls(client, 2)
        client._route(_reply(ids[1][0], "for second"))
        client._route(_reply(ids[0][0], "for first"))
        for thread in threads:
            thread.join(5)
    assert [o.get("value") for o in outcomes] == ["for first", "for second"]


def test_abandoning_one_call_leaves_the_other_calls_on_the_same_stdio_process_waiting_for_their_replies():
    client = _stdio_client()
    with patch("mcp.audit.schedule_mcp_call"):
        ids, outcomes, threads = _start_calls(client, 2)
        client.cancel_request(ids[0][0], "stopped")
        threads[0].join(5)
        assert not threads[0].is_alive() and "error" in outcomes[0]
        assert threads[1].is_alive() and client.in_flight() == 1
        client._proc.terminate.assert_not_called()
        client._route(_reply(ids[0][0], "too late, nobody is waiting"))
        client._route(_reply(ids[1][0], "still wanted"))
        threads[1].join(5)
    assert outcomes[1] == {"value": "still wanted"}


def test_a_dying_stdio_process_still_wakes_every_call_waiting_on_it():
    client = _stdio_client()
    with patch("mcp.audit.schedule_mcp_call"):
        ids, outcomes, threads = _start_calls(client, 2)
        client._wake_waiters(stdio_client._EOF)
        for thread in threads:
            thread.join(5)
    assert all("subprocess closed stdout" in str(o["error"]) for o in outcomes)


def test_releasing_an_old_process_does_not_evict_the_fresh_one_that_replaced_it():
    cfg = {"command": "demo-mcp", "args": [], "env": {}, "name": "demo"}
    old, fresh = MagicMock(), MagicMock()
    with patch.dict(stdio_client._pool, {stdio_client._pool_key(cfg): fresh}, clear=True):
        stdio_client.release_from_pool(cfg, old)
        assert stdio_client._pool[stdio_client._pool_key(cfg)] is fresh
        stdio_client.release_from_pool(cfg, fresh)
        assert stdio_client._pool == {}
    old.close.assert_called_once()
    fresh.close.assert_called_once()


# ── a real stdio server, no mocks ───────────────────────────────────────────

FAKE_SERVER = os.path.join(os.path.dirname(__file__), "mcp", "fixtures", "fake_mcp_server.py")


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_a_real_stdio_server_that_outlives_its_budget_gets_its_own_cancel_and_a_fresh_process(
        monkeypatch, sup, tmp_path):
    log = tmp_path / "fake-mcp.log"
    cfg = {"command": sys.executable, "args": [FAKE_SERVER], "env": {"FAKE_MCP_LOG": str(log)}, "name": "Demo"}
    handlers = _register(monkeypatch, transport="stdio", tools=("slow", "pid"), **cfg)
    try:
        first_pid = handlers["pid"](_context_id="tab-1")["result"]

        with timeouts.override("mcp", run_ms=400), patch("mcp.manager._mark_health_result"):
            started = time.monotonic()
            result = handlers["slow"](_context_id="tab-1")
        assert time.monotonic() - started < 5
        assert "still running" in result["error"] and "may still complete" in result["error"]
        assert result["_mcp_call"]["state"] == "abandoned"

        calls = [line.split()[1] for line in log.read_text().splitlines() if line.startswith("call ")]
        assert len(calls) == 1
        assert _wait_for(lambda: f"cancelled {calls[0]}" in log.read_text().splitlines())

        second_pid = handlers["pid"](_context_id="tab-1")["result"]
        assert second_pid != first_pid
    finally:
        stdio_client.release_from_pool(cfg)


def test_stopping_one_call_on_a_real_stdio_server_does_not_fail_another_call_on_the_same_process(
        monkeypatch, sup, tmp_path):
    log = tmp_path / "fake-mcp.log"
    cfg = {"command": sys.executable, "args": [FAKE_SERVER], "env": {"FAKE_MCP_LOG": str(log)}, "name": "Demo"}
    handlers = _register(monkeypatch, transport="stdio", tools=("slow", "later", "pid"), **cfg)
    out = {}

    def run(slot, turn):
        token = current_turn.set(turn)
        try:
            out[slot] = handlers[slot](_context_id="tab-1")
        finally:
            current_turn.reset(token)

    try:
        first_pid = handlers["pid"](_context_id="tab-1")["result"]
        with patch("mcp.manager._mark_health_result"):
            slow = threading.Thread(target=run, args=("slow", "turn-slow"), daemon=True)
            later = threading.Thread(target=run, args=("later", "turn-later"), daemon=True)
            slow.start()
            assert _wait_for(lambda: log.exists() and "slow" in log.read_text())
            later.start()
            assert _wait_for(lambda: "later" in log.read_text())
            assert len(sup.cancel_turn("turn-slow")) == 1
            slow.join(5)
            later.join(10)
        assert "stopped" in out["slow"]["error"]
        assert out["later"] == {"result": "answered"}
        assert handlers["pid"](_context_id="tab-1")["result"] == first_pid
    finally:
        stdio_client.release_from_pool(cfg)


def test_stopping_a_stdio_call_does_not_release_the_process_while_another_call_is_in_flight(monkeypatch, sup):
    handler = _register(monkeypatch, transport="stdio")
    hang = Hang()
    client = MagicMock(spec=StdioMCPClient)
    client.in_flight.return_value = 1

    def call(tool, arguments, on_request=None):
        on_request(41)
        return hang(tool, arguments)

    client.call.side_effect = call
    out = {}

    def run():
        token = current_turn.set("turn-1")
        try:
            with patch("mcp.manager._client_for", return_value=client), patch("mcp.manager._mark_health_result"), \
                    patch("mcp.manager.release_from_pool") as release:
                out["result"] = handler(_context_id="tab-1")
                out["release"] = release
        finally:
            current_turn.reset(token)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert hang.entered.wait(5)
    assert len(sup.cancel_turn("turn-1")) == 1
    thread.join(5)
    hang.release.set()
    client.cancel_request.assert_called_once_with(41, "stopped")
    out["release"].assert_not_called()
