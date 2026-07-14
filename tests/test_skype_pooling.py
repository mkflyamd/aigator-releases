"""Tests for the Skype connection-pooling change + the /api/perf local guard.

Covers the gaps that couldn't be verified against the live server:
  1. skype_get_json re-raises non-2xx as urllib.error.HTTPError (preserving the
     .code + body '911' marker) so Skype auth-lag detection keeps working, and a
     transport error becomes a urllib.error.URLError.
  2. teams._is_skype_auth_error still classifies that HTTPError as auth, and
     GET /api/teams/chats maps a Skype auth-lag failure to a retryable 503.
  3. health._require_local (and GET /api/perf) return 404 for non-loopback
     clients, 200 for loopback / DEV_MODE.

These are fast, deterministic unit tests — no live server, no Microsoft auth.
"""

import importlib.util
import os
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

WEB = Path(__file__).resolve().parent.parent / "web"


def _load_read_chats():
    """Load read_chats.py the same way the app does (it lives under a dashed path)."""
    path = WEB / "skills" / "m365-teams" / "scripts" / "read_chats.py"
    spec = importlib.util.spec_from_file_location("_test_read_chats", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


read_chats = _load_read_chats()


class _FakeResp:
    def __init__(self, status_code, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = {} if json_data is None else json_data

    def json(self):
        return self._json


class _FakeClient:
    """Stands in for the pooled httpx.Client, returning a canned response."""
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc

    def get(self, url, headers=None, timeout=None):
        if self._exc is not None:
            raise self._exc
        return self._resp


# ── 1. skype_get_json transport/contract ────────────────────────────────────

def test_skype_get_json_success_returns_json():
    resp = _FakeResp(200, json_data={"conversations": [1, 2]})
    with patch.object(read_chats, "_skype_client", return_value=_FakeClient(resp)):
        out = read_chats.skype_get_json("https://chatsvc/v1/users/ME/conversations", "tok")
    assert out == {"conversations": [1, 2]}


def test_skype_get_json_reraises_httperror_with_code_and_body():
    """Non-2xx must surface as urllib.error.HTTPError carrying the status code and
    the response body (so the '911' auth-lag marker is visible to callers)."""
    body = '{"errorCode":911,"message":"Authentication failed"}'
    resp = _FakeResp(401, text=body)
    with patch.object(read_chats, "_skype_client", return_value=_FakeClient(resp)):
        with pytest.raises(urllib.error.HTTPError) as ei:
            read_chats.skype_get_json("https://chatsvc/x", "tok")
    assert ei.value.code == 401
    assert "911" in str(ei.value)


def test_skype_get_json_transport_error_becomes_urlerror():
    import httpx
    client = _FakeClient(exc=httpx.ConnectError("connection refused"))
    with patch.object(read_chats, "_skype_client", return_value=client):
        with pytest.raises(urllib.error.URLError):
            read_chats.skype_get_json("https://chatsvc/x", "tok")


# ── 2. auth-lag detection + 503 mapping ──────────────────────────────────────

def test_is_skype_auth_error_detects_pooled_httperror():
    from routes import teams
    assert teams._is_skype_auth_error(
        urllib.error.HTTPError("https://x", 401, '{"errorCode":911}', None, None)
    ) is True
    assert teams._is_skype_auth_error(
        urllib.error.HTTPError("https://x", 403, "", None, None)
    ) is True
    # A genuine server error is NOT an auth problem.
    assert teams._is_skype_auth_error(
        urllib.error.HTTPError("https://x", 500, "boom", None, None)
    ) is False


def test_teams_chats_returns_503_on_skype_auth_lag():
    """A Skype 401 (token still minting) must surface as a retryable 503, not 500,
    through the pooled code path."""
    from routes import teams

    def _boom(*a, **k):
        raise urllib.error.HTTPError("https://chatsvc", 401, '{"errorCode":911}', None, None)

    fake_mod = SimpleNamespace(
        get_auth=lambda: ("tok", "https://chatsvc/v1"),
        list_chats=_boom,
    )
    app = FastAPI()
    app.include_router(teams.router)
    with patch.object(teams, "_get_skype_module", return_value=fake_mod):
        client = TestClient(app)
        r = client.get("/api/teams/chats")
    assert r.status_code == 503


# ── 3. /api/perf local-only guard ────────────────────────────────────────────

def test_require_local_allows_loopback_blocks_others(monkeypatch):
    from routes import health
    monkeypatch.delenv("DEV_MODE", raising=False)
    for host in ("127.0.0.1", "::1", "localhost"):
        health._require_local(SimpleNamespace(client=SimpleNamespace(host=host)))  # no raise
    with pytest.raises(HTTPException) as ei:
        health._require_local(SimpleNamespace(client=SimpleNamespace(host="10.0.0.5")))
    assert ei.value.status_code == 404


def test_perf_endpoint_404_from_non_loopback(monkeypatch):
    from routes import health
    monkeypatch.delenv("DEV_MODE", raising=False)
    app = FastAPI()
    app.include_router(health.router)
    # TestClient reports client host "testclient" — a non-loopback address.
    r = TestClient(app).get("/api/perf")
    assert r.status_code == 404


def test_perf_endpoint_ok_with_dev_mode(monkeypatch):
    from routes import health
    monkeypatch.setenv("DEV_MODE", "1")
    app = FastAPI()
    app.include_router(health.router)
    r = TestClient(app).get("/api/perf")
    assert r.status_code == 200
    assert "endpoints" in r.json()
