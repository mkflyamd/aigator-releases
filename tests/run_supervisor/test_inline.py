import asyncio
import dataclasses
import pathlib
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import pytest

import fakes
import sandbox
import timeouts
from runs import inline
from runs.records import RunStore
from runs.supervisor import RunSupervisor, get_supervisor, reset_supervisor
from runs.turn import current_turn

BUDGETS = timeouts.Budgets(setup_ms=0, run_ms=5000, teardown_ms=300)


@pytest.fixture
def sup(tmp_path):
    supervisor = RunSupervisor(RunStore(tmp_path / "runs.db"), max_running_per_context=2)
    reset_supervisor(supervisor)
    return supervisor


def _inline(sup, runner, turn="turn-1", ctx="tab-1", budgets=BUDGETS):
    return sup.run_inline(context_id=ctx, turn_id=turn, path="shell", kind="shell", budgets=budgets, runner=runner)


def _in_thread(fn):
    box = {}
    thread = threading.Thread(target=lambda: box.update(out=fn()), daemon=True)
    thread.start()
    return thread, box


class Sleeper:
    """A runner that has a started process until Stop arrives."""

    def __init__(self, hang_after_stop=False):
        self.entered = threading.Event()
        self.hang_after_stop = hang_after_stop
        self.release = threading.Event()

    def __call__(self, handle):
        handle.started(0)
        self.entered.set()
        if self.hang_after_stop:
            self.release.wait(10)
        else:
            handle._cancelled.wait(10)
        return {"stdout": "", "stderr": "", "exit_code": -1}


def test_an_inline_run_goes_preparing_then_running_when_its_process_starts_then_finishes(sup):
    seen = []

    def runner(handle):
        seen.append(sup.get(handle.run_id, "tab-1")["state"])
        handle.started(0)
        seen.append(sup.get(handle.run_id, "tab-1")["state"])
        return {"stdout": "hi", "stderr": "", "exit_code": 0}

    record, result = _inline(sup, runner)
    assert seen == ["preparing", "running"]
    assert record["state"] == "finished" and record["scope"] == "turn" and record["turn_id"] == "turn-1"
    assert result["stdout"] == "hi"


def test_an_inline_run_over_the_concurrency_cap_is_refused_without_running(sup):
    gates = [Sleeper(), Sleeper()]
    threads = [_in_thread(lambda g=g: _inline(sup, g, turn=f"t{i}")) for i, g in enumerate(gates)]
    assert all(g.entered.wait(5) for g in gates)
    ran = []
    record, result = _inline(sup, lambda handle: ran.append(1) or {}, turn="t3")
    assert record["state"] == "failed_to_start" and record["reason"] == "concurrency_cap"
    assert not ran and "Too many" in result["error"]
    for turn in ("t0", "t1"):
        sup.cancel_turn(turn)
    for thread, _ in threads:
        thread.join(5)


def test_the_turns_stop_cancels_its_inline_run_and_waits_for_it_to_wind_down(sup):
    runner = Sleeper()
    thread, box = _in_thread(lambda: _inline(sup, runner))
    assert runner.entered.wait(5)
    started = time.monotonic()
    assert len(sup.cancel_turn("turn-1")) == 1
    # taskkill alone takes 2-3 s on managed Windows machines; a runner that never heard Stop waits 10 s.
    assert time.monotonic() - started < 8
    thread.join(5)
    record, _ = box["out"]
    assert record["state"] == "cancelled"
    assert "teardown_failed" not in record["facts"]


def test_stop_during_preparing_cancels_a_run_whose_process_never_started(sup):
    entered, release = threading.Event(), threading.Event()

    def queued(handle):
        entered.set()
        handle._cancelled.wait(10)
        raise sandbox.SandboxCancelled()

    thread, box = _in_thread(lambda: _inline(sup, queued))
    assert entered.wait(5)
    assert sup.cancel_turn("turn-1")
    thread.join(5)
    record, _ = box["out"]
    assert record["state"] == "cancelled" and record["facts"].get("teardown_failed") is None


def test_a_queued_inline_run_that_cannot_hear_stop_is_not_reported_as_a_failed_teardown(sup):
    entered, release = threading.Event(), threading.Event()

    def blocked_on_a_lock(handle):
        entered.set()
        release.wait(10)
        return {}

    thread, _ = _in_thread(lambda: _inline(sup, blocked_on_a_lock))
    assert entered.wait(5)
    sup.cancel_turn("turn-1")
    record = sup.list("tab-1")[0]
    assert record["state"] == "cancelled" and "teardown_failed" not in record["facts"]
    release.set()
    thread.join(5)


def test_a_started_process_that_outlives_the_teardown_budget_is_reported(sup):
    runner = Sleeper(hang_after_stop=True)
    thread, _ = _in_thread(lambda: _inline(sup, runner))
    assert runner.entered.wait(5)
    sup.cancel_turn("turn-1")
    assert sup.list("tab-1")[0]["facts"]["teardown_failed"] is True
    runner.release.set()
    thread.join(5)


def test_stopping_twice_is_harmless(sup):
    runner = Sleeper()
    thread, box = _in_thread(lambda: _inline(sup, runner))
    assert runner.entered.wait(5)
    sup.cancel_turn("turn-1")
    sup.cancel_turn("turn-1")
    thread.join(5)
    assert box["out"][0]["state"] == "cancelled"


def test_another_turns_stop_leaves_the_run_alone(sup):
    runner = Sleeper()
    thread, box = _in_thread(lambda: _inline(sup, runner))
    assert runner.entered.wait(5)
    assert sup.cancel_turn("someone-else") == []
    sup.cancel_turn("turn-1")
    thread.join(5)


def test_the_turn_id_reaches_a_tool_running_in_a_worker_thread():
    async def call():
        token = current_turn.set("turn-9")
        try:
            return await asyncio.to_thread(current_turn.get)
        finally:
            current_turn.reset(token)

    assert asyncio.run(call()) == "turn-9"


def test_inline_helper_stamps_the_run_with_the_current_turn(sup):
    token = current_turn.set("turn-5")
    try:
        record, _ = inline.run_inline("shell", "shell", "tab-1", 5, lambda handle: {"exit_code": 0})
    finally:
        current_turn.reset(token)
    assert record["turn_id"] == "turn-5"


def test_a_real_process_is_killed_by_the_turns_stop(sup, tmp_path):
    from skills.shell_runner import tools as shell_tools

    fakes._PROGRAMS["napper"] = (
        "import time\nprint('Viewer at http://127.0.0.1:4173/', flush=True)\n"
        f"open({str(tmp_path / 'printed')!r}, 'w').close()\ntime.sleep(60)")
    command = fakes.command(tmp_path, "napper")

    def tool_call():
        current_turn.set("turn-7")
        return inline.run_inline(
            "shell", "shell", "tab-1", 60,
            lambda handle: shell_tools._run_unsandboxed(command, fakes.SHELL, str(tmp_path), 60, False,
                                                        as_typed=True, on_start=handle.attach))

    thread, box = _in_thread(tool_call)
    assert fakes.wait_for(lambda: (tmp_path / "printed").exists())
    started = time.monotonic()
    sup.cancel_turn("turn-7")
    thread.join(15)
    record, result = box["out"]
    assert time.monotonic() - started < 15
    assert record["state"] == "cancelled"
    assert "4173" in result["stdout"]


def test_the_fields_added_to_a_tool_result_do_not_replace_its_own_keys(sup):
    record, result = _inline(sup, lambda handle: {"stdout": "x", "exit_code": 0, "shell_used": "bash"})
    merged = inline.with_run_fields(result, record)
    assert merged["shell_used"] == "bash" and merged["run_id"] == record["id"] and merged["state"] == "finished"


def _request(timeout=5):
    return sandbox.SandboxRequest(argv=["x"], cwd=pathlib.Path("."), env={}, runtime_paths=[], read_paths=[],
                                  write_paths=[], network=False, timeout=timeout)


def test_a_supervised_launch_hands_the_launcher_the_stop_event_the_start_hook_and_the_budgets(sup, monkeypatch):
    seen = {}

    def fake_launch(req):
        seen["req"] = req
        req.on_start(0)
        return sandbox.SandboxResult(returncode=0, stdout="out", stderr="", timed_out=False)

    monkeypatch.setattr(sandbox, "launch_sandboxed", fake_launch)
    with timeouts.override("sandbox", setup_ms=1500, teardown_ms=2500):
        res, record = inline.launch_supervised(_request(), context_id="tab-1", kind="shell")
    req = seen["req"]
    assert req.cancel is not None and callable(req.on_start)
    assert (req.setup_seconds, req.teardown_seconds, req.timeout) == (1.5, 2.5, 5)
    assert res.stdout == "out" and record["state"] == "finished" and record["path"] == "sandbox"


def test_a_launcher_refusal_reaches_the_caller_unchanged_and_the_run_is_recorded(sup, monkeypatch):
    def refuse(req):
        raise sandbox.SandboxUnavailable("no sandbox")

    monkeypatch.setattr(sandbox, "launch_sandboxed", refuse)
    with pytest.raises(sandbox.SandboxUnavailable, match="no sandbox"):
        inline.launch_supervised(_request(), context_id="tab-1", kind="shell")
    assert sup.list("tab-1")[0]["state"] == "failed_to_start"


def test_a_refusal_that_left_grants_behind_is_still_a_teardown_fact_on_the_record(sup, monkeypatch):
    def refuse(req):
        exc = sandbox.SandboxUnavailable("timed out granting")
        exc.teardown_failed = True
        raise exc

    monkeypatch.setattr(sandbox, "launch_sandboxed", refuse)
    with pytest.raises(sandbox.SandboxUnavailable):
        inline.launch_supervised(_request(), context_id="tab-1", kind="shell")
    record = sup.list("tab-1")[0]
    assert record["state"] == "failed_to_start" and record["facts"]["teardown_failed"] is True


def test_a_supervised_launch_over_the_cap_is_refused_before_the_launcher_runs(sup, monkeypatch):
    sleepers = [Sleeper(), Sleeper()]
    threads = [_in_thread(lambda s=s, i=i: _inline(sup, s, turn=f"t{i}")) for i, s in enumerate(sleepers)]
    assert all(s.entered.wait(5) for s in sleepers)
    monkeypatch.setattr(sandbox, "launch_sandboxed", lambda req: pytest.fail("must not launch"))
    with pytest.raises(inline.RunRefused, match="Too many"):
        inline.launch_supervised(_request(), context_id="tab-1", kind="shell")
    sup.stop_all()
    for thread, _ in threads:
        thread.join(5)


def test_a_teardown_that_leaves_grants_behind_is_a_fact_on_the_record(sup, monkeypatch):
    monkeypatch.setattr(sandbox, "launch_sandboxed", lambda req: sandbox.SandboxResult(
        returncode=0, stdout="", stderr="", timed_out=False, teardown_failed=True))
    _, record = inline.launch_supervised(_request(), context_id="tab-1", kind="shell")
    assert record["facts"]["teardown_failed"] is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group launcher")
def test_the_posix_launcher_kills_its_group_when_stop_is_set(tmp_path):
    stop, pids = threading.Event(), []
    threading.Timer(0.5, stop.set).start()
    started = time.monotonic()
    res = sandbox.run_process_group(["sleep", "60"], tmp_path, {"PATH": "/usr/bin:/bin"}, 60, stop, pids.append)
    assert res.cancelled and not res.timed_out
    assert time.monotonic() - started < 10 and len(pids) == 1


def test_the_windows_launcher_refuses_a_launch_whose_stop_already_arrived():
    from sandbox import launcher_windows

    stop = threading.Event()
    stop.set()
    with pytest.raises(sandbox.SandboxCancelled):
        launcher_windows._check_not_cancelled(dataclasses.replace(_request(), cancel=stop))
    launcher_windows._check_not_cancelled(_request())


def test_the_runs_route_lists_a_tabs_runs_newest_first_and_only_that_tab(sup):
    from fastapi.testclient import TestClient
    from app import app

    _inline(sup, lambda h: {"exit_code": 0}, turn="a", ctx="tab-1")
    _inline(sup, lambda h: {"exit_code": 0}, turn="b", ctx="tab-1")
    _inline(sup, lambda h: {"exit_code": 0}, turn="c", ctx="tab-2")
    body = TestClient(app).get("/api/runs", params={"context_id": "tab-1"}).json()
    assert [r["turn_id"] for r in body["runs"]] == ["b", "a"]


def test_a_turns_active_runs_are_listed_until_they_finish(sup):
    runner = Sleeper()
    thread, _ = _in_thread(lambda: _inline(sup, runner))
    assert runner.entered.wait(5)
    assert [r["state"] for r in sup.active_for_turn("turn-1")] == ["running"]
    assert sup.active_for_turn("other") == []
    sup.cancel_turn("turn-1")
    thread.join(5)
    assert sup.active_for_turn("turn-1") == []
