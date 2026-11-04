import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi.testclient import TestClient

import data_sources
import permissions
import secure_store
from app import app
from permissions import registry, store
from sandbox.policy import Policy

JIRA = "data:Jira"


@pytest.fixture(autouse=True)
def _fresh():
    data_sources._reset()
    yield
    data_sources._reset()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def csrf():
    from security import get_csrf_token

    return {"X-CSRF-Token": get_csrf_token("testserver")}


@pytest.fixture
def deny_persistent(monkeypatch):
    monkeypatch.setattr(permissions, "load_policy", lambda: Policy(persistent_permissions="deny"))


def test_default_is_ask():
    assert permissions.decision("tab-1", JIRA) == "ask"


def test_always_rule_allows_every_tab():
    permissions.remember(JIRA)
    assert permissions.decision("tab-1", JIRA) == "allow"
    assert permissions.decision("tab-2", JIRA) == "allow"


def test_tab_grant_is_per_tab_and_ends_with_the_tab():
    permissions.allow_for_tab("tab-1", JIRA)
    assert permissions.decision("tab-1", JIRA) == "allow"
    assert permissions.decision("tab-2", JIRA) == "ask"
    data_sources.end_for_tab("tab-1")
    assert permissions.decision("tab-1", JIRA) == "ask"


def test_tab_grant_uses_the_existing_data_sources_key():
    data_sources.allow("tab-1", JIRA)
    assert permissions.decision("tab-1", JIRA) == "allow"


def test_unattended_run_always_asks_even_with_a_rule():
    permissions.remember(JIRA)
    assert permissions.decision(None, JIRA) == "ask"
    assert permissions.decision("", JIRA) == "ask"


def test_unknown_category_asks():
    assert permissions.decision("tab-1", "data:Nope") == "ask"
    with pytest.raises(ValueError):
        permissions.remember("data:Nope")


def test_policy_deny_ignores_rules_and_refuses_new_ones(deny_persistent):
    store.add(JIRA)
    assert permissions.decision("tab-1", JIRA) == "ask"
    with pytest.raises(ValueError):
        permissions.remember(JIRA)
    permissions.allow_for_tab("tab-1", JIRA)  # a tab grant is not a persistent permission
    assert permissions.decision("tab-1", JIRA) == "allow"


def test_web_is_remembered_per_host_not_for_all_sites():
    permissions.remember("web", "github.com")
    assert permissions.decision("tab-1", "web", "github.com") == "allow"
    assert permissions.decision("tab-1", "web", "evil.example") == "ask"
    assert permissions.decision("tab-1", "web") == "ask"
    with pytest.raises(ValueError):
        permissions.remember("web")
    with pytest.raises(ValueError):
        permissions.set_mode("web", "always")


def test_web_tab_grant_matches_the_data_sources_host_key():
    data_sources.allow("tab-1", "web:github.com")
    assert permissions.decision("tab-1", "web", "github.com") == "allow"
    assert permissions.decision("tab-1", "web", "other.example") == "ask"


def test_mcp_category_is_built_from_the_connection_id():
    permissions.remember("mcp:mcp-google-workspace")
    assert permissions.decision("tab-1", "mcp:mcp-google-workspace") == "allow"
    assert permissions.decision("tab-1", "mcp:mcp-other") == "ask"
    assert registry.get("mcp:") is None


def test_a_category_without_always_cannot_be_remembered(monkeypatch):
    once_only = registry.Category("x", "X", "x", "high", scopes=("once",))
    monkeypatch.setattr(registry, "known", lambda: [once_only])
    with pytest.raises(ValueError):
        permissions.remember("x")
    with pytest.raises(ValueError):
        permissions.allow_for_tab("tab-1", "x")


def test_set_mode_round_trip():
    permissions.set_mode("browser", "always")
    assert permissions.decision("tab-1", "browser") == "allow"
    permissions.set_mode("browser", "ask")
    assert permissions.decision("tab-1", "browser") == "ask"
    with pytest.raises(ValueError):
        permissions.set_mode("browser", "sometimes")


def test_mode_ask_keeps_a_websites_rule():
    permissions.remember("web", "github.com")
    store.remove_category("web")
    assert permissions.decision("tab-1", "web", "github.com") == "allow"


def test_card_options_lead_with_always_for_low_risk_and_tab_for_high_risk():
    assert permissions.card_options(JIRA) == {"scopes": ["always", "tab"], "primary": "always"}
    assert permissions.card_options("browser") == {"scopes": ["always", "tab"], "primary": "tab"}
    assert permissions.card_options("nope") is None


def test_card_options_drop_always_when_policy_denies(deny_persistent):
    assert permissions.card_options(JIRA) == {"scopes": ["tab"], "primary": "tab"}


def test_registry_covers_the_gates():
    ids = {c.id for c in registry.known()}
    assert {"data:Outlook mail", "data:Jira", "data:Slack", "web", "browser", "schedule_task",
            "capability:code_runner", "capability:shell_runner"} <= ids
    assert len(ids) == len(registry.known())


@pytest.mark.parametrize("blob", [{"version": 99, "rules": []}, {"version": 1, "rules": "x"}, {"rules": []}])
def test_unreadable_store_means_no_rules_and_is_not_overwritten(blob):
    secure_store.set_json("permissions/rules", blob)
    assert permissions.decision("tab-1", JIRA) == "ask"
    with pytest.raises(RuntimeError):
        store.add(JIRA)
    assert secure_store.get_json("permissions/rules") == blob


def test_malformed_rules_are_dropped():
    secure_store.set_json("permissions/rules", {"version": 1, "rules": [
        {"id": "a", "category": JIRA, "subject": "", "created": 1.0},
        {"id": "b", "category": "", "subject": "", "created": 1.0},
        {"id": 3, "category": JIRA, "subject": "", "created": 1.0},
        {"id": "c", "category": JIRA, "subject": "", "created": True},
    ]})
    assert [r["id"] for r in store.list_rules()] == ["a"]


def test_add_is_idempotent():
    assert store.add(JIRA)["id"] == store.add(JIRA)["id"]
    assert len(store.list_rules()) == 1


def test_list_requires_no_rules_and_shows_categories(client):
    body = client.get("/api/permissions").json()
    assert body["persistent_allowed"] is True and body["rules"] == []
    by_id = {c["id"]: c for c in body["categories"]}
    assert by_id["browser"]["mode"] == "ask" and by_id["browser"]["card"]["primary"] == "tab"
    assert by_id["web"]["mode"] is None and by_id["web"]["subject_scoped"] is True


def test_mode_route_requires_csrf(client):
    r = client.post("/api/permissions/mode", json={"category": "browser", "mode": "always"})
    assert r.status_code == 403
    assert store.list_rules() == []


def test_mode_route_saves_and_clears(client, csrf):
    assert client.post("/api/permissions/mode", json={"category": "browser", "mode": "always"}, headers=csrf).status_code == 200
    body = client.get("/api/permissions").json()
    assert {c["id"]: c["mode"] for c in body["categories"]}["browser"] == "always"
    assert [r["label"] for r in body["rules"]] == ["Browser control"]
    assert client.post("/api/permissions/mode", json={"category": "browser", "mode": "ask"}, headers=csrf).status_code == 200
    assert client.get("/api/permissions").json()["rules"] == []


def test_mode_route_rejects_unknown_subject_scoped_and_bad_mode(client, csrf):
    for category in ("nope", "web"):
        r = client.post("/api/permissions/mode", json={"category": category, "mode": "always"}, headers=csrf)
        assert r.status_code == 404
    assert client.post("/api/permissions/mode", json={"category": "browser", "mode": "maybe"}, headers=csrf).status_code == 422


def test_mode_route_refused_when_policy_denies(client, csrf, deny_persistent):
    r = client.post("/api/permissions/mode", json={"category": "browser", "mode": "always"}, headers=csrf)
    assert r.status_code == 409
    assert client.get("/api/permissions").json()["persistent_allowed"] is False


def test_remove_routes_require_csrf_and_work(client, csrf):
    rule = permissions.remember("web", "github.com")
    permissions.remember("browser")
    assert client.delete(f"/api/permissions/rules/{rule['id']}").status_code == 403
    assert client.delete("/api/permissions/rules").status_code == 403
    assert client.delete(f"/api/permissions/rules/{rule['id']}", headers=csrf).status_code == 200
    assert client.delete(f"/api/permissions/rules/{rule['id']}", headers=csrf).status_code == 404
    assert len(store.list_rules()) == 1
    assert client.delete("/api/permissions/rules", headers=csrf).status_code == 200
    assert store.list_rules() == []


def test_a_rule_for_a_disconnected_mcp_server_stays_listed(client, csrf):
    permissions.remember("mcp:mcp-gone")
    body = client.get("/api/permissions").json()
    assert any(c["id"] == "mcp:mcp-gone" for c in body["categories"])
    assert [r["label"] for r in body["rules"]] == ["mcp-gone"]
