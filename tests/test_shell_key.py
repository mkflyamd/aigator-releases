"""The CSRF token is served only to the AI Gator shell (per-launch shell key)."""

import importlib
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi.testclient import TestClient

import sandbox
import security
from app import app

FAKE = "aigator-fake-api-key"
HEADER = "X-AIGator-Shell-Key"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(security, "_SHELL_KEY", FAKE)


@pytest.mark.parametrize("path", ["/api/csrf", "/"])
def test_token_endpoints_refuse_without_key(client, keyed, path):
    assert client.get(path).status_code == 403


@pytest.mark.parametrize("path", ["/api/csrf", "/"])
def test_token_endpoints_refuse_wrong_key(client, keyed, path):
    assert client.get(path, headers={HEADER: "wrong"}).status_code == 403


def test_csrf_endpoint_serves_token_with_right_key(client, keyed):
    r = client.get("/api/csrf", headers={HEADER: FAKE})
    assert r.status_code == 200
    assert r.json()["csrf_token"] == security.get_csrf_token()


def test_root_serves_page_with_right_key(client, keyed):
    r = client.get("/", headers={HEADER: FAKE})
    assert r.status_code == 200
    assert security.get_csrf_token() in r.text


@pytest.mark.parametrize("path", ["/api/csrf", "/"])
def test_no_key_configured_leaves_endpoints_open(client, monkeypatch, path):
    monkeypatch.setattr(security, "_SHELL_KEY", None)
    assert client.get(path).status_code == 200


def test_csrf_guarded_route_still_needs_csrf_header(client, keyed):
    # The shell key does not replace X-CSRF-Token on guarded routes.
    r = client.post("/api/auth/clear", headers={HEADER: FAKE})
    assert r.status_code == 403
    assert "CSRF" in r.json()["detail"]


def test_key_is_read_once_and_scrubbed_from_environment(monkeypatch):
    token = security._TOKEN
    monkeypatch.setenv("AIGATOR_SHELL_KEY", FAKE)
    try:
        importlib.reload(security)
        assert security._SHELL_KEY == FAKE
        assert "AIGATOR_SHELL_KEY" not in os.environ
    finally:
        monkeypatch.delenv("AIGATOR_SHELL_KEY", raising=False)
        importlib.reload(security)
        security._TOKEN = token
        assert security._SHELL_KEY is None


def test_sandbox_env_allow_list_drops_shell_key(tmp_path):
    parent = {"AIGATOR_SHELL_KEY": FAKE, "PATH": "/usr/bin", "SYSTEMROOT": "C:\\Windows"}
    for platform in ("linux", "win32"):
        env = sandbox.build_env(parent, tmp_path, None, platform=platform)
        assert "AIGATOR_SHELL_KEY" not in {k.upper() for k in env}
        assert FAKE not in env.values()
