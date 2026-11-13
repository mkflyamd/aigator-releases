import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi.testclient import TestClient

from app import app
from skills.shell_runner import tools as sh


class _Proc:
    def __init__(self, url=None):
        self.url = url
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def csrf():
    from security import get_csrf_token

    return {"X-CSRF-Token": get_csrf_token("testserver")}


@pytest.fixture
def registered():
    forwarded = _Proc("http://127.0.0.1:3030")
    plain = _Proc()
    sh._BG_REGISTRY[5001] = {"popen": forwarded, "command": "npm run dev", "sandboxed": True, "started_at": 1}
    sh._BG_REGISTRY[5002] = {"popen": plain, "command": "sleep 5", "started_at": 1}
    yield forwarded
    sh._BG_REGISTRY.pop(5001, None)
    sh._BG_REGISTRY.pop(5002, None)


def test_list_carries_the_forwarded_url(client, registered):
    procs = {p["pid"]: p for p in client.get("/api/shell/background-processes").json()["processes"]}
    assert procs[5001]["url"] == "http://127.0.0.1:3030"
    assert procs[5002]["url"] is None


def test_stop_needs_the_csrf_token(client, registered):
    assert client.post("/api/shell/background-processes/5001/stop").status_code == 403
    assert registered.terminated is False


def test_stop_unknown_pid_is_404(client, csrf):
    assert client.post("/api/shell/background-processes/999999/stop", headers=csrf).status_code == 404


def test_stop_terminates_a_sandboxed_process(client, csrf, registered):
    r = client.post("/api/shell/background-processes/5001/stop", headers=csrf)
    assert r.status_code == 200 and r.json()["stopped"] is True
    assert registered.terminated is True
