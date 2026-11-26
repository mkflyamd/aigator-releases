"""Usage-sharing status route: read-only, no opt-out."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from fastapi import FastAPI
from fastapi.testclient import TestClient

import security
import shared
import usage_report
from routes.usage_sharing import router

HOST = "127.0.0.1:8000"
CFG = {"usage_list_site_id": "aigator-fake-site", "usage_list_id": "aigator-fake-list"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(usage_report, "STATE_FILE", tmp_path / "usage_report.json")
    monkeypatch.setattr(shared, "cfg", dict(CFG))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_status_starts_waiting_when_reporting_is_available(client):
    body = client.get("/api/usage-sharing").json()
    assert body == {"available": True, "status": "waiting", "last_sent_at": None}


def test_status_is_unavailable_without_admin_config(client, monkeypatch):
    monkeypatch.setattr(shared, "cfg", {})
    assert client.get("/api/usage-sharing").json()["available"] is False


def test_there_is_no_opt_out_route(client):
    headers = {"X-CSRF-Token": security.get_csrf_token(HOST), "Host": HOST}
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/usage-sharing", headers=headers)
        assert response.status_code == 405
    assert [r.methods for r in router.routes] == [{"GET"}]
