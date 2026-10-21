"""Settings > AI Model > About you: who "me" and "myself" mean to the assistant."""

import pytest
from app import app
from fastapi.testclient import TestClient
from routes import config_routes as cr
from security import get_csrf_token


@pytest.fixture
def store(monkeypatch):
    saved = {}
    monkeypatch.setattr(cr, "_load_config", lambda: dict(saved))
    monkeypatch.setattr(cr, "_save_config", lambda cfg: saved.update(cfg))
    monkeypatch.setattr(
        cr, "_signed_in_identity", lambda: {"name": "", "email": ""}
    )
    return saved


@pytest.fixture
def client():
    return TestClient(app, headers={"X-CSRF-Token": get_csrf_token("testserver")})


def test_save_then_prompt_names_the_user(store, client):
    res = client.post(
        "/api/config/user-profile",
        json={"name": " Ada   Lovelace ", "email": "ada@example.com"},
    )
    assert res.status_code == 200
    assert store["user_profile"] == {"name": "Ada Lovelace", "email": "ada@example.com"}
    prompt = cr._get_user_profile_prompt()
    assert "Ada Lovelace <ada@example.com>" in prompt
    assert "email myself" in prompt


def test_signed_in_account_fills_the_gap(store, monkeypatch):
    monkeypatch.setattr(
        cr,
        "_signed_in_identity",
        lambda: {"name": "Grace Hopper", "email": "grace@example.com"},
    )
    assert cr._get_user_profile() == {
        "name": "Grace Hopper",
        "email": "grace@example.com",
    }


def test_saved_details_win_over_signed_in_account(store, monkeypatch):
    store["user_profile"] = {"name": "", "email": "me@example.com"}
    monkeypatch.setattr(
        cr,
        "_signed_in_identity",
        lambda: {"name": "Grace Hopper", "email": "grace@example.com"},
    )
    assert cr._get_user_profile() == {
        "name": "Grace Hopper",
        "email": "me@example.com",
    }


def test_no_details_adds_nothing_to_the_prompt(store):
    assert cr._get_user_profile_prompt() == ""


@pytest.mark.parametrize("bad", ["not-an-email", "a b@example.com"])
def test_rejects_malformed_email(store, client, bad):
    res = client.post("/api/config/user-profile", json={"name": "", "email": bad})
    assert res.status_code == 400
    assert "user_profile" not in store


def test_save_requires_csrf(store):
    res = TestClient(app).post(
        "/api/config/user-profile", json={"name": "A", "email": ""}
    )
    assert res.status_code == 403


def test_get_returns_only_what_was_saved(store, client, monkeypatch):
    store["user_profile"] = {"name": "Ada", "email": "ada@example.com"}
    monkeypatch.setattr(
        cr, "_signed_in_identity", lambda: {"name": "G", "email": "g@example.com"}
    )
    assert client.get("/api/config/user-profile").json() == {
        "name": "Ada",
        "email": "ada@example.com",
    }


def test_untouched_program_manager_becomes_technical_program_manager(store):
    store["personas"] = {"program-manager": dict(cr._OLD_PROGRAM_MANAGER)}
    store["active_persona"] = "program-manager"
    personas = cr._get_personas()
    assert list(personas) == ["technical-program-manager"]
    assert store["active_persona"] == "technical-program-manager"


def test_edited_program_manager_is_left_alone(store):
    edited = {"name": "Program Manager", "prompt": "my own words"}
    store["personas"] = {"program-manager": edited}
    assert cr._get_personas() == {"program-manager": edited}


def test_program_manager_with_garbled_dash_is_still_migrated(store):
    garbled = dict(cr._OLD_PROGRAM_MANAGER)
    garbled["prompt"] = garbled["prompt"].replace("\u2014", "\u00e2\u20ac\u201d")
    store["personas"] = {"program-manager": garbled}
    assert list(cr._get_personas()) == ["technical-program-manager"]
