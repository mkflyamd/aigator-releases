import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))

import pytest

import timeouts
from runs.records import RunRecord, RunStore
from runs.supervisor import RunError, RunSupervisor

BUDGETS = timeouts.Budgets(setup_ms=0, run_ms=2000, teardown_ms=300)


@pytest.fixture
def sup(tmp_path):
    return RunSupervisor(RunStore(tmp_path / "runs.db"), max_running_per_context=2)


def _open(sup, run_id="r1", ctx="tab-1", scope="tab", turn_id="", expires_at=None):
    return sup.open_approval(run_id=run_id, context_id=ctx, path="host", kind="command", scope=scope,
                             expires_at=time.time() + 600 if expires_at is None else expires_at, turn_id=turn_id)


def _ok(result=None):
    return lambda handle: result if result is not None else {"stdout": "hi", "stderr": "", "exit_code": 0}


class Gate:
    """A runner that blocks until released, so a test can look at the record while it runs."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, handle):
        self.entered.set()
        self.release.wait(10)
        return {"stdout": "", "stderr": "", "exit_code": 0}


def test_a_record_starts_awaiting_approval(sup):
    rec = _open(sup)
    assert rec["state"] == "awaiting_approval"
    assert rec["scope"] == "tab"


def test_a_finished_run_records_exit_and_output(sup):
    _open(sup)
    sup.start("r1", "tab-1", _ok(), BUDGETS)
    sup.wait("r1", 5)
    rec = sup.get("r1", "tab-1")
    assert rec["state"] == "finished"
    assert rec["exit"]["code"] == 0
    assert rec["output_tail"] == "hi"
    assert rec["run_started_at"] and rec["finished_at"]


def test_an_abnormal_exit_is_still_finished_with_the_code_as_a_fact(sup):
    _open(sup)
    sup.start("r1", "tab-1", _ok({"stdout": "", "stderr": "", "exit_code": -1073740791}), BUDGETS)
    sup.wait("r1", 5)
    rec = sup.get("r1", "tab-1")
    assert rec["state"] == "finished"
    assert rec["exit"] == {"code": -1073740791, "hex": "0xC0000409", "is_crash_value": True}


def test_a_timed_out_runner_ends_timed_out(sup):
    _open(sup)
    sup.start("r1", "tab-1", _ok({"stdout": "", "stderr": "", "exit_code": -1, "timed_out": True}), BUDGETS)
    sup.wait("r1", 5)
    assert sup.get("r1", "tab-1")["state"] == "timed_out"


def test_a_runner_that_raises_ends_failed_to_start(sup):
    def boom(handle):
        raise OSError("nope")

    _open(sup)
    sup.start("r1", "tab-1", boom, BUDGETS)
    sup.wait("r1", 5)
    rec = sup.get("r1", "tab-1")
    assert rec["state"] == "failed_to_start"
    assert "OSError" in rec["error"]


def test_a_run_that_never_started_a_process_and_reports_an_error_failed_to_start(sup):
    _open(sup)
    sup.start("r1", "tab-1", _ok({"stdout": "", "stderr": "", "exit_code": -1, "error": "Bash is not available."}), BUDGETS)
    sup.wait("r1", 5)
    assert sup.get("r1", "tab-1")["state"] == "failed_to_start"


def test_run_on_a_running_record_returns_it_and_does_not_start_twice(sup):
    gate, started = Gate(), []
    _open(sup)
    sup.start("r1", "tab-1", lambda h: started.append(1) or gate(h), BUDGETS)
    assert gate.entered.wait(5)
    again = sup.start("r1", "tab-1", lambda h: started.append(2) or {}, BUDGETS)
    assert again["state"] == "running"
    gate.release.set()
    sup.wait("r1", 5)
    assert started == [1]


def test_start_on_a_finished_record_is_a_conflict(sup):
    _open(sup)
    sup.start("r1", "tab-1", _ok(), BUDGETS)
    sup.wait("r1", 5)
    with pytest.raises(RunError) as exc:
        sup.start("r1", "tab-1", _ok(), BUDGETS)
    assert exc.value.status_code == 409


def test_a_record_belongs_to_its_tab(sup):
    _open(sup)
    assert sup.get("r1", "tab-2") is None
    with pytest.raises(RunError) as exc:
        sup.start("r1", "tab-2", _ok(), BUDGETS)
    assert exc.value.status_code == 409


def test_an_unknown_record_is_404(sup):
    with pytest.raises(RunError) as exc:
        sup.start("nope", "tab-1", _ok(), BUDGETS)
    assert exc.value.status_code == 404


def test_the_per_tab_cap_rejects_as_failed_to_start_with_the_reason(sup):
    gates = [Gate(), Gate()]
    for i, gate in enumerate(gates):
        _open(sup, run_id=f"r{i}")
        sup.start(f"r{i}", "tab-1", gate, BUDGETS)
        assert gate.entered.wait(5)
    _open(sup, run_id="r2")
    rec = sup.start("r2", "tab-1", _ok(), BUDGETS)
    assert rec["state"] == "failed_to_start"
    assert rec["reason"] == "concurrency_cap"
    _open(sup, run_id="other", ctx="tab-2")
    assert sup.start("other", "tab-2", _ok(), BUDGETS)["state"] != "failed_to_start"
    for gate in gates:
        gate.release.set()


def test_cancel_sets_cancelled_and_runner_sees_it(sup):
    seen = threading.Event()

    def runner(handle):
        seen.set()
        while not handle.cancelled:
            time.sleep(0.01)
        return {"stdout": "", "stderr": "", "exit_code": -1}

    _open(sup)
    sup.start("r1", "tab-1", runner, BUDGETS)
    assert seen.wait(5)
    rec = sup.cancel("r1", "tab-1")
    assert rec["state"] == "cancelled"
    sup.wait("r1", 5)
    assert sup.get("r1", "tab-1")["state"] == "cancelled"
    assert "teardown_failed" not in sup.get("r1", "tab-1")["facts"]


def test_a_double_stop_is_harmless(sup):
    gate = Gate()
    _open(sup)
    sup.start("r1", "tab-1", gate, BUDGETS)
    assert gate.entered.wait(5)
    first = sup.cancel("r1", "tab-1")
    second = sup.cancel("r1", "tab-1")
    gate.release.set()
    assert first["state"] == second["state"] == "cancelled"


def test_a_runner_that_ignores_stop_is_marked_teardown_failed(sup):
    gate = Gate()
    _open(sup)
    sup.start("r1", "tab-1", gate, BUDGETS)
    assert gate.entered.wait(5)
    started = time.monotonic()
    rec = sup.cancel("r1", "tab-1")
    assert time.monotonic() - started < 2
    assert rec["state"] == "cancelled"
    assert rec["facts"]["teardown_failed"] is True
    gate.release.set()
    sup.wait("r1", 5)
    assert sup.get("r1", "tab-1")["state"] == "cancelled"


def test_cancel_while_awaiting_approval_is_a_denial(sup):
    _open(sup)
    assert sup.cancel("r1", "tab-1")["state"] == "denied"


def test_cancel_turn_stops_only_that_turns_turn_scoped_runs(tmp_path):
    sup = RunSupervisor(RunStore(tmp_path / "runs.db"), max_running_per_context=5)
    gates = {name: Gate() for name in ("mine", "other_turn", "card")}
    _open(sup, run_id="mine", scope="turn", turn_id="turn-1")
    _open(sup, run_id="other_turn", scope="turn", turn_id="turn-2")
    _open(sup, run_id="card", scope="tab", turn_id="turn-1")
    for name, gate in gates.items():
        sup.start(name, "tab-1", gate, timeouts.Budgets(0, 2000, 100))
        assert gate.entered.wait(5)
    assert sup.cancel_turn("turn-1") == ["mine"]
    assert sup.get("mine", "tab-1")["state"] == "cancelled"
    assert sup.get("other_turn", "tab-1")["state"] == "running"
    assert sup.get("card", "tab-1")["state"] == "running"
    for gate in gates.values():
        gate.release.set()


def test_deny_and_policy_block_are_different_states(sup):
    _open(sup, run_id="a")
    _open(sup, run_id="b")
    assert sup.deny("a", "tab-1")["state"] == "denied"
    rec = sup.policy_block("b", "tab-1", "An administrator turned this off.")
    assert rec["state"] == "policy_blocked"
    assert rec["reason"] == "An administrator turned this off."


def test_an_awaiting_record_expires_once_at_its_deadline(sup):
    _open(sup, expires_at=100.0)
    assert sup.mark_expired("r1")["state"] == "expired"
    assert sup.mark_expired("r1")["state"] == "expired"


def test_a_running_record_is_not_expired(sup):
    gate = Gate()
    _open(sup)
    sup.start("r1", "tab-1", gate, BUDGETS)
    assert gate.entered.wait(5)
    assert sup.mark_expired("r1")["state"] == "running"
    gate.release.set()


def test_start_after_expiry_is_410(sup):
    _open(sup)
    sup.mark_expired("r1")
    with pytest.raises(RunError) as exc:
        sup.start("r1", "tab-1", _ok(), BUDGETS)
    assert exc.value.status_code == 410


def test_the_run_budget_is_handed_to_the_runner(sup):
    got = {}

    def runner(handle):
        got["timeout_s"] = handle.timeout_s
        return {"stdout": "", "stderr": "", "exit_code": 0}

    _open(sup)
    sup.start("r1", "tab-1", runner, timeouts.Budgets(0, 1500, 100))
    sup.wait("r1", 5)
    assert got["timeout_s"] == 1.5


def test_list_returns_the_tabs_runs(sup):
    _open(sup, run_id="a")
    _open(sup, run_id="b", ctx="tab-2")
    assert [r["id"] for r in sup.list("tab-1")] == ["a"]


def test_a_reload_after_restart_reads_the_record_from_the_store(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    first = RunSupervisor(store)
    _open(first)
    first.start("r1", "tab-1", _ok(), BUDGETS)
    first.wait("r1", 5)
    second = RunSupervisor(store)
    assert second.get("r1", "tab-1")["state"] == "finished"
    assert [r["id"] for r in second.list("tab-1")] == ["r1"]


def test_reconcile_interrupts_what_was_active_when_the_backend_died(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    first = RunSupervisor(store)
    _open(first, run_id="waiting")
    gate = Gate()
    _open(first, run_id="busy")
    first.start("busy", "tab-1", gate, BUDGETS)
    assert gate.entered.wait(5)
    second = RunSupervisor(store)
    assert sorted(second.reconcile()) == ["busy", "waiting"]
    assert second.get("busy", "tab-1")["state"] == "interrupted"
    assert second.get("waiting", "tab-1")["state"] == "interrupted"
    gate.release.set()


def test_a_stale_pid_from_an_interrupted_run_is_swept_only_if_it_is_the_same_process(tmp_path):
    import subprocess

    import psutil

    store = RunStore(tmp_path / "runs.db")
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    mine, reused = subprocess.Popen(sleeper), subprocess.Popen(sleeper)
    try:
        created = psutil.Process(mine.pid).create_time()
        store.upsert(RunRecord(id="mine", context_id="t", path="host", kind="command", scope="tab", state="running",
                               owner_pid=mine.pid, owner_create_time=created).to_dict())
        store.upsert(RunRecord(id="reused", context_id="t", path="host", kind="command", scope="tab", state="running",
                               owner_pid=reused.pid, owner_create_time=created - 1000).to_dict())
        RunSupervisor(store).reconcile()
        assert mine.wait(15) is not None
        assert reused.poll() is None
    finally:
        for proc in (mine, reused):
            if proc.poll() is None:
                proc.kill()


def test_stop_all_cancels_every_running_run(sup):
    gate = Gate()
    _open(sup)
    sup.start("r1", "tab-1", gate, BUDGETS)
    assert gate.entered.wait(5)
    sup.stop_all()
    assert sup.get("r1", "tab-1")["state"] == "cancelled"
    gate.release.set()


def test_budgets_are_injectable_in_milliseconds():
    with timeouts.override("host", run_ms=250):
        assert timeouts.budgets_for("host", run_ms=60_000).run_ms == 250
    assert timeouts.budgets_for("host", run_ms=60_000).run_ms == 60_000


def test_every_path_has_a_default_budget():
    budgets = timeouts.budgets_for("host")
    assert budgets.run_ms > 0 and budgets.teardown_ms > 0


def test_on_done_fires_after_the_record_is_terminal(sup):
    _open(sup)
    seen = []
    sup.start("r1", "tab-1", _ok(), BUDGETS, lambda result: seen.append(sup.get("r1", "tab-1")["state"]))
    sup.wait("r1", 5)
    assert _wait_for(lambda: seen)
    assert seen == ["finished"]


def test_wait_returns_only_after_on_done_has_run(sup):
    _open(sup)
    done = threading.Event()

    def slow_done(result):
        time.sleep(0.2)
        done.set()

    sup.start("r1", "tab-1", _ok(), BUDGETS, slow_done)
    sup.wait("r1", 5)
    assert done.is_set()


def test_reconcile_leaves_the_runs_this_process_opened_alone(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    store.upsert(RunRecord(id="old", context_id="tab-1", path="host", kind="command", scope="tab",
                           state="running").to_dict())
    supervisor = RunSupervisor(store)
    _open(supervisor, run_id="mine")
    assert supervisor.reconcile() == ["old"]
    assert supervisor.get("mine", "tab-1")["state"] == "awaiting_approval"
    assert supervisor.get("old", "tab-1")["state"] == "interrupted"


def test_a_worker_that_cannot_start_leaves_a_failed_record_not_a_stuck_one(sup, monkeypatch):
    _open(sup)

    def refuse(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", refuse)
    with pytest.raises(RunError):
        sup.start("r1", "tab-1", _ok(), BUDGETS)
    monkeypatch.undo()
    assert sup.get("r1", "tab-1")["state"] == "failed_to_start"


def _wait_for(predicate, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False
