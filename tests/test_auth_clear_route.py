import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi.testclient import TestClient

import secure_store
from app import app
import routes.auth as _auth_mod

_REAL_REVOKE_OAUTH = _auth_mod._revoke_oauth

FAKE = "aigator-fake-api-key"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def csrf_headers():
    from security import get_csrf_token

    return {"X-CSRF-Token": get_csrf_token()}


def _seed():
    secure_store.set_json("graph/token", {"access_token": FAKE})
    secure_store.set_json("slack/token", {"access_token": FAKE})
    secure_store.set_json("oauth/p1", {"id": "p1", "token": {"access_token": FAKE}})
    secure_store.set("config/jira_pat", FAKE)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    import routes.auth as auth

    monkeypatch.setattr(auth, "_revoke_slack", lambda tok: None)
    monkeypatch.setattr(auth, "_revoke_oauth", lambda rec: None)


def test_clear_requires_csrf(client):
    _seed()
    assert client.post("/api/auth/clear", json={"scope": "all"}).status_code == 403
    assert secure_store.get_json("graph/token")


def test_clear_all(client, csrf_headers):
    _seed()
    r = client.post("/api/auth/clear", json={"scope": "all"}, headers=csrf_headers)
    assert r.status_code == 200
    assert secure_store.list_names() == []


def test_clear_single_scope_leaves_others(client, csrf_headers):
    _seed()
    client.post("/api/auth/clear", json={"scope": "slack"}, headers=csrf_headers)
    assert secure_store.get_json("slack/token") is None
    assert secure_store.get_json("graph/token")


def test_clear_revokes_slack_best_effort_and_survives_failure(client, csrf_headers, monkeypatch):
    import routes.auth as auth

    calls = []
    monkeypatch.setattr(
        auth,
        "_revoke_slack",
        lambda tok: calls.append(tok) or (_ for _ in ()).throw(RuntimeError("net")),
    )
    _seed()
    r = client.post("/api/auth/clear", json={"scope": "slack"}, headers=csrf_headers)
    assert r.status_code == 200
    assert calls == [{"access_token": FAKE}]
    assert secure_store.get_json("slack/token") is None  # cleared locally even though revoke failed


def test_clear_invalid_scope_is_400(client, csrf_headers):
    assert client.post("/api/auth/clear", json={"scope": "nope"}, headers=csrf_headers).status_code == 400


def test_clear_pats_pops_environment(client, csrf_headers, monkeypatch):
    _seed()
    monkeypatch.setenv("GITHUB_TOKEN", FAKE)
    r = client.post("/api/auth/clear", json={"scope": "pats"}, headers=csrf_headers)
    assert r.status_code == 200
    import os

    assert "GITHUB_TOKEN" not in os.environ
    assert secure_store.get("config/jira_pat") is None
    assert secure_store.get_json("graph/token")


def test_clear_pats_also_drops_in_memory_config_copy(client, csrf_headers):
    import config
    import shared

    _seed()
    shared.cfg["jira_pat"] = FAKE
    client.post("/api/auth/clear", json={"scope": "pats"}, headers=csrf_headers)
    assert "jira_pat" not in shared.cfg
    config.save_config(shared.cfg)
    assert secure_store.get("config/jira_pat") is None


def test_revoke_oauth_refuses_non_https_endpoint(monkeypatch):
    import routes.auth as auth

    seen = []
    monkeypatch.setattr(auth.urllib.request, "urlopen", lambda *a, **k: seen.append(a))
    with pytest.raises(ValueError):
        _REAL_REVOKE_OAUTH(
            {
                "provider": {"revocation_endpoint": "http://a.invalid/revoke"},
                "token": {"access_token": FAKE},
            }
        )
    assert seen == []


def test_revoke_oauth_posts_to_revocation_endpoint(monkeypatch):
    import routes.auth as auth

    real = _REAL_REVOKE_OAUTH  # the autouse fixture stubs the module attribute
    seen = []

    class _Resp:
        def read(self):
            return b""

    monkeypatch.setattr(
        auth.urllib.request,
        "urlopen",
        lambda req, timeout=0: seen.append((req.full_url, req.data)) or _Resp(),
    )
    real(
        {
            "provider": {"revocation_endpoint": "https://a.invalid/revoke", "client_id": "c"},
            "token": {"access_token": FAKE, "refresh_token": FAKE},
        }
    )
    assert [u for u, _ in seen] == ["https://a.invalid/revoke"] * 2
    assert b"refresh_token" in seen[0][1]


def test_provider_round_trips_revocation_endpoint():
    from oauth.provider import OAuthProvider

    p = OAuthProvider(
        id="p1",
        mode="static",
        authorize_url="https://a.invalid/auth",
        token_url="https://a.invalid/token",
        client_id="c",
        revocation_endpoint="https://a.invalid/revoke",
    )
    assert OAuthProvider.from_dict(p.to_dict()).revocation_endpoint == "https://a.invalid/revoke"
