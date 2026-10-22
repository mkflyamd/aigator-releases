"""POST /api/dictation/transcribe: auth, validation and happy path."""
import pytest
from fastapi.testclient import TestClient

from app import app
from dictation import service

URL = "/api/dictation/transcribe"


def _csrf():
    from security import get_csrf_token
    return {"X-CSRF-Token": get_csrf_token()}


@pytest.fixture
def client(monkeypatch):
    calls = []

    def fake_transcribe(pcm, cfg=None):
        calls.append(len(pcm))
        return "hello world"

    monkeypatch.setattr(service, "transcribe", fake_transcribe)
    c = TestClient(app)
    c.calls = calls
    return c


def test_requires_csrf_token(client):
    r = client.post(URL, content=b"\x00\x00")
    assert r.status_code == 403
    assert client.calls == []


def test_returns_text(client):
    r = client.post(URL, content=b"\x01\x00" * 1600, headers=_csrf())
    assert r.status_code == 200
    assert r.json() == {"text": "hello world"}
    assert client.calls == [3200]


def test_empty_body_returns_empty_text_without_engine(client):
    r = client.post(URL, content=b"", headers=_csrf())
    assert r.status_code == 200
    assert r.json() == {"text": ""}
    assert client.calls == []


def test_odd_length_is_rejected(client):
    r = client.post(URL, content=b"\x00\x00\x00", headers=_csrf())
    assert r.status_code == 400
    assert client.calls == []


def test_oversize_is_rejected(client):
    r = client.post(URL, content=b"\x00" * (service.MAX_PCM_BYTES + 2), headers=_csrf())
    assert r.status_code == 413
    assert client.calls == []


def test_max_size_is_accepted(client):
    r = client.post(URL, content=b"\x00" * service.MAX_PCM_BYTES, headers=_csrf())
    assert r.status_code == 200


def test_unavailable_engine_returns_503(monkeypatch):
    def boom(pcm, cfg=None):
        raise service.DictationUnavailable("model missing")

    monkeypatch.setattr(service, "transcribe", boom)
    r = TestClient(app).post(URL, content=b"\x00\x00", headers=_csrf())
    assert r.status_code == 503
    assert "model missing" in r.json()["detail"]
