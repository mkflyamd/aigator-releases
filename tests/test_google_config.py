import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi import HTTPException

from routes import config_routes as cr

CLIENT_ID = "1234567890-abc.apps.googleusercontent.com"
SECRET = "aigator-fake-api-key"


@pytest.fixture
def store(monkeypatch):
    data = {}
    monkeypatch.setattr(cr, "_load_config", lambda: data)

    def fake_update(fn):
        fn(data)
        return data

    monkeypatch.setattr(cr, "_update_config", fake_update)
    monkeypatch.setattr(cr, "probe_google_client", lambda cid, sec: "ok")
    return data


def _req(**kw):
    base = {"client_id": CLIENT_ID, "client_secret": SECRET}
    base.update(kw)
    return cr.GoogleWorkspaceConfigRequest(**base)


def test_save_writes_accounts_and_mirrors_default(store):
    out = cr.save_google_workspace(_req(accounts=["Me@Example.test", "work@example.test", "me@example.test"]))
    assert store["google_accounts"] == ["me@example.test", "work@example.test"]
    assert store["google_user_email"] == "me@example.test"
    assert out["accounts"] == ["me@example.test", "work@example.test"]


def test_save_without_accounts_leaves_them_unchanged(store):
    store["google_accounts"] = ["me@example.test"]
    cr.save_google_workspace(_req())
    assert store["google_accounts"] == ["me@example.test"]


def test_save_empty_accounts_clears_default(store):
    store.update({"google_accounts": ["me@example.test"], "google_user_email": "me@example.test"})
    cr.save_google_workspace(_req(accounts=[]))
    assert store["google_accounts"] == []
    assert store["google_user_email"] == ""


def test_bad_email_is_rejected(store):
    with pytest.raises(HTTPException) as exc:
        cr.save_google_workspace(_req(accounts=["not-an-email"]))
    assert exc.value.status_code == 400
    assert "not-an-email" in exc.value.detail
    assert "google_oauth_client_id" not in store


def test_bad_client_id_is_rejected(store):
    with pytest.raises(HTTPException) as exc:
        cr.save_google_workspace(_req(client_id="abc"))
    assert exc.value.status_code == 400
    assert "apps.googleusercontent.com" in exc.value.detail


def test_secret_with_whitespace_is_rejected(store):
    with pytest.raises(HTTPException) as exc:
        cr.save_google_workspace(_req(client_secret="two words"))
    assert exc.value.status_code == 400


def test_probe_invalid_client_returns_400_and_does_not_save(store, monkeypatch):
    monkeypatch.setattr(cr, "probe_google_client", lambda cid, sec: "invalid_client")
    with pytest.raises(HTTPException) as exc:
        cr.save_google_workspace(_req())
    assert exc.value.status_code == 400
    assert "client secret is wrong" in exc.value.detail
    assert "google_oauth_client_secret" not in store


def test_probe_network_failure_still_saves(store, monkeypatch):
    monkeypatch.setattr(cr, "probe_google_client", lambda cid, sec: "unknown")
    cr.save_google_workspace(_req())
    assert store["google_oauth_client_id"] == CLIENT_ID


def test_status_reports_accounts_and_signed_in(store, tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_MCP_CREDENTIALS_DIR", str(tmp_path))
    (tmp_path / "me@example.test.json").write_text("{}")
    store["google_accounts"] = ["me@example.test", "work@example.test"]
    out = cr.google_workspace_credentials_status()
    assert out["accounts"] == [
        {"email": "me@example.test", "default": True, "signed_in": True},
        {"email": "work@example.test", "default": False, "signed_in": False},
    ]


def test_status_reads_legacy_single_email(store, tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_MCP_CREDENTIALS_DIR", str(tmp_path))
    store["google_user_email"] = "old@example.test"
    out = cr.google_workspace_credentials_status()
    assert [a["email"] for a in out["accounts"]] == ["old@example.test"]
