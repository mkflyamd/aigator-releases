import os

import pytest
from fastapi.testclient import TestClient

from app import app
from routes import utils
from security import get_csrf_token


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(utils.subprocess, "run", lambda cmd, **kw: seen.append(cmd))
    monkeypatch.setattr(utils, "no_window_kwargs", lambda: {})
    return seen


@pytest.fixture
def client():
    c = TestClient(app)
    c.headers["X-CSRF-Token"] = get_csrf_token("testserver")
    return c


@pytest.mark.parametrize(
    "platform,expected",
    [
        ("win32", lambda p: ["explorer", "/select," + os.path.normpath(p)]),
        ("darwin", lambda p: ["open", "-R", p]),
        ("linux", lambda p: ["xdg-open", os.path.dirname(p)]),
    ],
)
def test_reveal_selects_the_file(calls, monkeypatch, tmp_path, platform, expected):
    f = tmp_path / "AI_Gator_Demo.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(utils.sys, "platform", platform)
    utils._do_open_file(str(f), False, True)
    assert calls == [expected(str(f))]


def test_file_without_reveal_still_opens_in_default_app(calls, monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(utils.os, "startfile", lambda p: started.append(p), raising=False)
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    utils._do_open_file(str(f))
    assert started == [str(f)]
    assert calls == []


def test_directory_ignores_reveal(calls, monkeypatch, tmp_path):
    monkeypatch.setattr(utils.sys, "platform", "linux")
    utils._do_open_file(str(tmp_path), True, True)
    assert calls == [["xdg-open", str(tmp_path)]]


def test_route_forwards_reveal(client, monkeypatch, tmp_path):
    f = tmp_path / "AI_Gator_Demo.mp4"
    f.write_bytes(b"x")
    seen = []
    monkeypatch.setattr(
        utils, "_do_open_file",
        lambda path, is_dir=False, reveal=False: seen.append((path, is_dir, reveal)),
    )
    r = client.post("/api/open-file", json={"path": str(f), "reveal": True})
    assert r.json() == {"ok": True}
    r = client.post("/api/open-file", json={"path": str(f)})
    assert r.json() == {"ok": True}
    assert seen == [(str(f), False, True), (str(f), False, False)]
