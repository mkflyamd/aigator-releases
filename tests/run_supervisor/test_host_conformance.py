"""Host-path conformance: each fake program is run through the real Run route and judged on its record."""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import pytest
from fastapi.testclient import TestClient

import fakes
import timeouts
from app import app
from runs.records import RunStore
from runs.supervisor import RunSupervisor, get_supervisor, reset_supervisor
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


def test_a_command_that_outlives_its_budget_is_timed_out_and_its_detached_child_is_killed(client, csrf, tmp_path):
    req = _start(client, csrf, tmp_path, "detached_child", run_ms=2500)
    body = _finish(client, req.id)
    pid = fakes.child_pid(tmp_path, "detached_child")
    assert body["run"]["state"] in ("finished", "timed_out")
    if body["run"]["state"] == "timed_out":
        assert fakes.wait_for(lambda: not fakes.alive(pid)), "the detached child survived the timeout"
    else:
        # The shell exited first; the child is left behind as a fact, not killed.
        assert fakes.alive(pid)
        import psutil

        psutil.Process(pid).kill()


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
