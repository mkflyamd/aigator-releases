"""Host-path conformance: each fake program is run through the real Run route and judged on its record."""
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import pytest
from fastapi.testclient import TestClient

import fakes
import timeouts
from app import app
from runs.records import RunStore
from runs.supervisor import RunError, RunSupervisor, get_supervisor, reset_supervisor
from sandbox import host_requests
from sandbox.policy import Policy
from skills.shell_runner import tools as shell_tools
import routes.host_shell_routes as host_routes

_ACTIVE = ("awaiting_approval", "preparing", "running")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def csrf():
    from security import get_csrf_token

    return {"X-CSRF-Token": get_csrf_token("testserver")}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    host_requests._reset()
    monkeypatch.setattr(shell_tools, "load_policy", lambda: Policy())
    monkeypatch.setattr(host_routes, "load_policy", lambda: Policy())
    yield
    host_requests._reset()


def _start(client, csrf, tmp_path, program, run_ms=None):
    req = host_requests.create("tab-1", fakes.command(tmp_path, program), str(tmp_path), fakes.SHELL, "", 600)
    if run_ms is None:
        r = client.post(f"/api/host-shell/{req.id}/run", json={"context_id": "tab-1"}, headers=csrf)
    else:
        with timeouts.override("host", run_ms=run_ms):
            r = client.post(f"/api/host-shell/{req.id}/run", json={"context_id": "tab-1"}, headers=csrf)
    assert r.status_code == 200
    return req


def _status(client, request_id):
    return client.get(f"/api/host-shell/{request_id}", params={"context_id": "tab-1"}).json()


def _finish(client, request_id, seconds=40):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        body = _status(client, request_id)
        if body["run"]["state"] not in _ACTIVE:
            return body
        time.sleep(0.05)
    raise AssertionError("the run never ended")


def test_a_program_that_exits_after_printing_a_url_is_a_finished_run_with_its_exit_code(client, csrf, tmp_path):
    body = _finish(client, _start(client, csrf, tmp_path, "crash_after_success").id)
    assert body["run"]["state"] == "finished"
    assert body["run"]["exit"]["code"] == 3
    assert "http://127.0.0.1:4173/p/demo/" in body["result"]["stdout"]


def test_a_flood_of_output_is_capped_in_the_result_and_the_record(client, csrf, tmp_path):
    body = _finish(client, _start(client, csrf, tmp_path, "flood").id)
    assert body["run"]["state"] == "finished"
    assert len(body["result"]["stdout"]) < host_requests.OUTPUT_LIMIT + 200
    assert body["result"]["stdout"].startswith("[first ")
    assert body["run"]["output_truncated"] is True
    assert len(body["run"]["output_tail"]) < 2300


def test_a_program_that_ignores_polite_stop_signals_is_still_killed_by_stop(client, csrf, tmp_path):
    req = _start(client, csrf, tmp_path, "ignores_stop")
    assert fakes.wait_for(lambda: _status(client, req.id)["run"]["state"] == "running")
    started = time.monotonic()
    client.post(f"/api/host-shell/{req.id}/cancel", json={"context_id": "tab-1"}, headers=csrf)
    body = _finish(client, req.id)
    assert body["run"]["state"] == "cancelled"
    assert "teardown_failed" not in body["run"]["facts"]
    assert time.monotonic() - started < 10


def test_a_command_that_outlives_its_budget_is_timed_out_and_its_whole_tree_is_killed(client, csrf, tmp_path):
    req = _start(client, csrf, tmp_path, "slow_tree", run_ms=2500)
    pid = fakes.child_pid(tmp_path, "slow_tree")
    body = _finish(client, req.id)
    assert body["run"]["state"] == "timed_out"
    assert fakes.wait_for(lambda: not fakes.alive(pid)), "the child survived the timeout"


def test_a_command_that_ends_while_its_child_holds_the_output_is_finished_and_the_child_is_reported(client, csrf, tmp_path):
    req = _start(client, csrf, tmp_path, "pipe_holder", run_ms=30_000)
    pid = fakes.child_pid(tmp_path, "pipe_holder")
    try:
        body = _finish(client, req.id)
        assert body["run"]["state"] == "finished"
        assert fakes.alive(pid)
        assert body["run"]["facts"]["children_left"]
    finally:
        import psutil

        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass


def test_a_command_that_finishes_leaves_its_detached_child_running(client, csrf, tmp_path):
    req = _start(client, csrf, tmp_path, "detached_child")
    pid = fakes.child_pid(tmp_path, "detached_child")
    try:
        body = _finish(client, req.id)
        assert body["run"]["state"] == "finished"
        assert "parent done" in body["result"]["stdout"]
        assert fakes.alive(pid), "a finished command's child is not killed behind the user's back"
        assert body["run"]["facts"]["children_left"], "the survivor is reported"
    finally:
        import psutil

        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass


def test_a_reload_mid_run_finds_the_same_running_record(client, csrf, tmp_path):
    req = _start(client, csrf, tmp_path, "slow")
    assert fakes.wait_for(lambda: _status(client, req.id)["run"]["state"] == "running")
    fresh_client = TestClient(app)
    seen = fresh_client.get(f"/api/host-shell/{req.id}", params={"context_id": "tab-1"}).json()
    assert seen["run"]["id"] == req.id and seen["run"]["state"] == "running"
    get_supervisor().stop_all()
    assert _finish(client, req.id)["run"]["state"] == "cancelled"


def test_the_fourth_concurrent_run_in_a_tab_is_refused_with_its_reason(client, csrf, tmp_path):
    reset_supervisor(RunSupervisor(RunStore(tmp_path / "cap.db"), max_running_per_context=3))
    started = [_start(client, csrf, tmp_path, "slow") for _ in range(3)]
    assert fakes.wait_for(lambda: all(_status(client, r.id)["run"]["state"] == "running" for r in started))
    fourth = _start(client, csrf, tmp_path, "quick")
    body = _status(client, fourth.id)
    assert body["run"]["state"] == "failed_to_start"
    assert body["run"]["reason"] == "concurrency_cap"
    assert "concurrency_cap" in body["result"]["error"]
    get_supervisor().stop_all()


def _cancel(client, csrf, request_id):
    return client.post(f"/api/host-shell/{request_id}/cancel", json={"context_id": "tab-1"}, headers=csrf)


@pytest.fixture
def own_supervisor(tmp_path):
    supervisor = RunSupervisor(RunStore(tmp_path / "own.db"))
    reset_supervisor(supervisor)
    yield supervisor
    supervisor.stop_all()


class _Gate:
    """Stands in for the command: counts how often it was run and holds it until released."""

    def __init__(self):
        self.runs = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, req, on_start=None, timeout=None):
        self.runs.append(req.id)
        self.entered.set()
        self.release.wait(10)
        return {"stdout": "ok", "stderr": "", "exit_code": 0, "ran_on": "host", "cwd": req.cwd}


def _run_url(request_id):
    return f"/api/host-shell/{request_id}/run"


def test_two_runs_at_once_start_one_command_and_both_get_the_record(csrf, tmp_path, monkeypatch, own_supervisor):
    gate = _Gate()
    monkeypatch.setattr(shell_tools, "run_host_request", gate)
    req = host_requests.create("tab-1", "echo", str(tmp_path), fakes.SHELL, "", 60)
    barrier, replies = threading.Barrier(2), []

    def click():
        other_tab = TestClient(app)
        barrier.wait(5)
        replies.append(other_tab.post(_run_url(req.id), json={"context_id": "tab-1"}, headers=csrf))

    threads = [threading.Thread(target=click) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    assert gate.entered.wait(5)
    assert [r.status_code for r in replies] == [200, 200]
    assert {r.json()["run"]["id"] for r in replies} == {req.id}
    gate.release.set()
    own_supervisor.wait(req.id, 5)
    assert gate.runs == [req.id]


def test_a_run_after_the_command_already_finished_gets_the_record_not_an_error(client, csrf, tmp_path):
    req = _start(client, csrf, tmp_path, "quick")
    _finish(client, req.id)
    again = client.post(_run_url(req.id), json={"context_id": "tab-1"}, headers=csrf)
    assert again.status_code == 200 and again.json()["run"]["state"] == "finished"


@pytest.mark.parametrize("failure", [RunError(409, "This command request was already denied."), RuntimeError("no threads")])
def test_a_run_that_could_not_start_does_not_leave_the_request_running(
        client, csrf, tmp_path, monkeypatch, own_supervisor, failure):
    def refuse(*args, **kwargs):
        raise failure

    monkeypatch.setattr(own_supervisor, "start", refuse)
    req = host_requests.create("tab-1", "echo", str(tmp_path), fakes.SHELL, "", 60)
    reply = client.post(_run_url(req.id), json={"context_id": "tab-1"}, headers=csrf)
    assert reply.status_code == (failure.status_code if isinstance(failure, RunError) else 500)
    status, stored = host_requests.lookup(req.id, "tab-1")
    assert status == "done" and "did not start" in stored.result["error"]
    told = shell_tools._tool_host_command_result(req.id, "tab-1")
    assert "did not start" in told["error"]


def test_stop_on_a_request_nobody_ran_denies_it_and_it_cannot_be_run_afterwards(client, csrf, tmp_path, own_supervisor):
    req = host_requests.create("tab-1", "echo", str(tmp_path), fakes.SHELL, "", 60)
    stopped = _cancel(client, csrf, req.id)
    assert stopped.status_code == 200 and stopped.json()["status"] == "denied"
    assert _status(client, req.id)["run"]["state"] == "denied"
    late = client.post(_run_url(req.id), json={"context_id": "tab-1"}, headers=csrf)
    assert late.status_code == 409


def test_stop_twice_is_one_stop_and_both_calls_get_the_record(client, csrf, tmp_path):
    req = _start(client, csrf, tmp_path, "slow")
    assert fakes.wait_for(lambda: _status(client, req.id)["run"]["state"] == "running")
    first, second = _cancel(client, csrf, req.id), _cancel(client, csrf, req.id)
    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json()["status"] == second.json()["status"] == "cancelled"
    assert _finish(client, req.id)["run"]["state"] == "cancelled"


def test_two_stops_at_once_both_succeed(client, csrf, tmp_path):
    req = _start(client, csrf, tmp_path, "slow")
    assert fakes.wait_for(lambda: _status(client, req.id)["run"]["state"] == "running")
    barrier, replies = threading.Barrier(2), []

    def stop():
        other_tab = TestClient(app)
        barrier.wait(5)
        replies.append(other_tab.post(f"/api/host-shell/{req.id}/cancel", json={"context_id": "tab-1"}, headers=csrf))

    threads = [threading.Thread(target=stop) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert [r.status_code for r in replies] == [200, 200]
    assert _finish(client, req.id)["run"]["state"] == "cancelled"


def test_a_tab_can_list_its_own_runs_to_find_the_one_a_card_belongs_to(client, csrf, tmp_path, own_supervisor):
    mine = _start(client, csrf, tmp_path, "slow")
    elsewhere = host_requests.create("tab-2", "echo", str(tmp_path), fakes.SHELL, "", 60)
    assert fakes.wait_for(lambda: _status(client, mine.id)["run"]["state"] == "running")
    listed = client.get("/api/runs", params={"context_id": "tab-1"}).json()["runs"]
    assert [r["id"] for r in listed] == [mine.id] and listed[0]["state"] == "running"
    assert elsewhere.id not in [r["id"] for r in listed]
    assert client.get("/api/runs").status_code == 422
    own_supervisor.stop_all()


def test_the_model_reading_an_unanswered_request_sees_it_expired_and_the_record_follows(tmp_path, own_supervisor):
    req = host_requests.create("tab-1", "echo", str(tmp_path), fakes.SHELL, "", 60, now=time.time() - 700)
    told = shell_tools._tool_host_command_result(req.id, "tab-1")
    assert told["state"] == "expired" and "within 10 minutes" in told["message"]
    assert own_supervisor.get(req.id, "tab-1")["state"] == "expired"


def test_a_command_whose_record_has_ended_reads_as_done_before_its_result_is_stored(tmp_path, own_supervisor):
    req = host_requests.create("tab-1", "echo", str(tmp_path), fakes.SHELL, "", 60)
    host_requests.claim(req.id, "tab-1")
    entered, release = threading.Event(), threading.Event()

    def on_done(result):
        entered.set()
        release.wait(10)
        host_requests.finish(req.id, result)

    own_supervisor.start(req.id, "tab-1", lambda handle: {"stdout": "out", "stderr": "", "exit_code": 0},
                         timeouts.budgets_for("host"), on_done)
    assert entered.wait(5)
    assert own_supervisor.get(req.id, "tab-1")["state"] == "finished"
    status, shown = host_requests.lookup_settled(req.id, "tab-1")
    assert status == "done" and shown.result["stdout"] == "out" and shown.result["exit_code"] == 0
    assert shell_tools._tool_host_command_result(req.id, "tab-1")["state"] == "finished"
    release.set()


def test_a_backend_that_died_mid_run_reports_interrupted_after_restart(client, csrf, tmp_path):
    store_path = tmp_path / "restart.db"
    reset_supervisor(RunSupervisor(RunStore(store_path)))
    req = _start(client, csrf, tmp_path, "slow")
    assert fakes.wait_for(lambda: _status(client, req.id)["run"]["state"] == "running")
    # A new backend process over the same store: it never saw the run end.
    restarted = RunSupervisor(RunStore(store_path))
    assert req.id in restarted.reconcile()
    assert restarted.get(req.id, "tab-1")["state"] == "interrupted"
    get_supervisor().stop_all()
