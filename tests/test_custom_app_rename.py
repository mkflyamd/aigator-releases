import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi.testclient import TestClient

from app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def csrf_headers():
    from security import get_csrf_token

    return {"X-CSRF-Token": get_csrf_token("testserver")}


@pytest.fixture
def cfg(monkeypatch):
    import config

    state = {"custom_apps": [{"id": "custom-old", "name": "Old", "url": "https://example.com", "icon": "x"}]}

    def fake_update(mutator):
        updated = mutator(state)
        if updated is not None:
            state.update(updated)
        return state

    monkeypatch.setattr(config, "update_config", fake_update)
    return state


def test_rename_custom_app(client, csrf_headers, cfg):
    res = client.patch("/api/config/custom-apps/custom-old", json={"name": "  New  "}, headers=csrf_headers)
    assert res.status_code == 200
    assert res.json()["app"]["name"] == "New"
    assert cfg["custom_apps"][0]["name"] == "New"
    assert cfg["custom_apps"][0]["url"] == "https://example.com"


def test_rename_caps_name_at_40_characters(client, csrf_headers, cfg):
    res = client.patch("/api/config/custom-apps/custom-old", json={"name": "a" * 60}, headers=csrf_headers)
    assert res.status_code == 200
    assert len(cfg["custom_apps"][0]["name"]) == 40


def test_rename_unknown_app_is_404(client, csrf_headers, cfg):
    res = client.patch("/api/config/custom-apps/custom-nope", json={"name": "X"}, headers=csrf_headers)
    assert res.status_code == 404


def test_rename_blank_name_is_rejected(client, csrf_headers, cfg):
    res = client.patch("/api/config/custom-apps/custom-old", json={"name": "   "}, headers=csrf_headers)
    assert res.status_code == 422
    assert cfg["custom_apps"][0]["name"] == "Old"


def test_rename_requires_csrf(client, cfg):
    res = client.patch("/api/config/custom-apps/custom-old", json={"name": "New"})
    assert res.status_code == 403
    assert cfg["custom_apps"][0]["name"] == "Old"
