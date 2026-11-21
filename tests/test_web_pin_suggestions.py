import base64
import uuid

import pytest
from fastapi.testclient import TestClient

import routes.web_pins as wp
from app import app
from security import get_csrf_token
from skills.context import state
from skills.webpin import store

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16
ACTION = "Draft an email to the team about this"


@pytest.fixture
def client():
    return TestClient(app, headers={"X-CSRF-Token": get_csrf_token("testserver")})


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_ROOT", tmp_path / "web_pins")
    monkeypatch.setattr(state, "pinned_contexts", {})
    monkeypatch.setattr(state, "_save", lambda: None)
    monkeypatch.setattr(wp, "_custom_apps", lambda: [{"id": "pbi", "name": "Power BI"}])


def _pin(client):
    body = {"context_id": "t", "app_id": "pbi", "image_b64": base64.b64encode(PNG).decode(), "text": "Revenue 4.2M, Cost 3.1M"}
    return client.post("/api/web-pins", json=body).json()["id"]


def test_questions_from_llm_plus_action(client, monkeypatch):
    monkeypatch.setattr(wp, "_ask_llm", lambda p: '["Why did revenue rise?", "What is the margin?", "Which region leads?", "Fourth?"]')
    pid = _pin(client)
    s = client.get(f"/api/web-pins/{pid}/suggestions").json()["suggestions"]
    assert [x["kind"] for x in s] == ["question", "question", "question", "action"]
    assert s[0]["text"] == "Why did revenue rise?" and s[-1]["text"] == ACTION


def test_prompt_contains_wrapped_page_text(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(wp, "_ask_llm", lambda p: seen.setdefault("p", p) and "[]")
    pid = _pin(client)
    client.get(f"/api/web-pins/{pid}/suggestions")
    assert "Revenue 4.2M" in seen["p"] and "untrusted" in seen["p"].lower()


def test_fallback_when_llm_fails_or_returns_junk(client, monkeypatch):
    pid = _pin(client)

    def boom(p):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(wp, "_ask_llm", boom)
    s = client.get(f"/api/web-pins/{pid}/suggestions").json()["suggestions"]
    assert [x["text"] for x in s] == ["Summarize this", "What stands out?", ACTION]
    monkeypatch.setattr(wp, "_ask_llm", lambda p: "not json at all")
    assert client.get(f"/api/web-pins/{pid}/suggestions").json()["suggestions"][0]["text"] == "Summarize this"


def test_overlong_and_non_string_items_are_dropped(client, monkeypatch):
    monkeypatch.setattr(wp, "_ask_llm", lambda p: '["' + "x" * 200 + '", 5, "Ok?\\nline two", "Ok?"]')
    pid = _pin(client)
    texts = [x["text"] for x in client.get(f"/api/web-pins/{pid}/suggestions").json()["suggestions"] if x["kind"] == "question"]
    assert texts == ["Ok? line two"] or texts == ["Ok? line two", "Ok?"]
    assert all(len(t) <= 80 and "\n" not in t for t in texts)


def test_unknown_pin_404(client):
    assert client.get(f"/api/web-pins/{uuid.uuid4()}/suggestions").status_code == 404
