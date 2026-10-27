"""POST /api/dictation/transcribe: auth, validation and happy path."""
import pytest
from fastapi.testclient import TestClient

from app import app
from dictation import service

URL = "/api/dictation/transcribe"


def _csrf():
    from security import get_csrf_token
    return {"X-CSRF-Token": get_csrf_token("testserver")}


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


def test_oversize_streaming_upload_is_rejected(client):
    sent = []

    def body():
        for _ in range(service.MAX_PCM_BYTES // 3200 + 4):
            sent.append(1)
            yield b"\x00" * 3200

    r = client.post(URL, content=body(), headers=_csrf())
    assert r.status_code == 413
    assert "content-length" not in r.request.headers
    assert client.calls == []


def test_streaming_upload_within_limit_is_transcribed(client):
    def body():
        for _ in range(5):
            yield b"\x01\x00" * 1600

    r = client.post(URL, content=body(), headers=_csrf())
    assert r.status_code == 200
    assert r.json() == {"text": "hello world"}
    assert client.calls == [16000]


def test_oversize_streaming_upload_stops_reading_at_the_limit(client):
    import asyncio

    chunk = b"\x00" * 3200
    limit_chunks = service.MAX_PCM_BYTES // len(chunk)
    reads = {"n": 0}
    sent = []

    async def receive():
        reads["n"] += 1
        if reads["n"] > limit_chunks * 10:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": URL,
        "raw_path": URL.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"transfer-encoding", b"chunked"),
            (b"x-csrf-token", _csrf()["X-CSRF-Token"].encode()),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    assert status == 413
    assert reads["n"] <= limit_chunks + 2
    assert client.calls == []
