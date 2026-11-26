"""Usage-sharing consent routes: status, choice, CSRF."""

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


def _csrf():
    return {"X-CSRF-Token": security.get_csrf_token(HOST), "Host": HOST}


def test_status_starts_not_started_when_reporting_is_available(client):
    body = client.get("/api/usage-sharing").json()
    assert body == {"available": True, "consent": "unset", "status": "not_started", "last_sent_at": None}


def test_status_is_unavailable_without_admin_config(client, monkeypatch):
    monkeypatch.setattr(shared, "cfg", {})
    assert client.get("/api/usage-sharing").json()["available"] is False


def test_choice_requires_the_csrf_token(client):
    assert client.post("/api/usage-sharing", json={"enabled": True}).status_code == 403
    assert usage_report.consent_choice() == "unset"


def test_keep_sharing_saves_consent_and_wakes_the_reporter(client, monkeypatch):
    woke = []
    monkeypatch.setattr(usage_report, "request_report", lambda: woke.append(1))
    body = client.post("/api/usage-sharing", json={"enabled": True}, headers=_csrf()).json()
    assert body["consent"] == "on"
    assert usage_report.consent_choice() == "on"
    assert woke == [1]


def test_turn_off_saves_consent_and_does_not_wake_the_reporter(client, monkeypatch):
    woke = []
    monkeypatch.setattr(usage_report, "request_report", lambda: woke.append(1))
    body = client.post("/api/usage-sharing", json={"enabled": False}, headers=_csrf()).json()
    assert body["consent"] == "off"
    assert body["status"] == "off"
    assert woke == []


def test_choice_needs_a_boolean(client):
    assert client.post("/api/usage-sharing", json={}, headers=_csrf()).status_code == 422
