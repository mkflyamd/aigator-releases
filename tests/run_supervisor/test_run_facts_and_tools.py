"""Facts on real runs, the model-facing result, and the probe tool, driven through the host Run route."""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import pytest
from fastapi.testclient import TestClient

import fakes
import timeouts
import data_sources
import routes.host_shell_routes as host_routes
from app import app
from runs import probe as probe_mod
from runs.supervisor import get_supervisor
from sandbox import host_requests
from sandbox.policy import Policy
from skills.shell_runner import tools as shell_tools

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
    get_supervisor().stop_all()
    host_requests._reset()


def _run(client, csrf, tmp_path, program, run_ms=None):
    req = host_requests.create("tab-1", fakes.command(tmp_path, program), str(tmp_path), fakes.SHELL, "", 600)
    if run_ms is None:
        r = client.post(f"/api/host-shell/{req.id}/run", json={"context_id": "tab-1"}, headers=csrf)
    else:
        with timeouts.override("host", run_ms=run_ms):
            r = client.post(f"/api/host-shell/{req.id}/run", json={"context_id": "tab-1"}, headers=csrf)
    assert r.status_code == 200
    end = time.monotonic() + 40
    while time.monotonic() < end:
        record = get_supervisor().get(req.id, "tab-1")
        if record["state"] not in _ACTIVE:
            return req.id, record
        time.sleep(0.05)
    raise AssertionError("the run never ended")


def test_a_viewer_left_running_after_its_launcher_exits_with_an_error_is_reported_as_facts(client, csrf, tmp_path):
    run_id, record = _run(client, csrf, tmp_path, "viewer_then_crash")
    child = fakes.child_pid(tmp_path, "viewer_then_crash")
    try:
        assert record["state"] == "finished" and record["exit"]["code"] == 3
        url = record["facts"]["urls_seen"][0]
        port = int(url.rsplit(":", 1)[1].strip("/"))
        assert port in record["facts"]["ports_opened"]
        assert child in [c["pid"] for c in record["facts"]["children_left"]]

        told = shell_tools._tool_host_command_result(run_id, "tab-1")
        assert told["state"] == "finished" and told["exit"]["code"] == 3
        assert told["facts"]["urls_seen"] == [url]
        assert "children_left" in told["message"]

        answer = shell_tools._tool_probe_local_url(run_id, url, "tab-1")
        assert answer["reached"] is True and answer["status"] == 200
        assert get_supervisor().get(run_id, "tab-1")["probe_log"][0]["status"] == 200
    finally:
        import psutil

        psutil.Process(child).kill()


def test_a_server_stopped_at_its_time_limit_keeps_its_port_facts_and_is_gone(client, csrf, tmp_path):
    run_id, record = _run(client, csrf, tmp_path, "serves_viewer", run_ms=2500)
    assert record["state"] == "timed_out"
    assert record["facts"]["urls_seen"], record
    url = record["facts"]["urls_seen"][0]
    port = int(url.rsplit(":", 1)[1].strip("/"))
    assert port in record["facts"]["ports_opened"]
    assert not record["facts"]["children_left"]
    answer = shell_tools._tool_probe_local_url(run_id, url, "tab-1")
    assert answer["reached"] is False


def test_the_probe_tool_refuses_an_address_the_run_never_printed(client, csrf, tmp_path):
    run_id, _ = _run(client, csrf, tmp_path, "prints_url")
    out = shell_tools._tool_probe_local_url(run_id, "http://127.0.0.1:9/", "tab-1")
    assert "not printed by this run" in out["error"]
    assert "refused" in get_supervisor().get(run_id, "tab-1")["probe_log"][0]


def test_the_probe_tool_is_limited_to_the_tab_that_owns_the_run(client, csrf, tmp_path):
    run_id, _ = _run(client, csrf, tmp_path, "prints_url")
    assert "error" in shell_tools._tool_probe_local_url(run_id, "http://127.0.0.1:4173/p/demo/", "tab-2")
    assert "error" in shell_tools._tool_probe_local_url("no-such-run", "http://127.0.0.1:4173/", "tab-1")
    assert "error" in shell_tools._tool_probe_local_url(run_id, "http://127.0.0.1:4173/p/demo/", "")


def test_a_run_can_only_be_probed_a_limited_number_of_times(client, csrf, tmp_path, monkeypatch):
    monkeypatch.setattr(probe_mod, "MAX_PROBES_PER_RUN", 2)
    run_id, _ = _run(client, csrf, tmp_path, "prints_url")
    url = "http://127.0.0.1:4173/p/demo/"
    for _ in range(2):
        assert "reached" in shell_tools._tool_probe_local_url(run_id, url, "tab-1")
    assert "probes" in shell_tools._tool_probe_local_url(run_id, url, "tab-1")["error"]
    assert len(get_supervisor().get(run_id, "tab-1")["probe_log"]) == 2


@pytest.mark.parametrize("name", ["run_shell", "run_python", "host_command_result", "probe_local_url"])
def test_output_from_every_command_tool_is_marked_untrusted(name):
    assert data_sources.is_untrusted(name)


def test_refused_probes_do_not_use_up_the_probe_allowance(client, csrf, tmp_path, monkeypatch):
    monkeypatch.setattr(probe_mod, "MAX_PROBES_PER_RUN", 2)
    run_id, _ = _run(client, csrf, tmp_path, "prints_url")
    for _ in range(4):
        assert "not printed by this run" in shell_tools._tool_probe_local_url(run_id, "http://127.0.0.1:9/", "tab-1")["error"]
    url = "http://127.0.0.1:4173/p/demo/"
    for _ in range(2):
        assert "reached" in shell_tools._tool_probe_local_url(run_id, url, "tab-1")
    assert "probes" in shell_tools._tool_probe_local_url(run_id, url, "tab-1")["error"]


def test_the_urls_a_run_prints_are_known_while_it_is_still_running(client, csrf, tmp_path):
    req = host_requests.create("tab-1", fakes.command(tmp_path, "serves_viewer"), str(tmp_path), fakes.SHELL, "", 600)
    assert client.post(f"/api/host-shell/{req.id}/run", json={"context_id": "tab-1"}, headers=csrf).status_code == 200
    seen = []

    def printed():
        record = get_supervisor().get(req.id, "tab-1")
        seen[:] = (record.get("facts") or {}).get("urls_seen") or []
        return bool(seen)

    assert fakes.wait_for(printed), f"the URL never showed up while the run was going: {get_supervisor().get(req.id, 'tab-1')}"
    assert get_supervisor().get(req.id, "tab-1")["state"] == "running"
    told = shell_tools._tool_host_command_result(req.id, "tab-1")
    assert told["state"] == "running" and told["facts"]["urls_seen"] == seen
    answer = shell_tools._tool_probe_local_url(req.id, seen[0], "tab-1")
    assert answer["reached"] is True and answer["status"] == 200


def test_a_stopped_turn_ends_its_probe_at_once(client, csrf, tmp_path, monkeypatch):
    import socket
    import threading

    from runs.turn import current_turn

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    monkeypatch.setattr(probe_mod, "backend_ports", lambda: set())  # this listener lives in the backend's own process
    monkeypatch.setitem(fakes._PROGRAMS, "prints_port", f"print('Viewer at http://127.0.0.1:{port}/p/demo/')")
    held = []
    threading.Thread(target=lambda: held.append(listener.accept()[0]), daemon=True).start()
    try:
        run_id, _ = _run(client, csrf, tmp_path, "prints_port")
        box = {}

        def call():
            token = current_turn.set("turn-1")
            try:
                box["out"] = shell_tools._tool_probe_local_url(run_id, f"http://127.0.0.1:{port}/p/demo/", "tab-1")
            finally:
                current_turn.reset(token)

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        assert fakes.wait_for(lambda: bool(held)), f"the probe never connected: {box}"
        started = time.monotonic()
        get_supervisor().cancel_turn("turn-1")
        worker.join(5)
        assert not worker.is_alive() and time.monotonic() - started < 3
        assert "stopped" in box["out"]["error"]
        assert get_supervisor().get(run_id, "tab-1")["probe_log"][0].get("stopped") is True
    finally:
        for conn in held:
            conn.close()
        listener.close()
