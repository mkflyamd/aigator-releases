"""MCP tool calls get a thin run record. A call that outlives its budget or its turn's Stop is abandoned, not cancelled."""
import json
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import pytest

import timeouts
from runs.records import RunStore
from runs.supervisor import McpAbandoned, McpDispatchRefused, RunSupervisor

BUDGETS = timeouts.Budgets(setup_ms=0, run_ms=5000, teardown_ms=500)
SHORT = timeouts.Budgets(setup_ms=0, run_ms=150, teardown_ms=500)


@pytest.fixture
def sup(tmp_path):
    return RunSupervisor(RunStore(tmp_path / "runs.db"), max_running_per_context=2, max_abandoned_per_server=2)


def _call(sup, call, *, server="srv", tool="search", turn="turn-1", ctx="tab-1", budgets=BUDGETS, on_abandon=None):
    return sup.run_mcp_call(context_id=ctx, turn_id=turn, server_id=server, server_name=server, tool=tool,
                            budgets=budgets, call=call, on_abandon=on_abandon)


class Hang:
    """A call that stays in flight until released."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self):
        self.entered.set()
        self.release.wait(10)
        return "late"


def _in_thread(fn):
    box = {}

    def run():
        try:
            box["out"] = fn()
        except BaseException as exc:  # noqa: BLE001 - the test inspects it
            box["exc"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


def _wait(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_finished_call_has_a_thin_record(sup):
    record, value = _call(sup, lambda: "the secret result", tool="get_issue")
    assert value == "the secret result"
    assert record["kind"] == "mcp_call" and record["path"] == "mcp" and record["state"] == "finished"
    assert record["facts"]["server"] == "srv" and record["facts"]["tool"] == "get_issue"
    assert record["facts"]["timeout_ms"] == 5000
    assert record["finished_at"] >= record["created_at"]
    assert "the secret result" not in json.dumps(record)


def test_the_record_is_mirrored_to_the_store_without_results(sup):
    record, _ = _call(sup, lambda: "the secret result")
    stored = sup.get(record["id"], "tab-1")
    assert stored["state"] == "finished"
    assert "the secret result" not in json.dumps(stored)


def test_a_call_error_is_raised_unchanged_and_the_record_names_only_its_type(sup):
    def boom():
        raise RuntimeError("auth_error:srv: token abc123 expired")

    with pytest.raises(RuntimeError, match="token abc123"):
        _call(sup, boom)
    (record,) = sup.list("tab-1")
    assert record["state"] == "finished" and record["error"] == "RuntimeError"
    assert "abc123" not in json.dumps(record)


def test_a_server_timeout_is_recorded_as_timed_out(sup):
    def stalled():
        raise TimeoutError("MCP server did not respond within 30.0s")

    with pytest.raises(TimeoutError):
        _call(sup, stalled)
    (record,) = sup.list("tab-1")
    assert record["state"] == "timed_out"


def test_a_call_past_its_budget_is_abandoned(sup):
    hang = Hang()
    told = []
    with pytest.raises(McpAbandoned) as err:
        _call(sup, hang, budgets=SHORT, on_abandon=lambda reason: told.append(reason))
    hang.release.set()
    assert err.value.reason == "timeout"
    assert err.value.record["state"] == "abandoned" and err.value.record["reason"] == "timeout"
    assert told == ["timeout"]


def test_stop_abandons_the_turns_in_flight_call_promptly(sup):
    hang = Hang()
    told = []
    thread, box = _in_thread(lambda: _call(sup, hang, on_abandon=lambda reason: told.append(reason)))
    assert hang.entered.wait(5)
    started = time.monotonic()
    stopped = sup.cancel_turn("turn-1")
    thread.join(5)
    hang.release.set()
    assert len(stopped) == 1
    assert time.monotonic() - started < 2
    assert isinstance(box["exc"], McpAbandoned) and box["exc"].reason == "stopped"
    assert sup.list("tab-1")[0]["state"] == "abandoned"
    assert told == ["stopped"]


def test_a_failing_cancel_notice_does_not_break_the_abandon(sup):
    def explode(reason):
        raise OSError("pipe closed")

    hang = Hang()
    with pytest.raises(McpAbandoned):
        _call(sup, hang, budgets=SHORT, on_abandon=explode)
    hang.release.set()


def test_a_server_with_too_many_abandoned_calls_gets_no_more(sup):
    hangs = [Hang(), Hang()]
    at_cap = []
    for hang in hangs:
        with pytest.raises(McpAbandoned) as err:
            _call(sup, hang, budgets=SHORT)
        at_cap.append(err.value.at_cap)
    assert at_cap == [False, True]

    sent = []
    with pytest.raises(McpDispatchRefused) as refused:
        _call(sup, lambda: sent.append("x"))
    assert sent == []
    assert refused.value.abandoned == 2
    assert _call(sup, lambda: "fine", server="other")[1] == "fine"

    for hang in hangs:
        hang.release.set()
    assert _wait(lambda: sup.abandoned_count("srv") == 0)
    assert _call(sup, lambda: "back")[1] == "back"


def test_a_call_that_ends_just_after_the_budget_is_not_counted_twice(sup):
    hang = Hang()
    with pytest.raises(McpAbandoned):
        _call(sup, hang, budgets=SHORT)
    assert sup.abandoned_count("srv") == 1
    hang.release.set()
    assert _wait(lambda: sup.abandoned_count("srv") == 0)
    assert sup.abandoned_count("srv") == 0


def test_mcp_calls_do_not_use_up_the_command_limit(sup):
    hangs = [Hang(), Hang(), Hang()]
    threads = [_in_thread(lambda h=h: _call(sup, h)) for h in hangs]
    for hang in hangs:
        assert hang.entered.wait(5)
    record, result = sup.run_inline(context_id="tab-1", turn_id="turn-1", path="shell", kind="shell",
                                    budgets=BUDGETS, runner=lambda handle: {"stdout": "ok", "exit_code": 0})
    assert record["state"] == "finished"
    for hang in hangs:
        hang.release.set()
    for thread, _ in threads:
        thread.join(5)


def test_the_status_line_only_reports_commands(sup):
    hang = Hang()
    thread, _ = _in_thread(lambda: _call(sup, hang))
    assert hang.entered.wait(5)
    assert sup.active_for_turn("turn-1") == []
    hang.release.set()
    thread.join(5)


def test_the_mcp_budget_has_a_default():
    assert timeouts.budgets_for("mcp").run_ms > 0
