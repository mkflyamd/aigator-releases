"""Auth/Teams routes keep Graph + Teams tokens in secure_store, never on disk as JSON."""

import base64
import json
import sys
import time
import types
import urllib.request
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import secure_store

FAKE = "aigator-fake-api-key"


def _jwt(exp_in=3600, **claims):
    def seg(obj):
        raw = json.dumps(obj).encode()
        return base64.b64encode(raw).decode().rstrip("=")

    body = {"exp": int(time.time()) + exp_in, "name": FAKE, **claims}
    return f"{seg({'alg': 'none'})}.{seg(body)}.{FAKE}"


@pytest.fixture
def guard_home(tmp_path, monkeypatch):
    """Route modules must not touch Path.home(); fail loudly (and stay out of the
    real home) if they try to leave anything behind there."""
    home = tmp_path / "guard-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def client(guard_home):
    from routes import auth

    app = FastAPI()
    app.include_router(auth.router)
    return TestClient(app)


def _plaintext_json_files():
    return [p for p in secure_store._home().rglob("*.json")]


def _fake_capture(monkeypatch, token):
    monkeypatch.setitem(
        sys.modules,
        "capture_token",
        types.SimpleNamespace(capture_token=lambda *a, **k: token),
    )


def test_manual_teams_token_paste_stores_in_secure_store(client, guard_home):
    tok = _jwt(scp="Chat.Read Chat.ReadWrite")
    r = client.post("/api/auth/token", json={"token": f"Bearer {tok}"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["has_chat_read"] is True
    stored = secure_store.get_json("graph/teams_token")
    assert stored["access_token"] == tok
    assert not _plaintext_json_files()
    assert not any(guard_home.rglob("*"))


def test_teams_capture_lands_in_secure_store_and_helper_reads_it(
    client, monkeypatch, guard_home
):
    tok = _jwt(scp="Chat.ReadWrite")
    _fake_capture(monkeypatch, f"Bearer {tok}")
    r = client.post("/api/auth/teams/capture")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert secure_store.get_json("graph/teams_token")["access_token"] == tok
    assert not _plaintext_json_files()

    from skills._m365.helpers import get_teams_token

    assert get_teams_token() == tok
    assert not any(guard_home.rglob("*"))


def test_teams_capture_stream_lands_in_secure_store(client, monkeypatch, guard_home):
    tok = _jwt(scp="Chat.ReadWrite")
    _fake_capture(monkeypatch, tok)
    r = client.get("/api/auth/teams/capture/stream")
    assert r.status_code == 200
    assert "event: result" in r.text
    assert secure_store.get_json("graph/teams_token")["access_token"] == tok
    assert not _plaintext_json_files()
    assert not any(guard_home.rglob("*"))


def test_capture_failure_writes_nothing(client, monkeypatch):
    _fake_capture(monkeypatch, "")
    assert client.post("/api/auth/teams/capture").status_code == 504
    assert secure_store.get_json("graph/teams_token") is None


def test_auth_status_without_token(client):
    body = client.get("/api/auth/status").json()
    assert body["authenticated"] is False
    assert body["reason"] == "No token"
    assert body["teams_token_ok"] is False


def test_auth_status_reads_secure_store(client):
    secure_store.set_json(
        "graph/token",
        {
            "access_token": _jwt(scp="Mail.Read Chat.Read"),
            "refresh_token": FAKE,
            "tenant_id": "t",
        },
    )
    secure_store.set_json(
        "graph/teams_token",
        {"access_token": FAKE, "expires_at": time.time() + 3600},
    )
    body = client.get("/api/auth/status").json()
    assert body["authenticated"] is True
    assert body["has_refresh_token"] is True
    assert body["has_mail"] is True
    assert body["teams_token_ok"] is True
    assert body["apps"]["teams_chat"]["api"]["ok"] is True


def test_auth_status_reports_slack_from_secure_store(client):
    secure_store.set_json(
        "slack/token",
        {"access_token": FAKE, "expires_at": time.time() + 3600, "team": "t"},
    )
    slack = client.get("/api/auth/status").json()["apps"]["slack"]["api"]
    assert slack["ok"] is True and slack["team"] == "t"


def test_auth_status_migrates_legacy_plaintext_and_removes_it(client):
    legacy = secure_store._home() / ".config" / "microsoft-graph" / "teams_token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps({"access_token": FAKE, "expires_at": time.time() + 3600})
    )
    body = client.get("/api/auth/status").json()
    assert body["teams_token_ok"] is True
    assert not legacy.exists()
    assert secure_store.get_json("graph/teams_token")["access_token"] == FAKE


def test_deleting_secrets_is_honoured_by_status_and_readers(client):
    secure_store.set_json(
        "graph/token", {"access_token": _jwt(), "refresh_token": FAKE}
    )
    secure_store.set_json(
        "graph/teams_token",
        {"access_token": FAKE, "expires_at": time.time() + 3600},
    )
    assert client.get("/api/auth/status").json()["authenticated"] is True

    secure_store.delete("graph/token")
    secure_store.delete("graph/teams_token")

    body = client.get("/api/auth/status").json()
    assert body["authenticated"] is False and body["reason"] == "No token"
    assert body["teams_token_ok"] is False
    assert body["apps"]["teams_chat"]["api"]["ok"] is False
    assert not _plaintext_json_files()


def test_device_auth_completion_stores_in_secure_store(
    client, monkeypatch, guard_home
):
    access = _jwt(tid="tenant-1", scp="Mail.Read")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                {
                    "access_token": access,
                    "refresh_token": FAKE,
                    "expires_in": 3600,
                    "scope": "Mail.Read",
                }
            ).encode()

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    r = client.post(
        "/api/auth/device/poll",
        json={"device_code": FAKE, "tenant_id": "organizations"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    stored = secure_store.get_json("graph/token")
    assert stored["access_token"] == access
    assert stored["refresh_token"] == FAKE
    assert stored["tenant_id"] == "tenant-1"
    assert not _plaintext_json_files()
    assert not any(guard_home.rglob("*"))
    assert client.get("/api/auth/status").json()["authenticated"] is True


def test_device_auth_poll_never_logs_token_values(client, monkeypatch, caplog):
    access = _jwt(tid="tenant-1")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                {"access_token": access, "refresh_token": FAKE, "expires_in": 3600}
            ).encode()

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    with caplog.at_level("DEBUG"):
        client.post("/api/auth/device/poll", json={"device_code": FAKE})
    assert access not in caplog.text
    assert FAKE not in caplog.text


# ── teams.py readers ──────────────────────────────────────────────────────────


def test_teams_routes_read_graph_token_from_secure_store(guard_home):
    from routes import teams

    secure_store.set_json(
        "graph/token", {"access_token": _jwt(oid="oid-1", name="Fake User")}
    )
    assert teams._get_my_name() == "Fake User"
    assert not any(guard_home.rglob("*"))


def test_teams_chat_readwrite_token_reads_secure_store(guard_home):
    from routes import teams

    with pytest.raises(RuntimeError, match="not found"):
        teams._chat_readwrite_token()

    secure_store.set_json(
        "graph/teams_token", {"access_token": FAKE, "expires_at": time.time() + 3600}
    )
    assert teams._chat_readwrite_token() == FAKE

    secure_store.set_json(
        "graph/teams_token", {"access_token": FAKE, "expires_at": time.time() - 10}
    )
    with pytest.raises(RuntimeError, match="expired"):
        teams._chat_readwrite_token()
    assert not any(guard_home.rglob("*"))


def test_teams_module_has_no_token_file_references():
    src = (
        Path(__file__).resolve().parents[1] / "web" / "routes" / "teams.py"
    ).read_text(encoding="utf-8")
    auth_src = (
        Path(__file__).resolve().parents[1] / "web" / "routes" / "auth.py"
    ).read_text(encoding="utf-8")
    for text in (src, auth_src):
        assert "token.json" not in text
        assert "teams_token.json" not in text
