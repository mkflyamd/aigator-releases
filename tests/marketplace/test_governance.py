import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "web"))

from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import patch
from routes.marketplace import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

CATALOG = [
    {
        "id": "powerbi",
        "name": "Power BI",
        "tier": "Verified",
        "description": "",
        "version": "1.0",
        "install_url": "",
        "install_count": 0,
        "category": "",
        "license": "",
        "has_tools": False,
        "source": "verified",
    },
    {
        "id": "gmail",
        "name": "Gmail",
        "tier": "Community",
        "description": "",
        "version": "1.0",
        "install_url": "",
        "install_count": 0,
        "category": "",
        "license": "",
        "has_tools": False,
        "source": "clawhub",
    },
]


def test_no_tier_filter_returns_all():
    with (
        patch("routes.marketplace.fetch_catalog", return_value=CATALOG),
        patch(
            "routes.marketplace._load_config",
            return_value={"marketplace_enabled": True},
        ),
        patch("routes.marketplace._load_native_skills", return_value=[]),
    ):
        r = client.get("/api/marketplace/catalog")
    assert r.json()["count"] == 2


def test_allowed_tiers_filters_community():
    cfg = {
        "marketplace_enabled": True,
        "marketplace_allowed_tiers": ["Native", "Verified"],
    }
    with (
        patch("routes.marketplace.fetch_catalog", return_value=CATALOG),
        patch("routes.marketplace._load_config", return_value=cfg),
        patch("routes.marketplace._load_native_skills", return_value=[]),
    ):
        r = client.get("/api/marketplace/catalog")
    data = r.json()
    assert data["count"] == 1
    assert data["skills"][0]["id"] == "powerbi"


def test_marketplace_disabled_returns_empty():
    with patch(
        "routes.marketplace._load_config", return_value={"marketplace_enabled": False}
    ):
        r = client.get("/api/marketplace/catalog")
    assert r.json()["skills"] == []
    assert r.json()["disabled"] is True


# ── admin policy enforcement (M_09) ───────────────────────────────────────────

import json

from sandbox import policy as _policy
from security import get_csrf_token

_CSRF = {"X-CSRF-Token": get_csrf_token()}


def _admin_policy(tmp_path, body):
    (tmp_path / "sandbox-policy.json").write_text(json.dumps(body), encoding="utf-8")
    _policy._reset_cache()


def _catalog_get(cfg):
    with (
        patch("routes.marketplace.fetch_catalog", return_value=CATALOG),
        patch("routes.marketplace._load_config", return_value=cfg),
        patch("routes.marketplace._load_native_skills", return_value=[]),
    ):
        return client.get("/api/marketplace/catalog").json()


def _install(entry_id, cfg, **body):
    with (
        patch("routes.marketplace.fetch_catalog", return_value=CATALOG),
        patch("routes.marketplace._load_config", return_value=cfg),
    ):
        return client.post(
            "/api/marketplace/install",
            json={"skill_id": entry_id, "skill_md": "---\nname: x\n---\nbody", **body},
            headers=_CSRF,
        )


def test_admin_policy_filters_catalog(tmp_path):
    _admin_policy(tmp_path, {"marketplace_allowed_tiers": ["Verified"]})
    assert [s["id"] for s in _catalog_get({"marketplace_enabled": True})["skills"]] == ["powerbi"]


def test_user_config_cannot_widen_admin_policy(tmp_path):
    _admin_policy(tmp_path, {"marketplace_allowed_tiers": ["Verified"]})
    cfg = {"marketplace_enabled": True, "marketplace_allowed_tiers": ["Verified", "Community"]}
    assert [s["id"] for s in _catalog_get(cfg)["skills"]] == ["powerbi"]


def test_install_of_a_blocked_tier_is_refused(tmp_path):
    _admin_policy(tmp_path, {"marketplace_allowed_tiers": ["Verified"]})
    r = _install("gmail", {"marketplace_enabled": True})
    assert r.status_code == 403
    assert "not allowed by policy" in r.json()["detail"]


def test_client_cannot_claim_a_higher_tier_to_get_past_the_gate(tmp_path):
    _admin_policy(tmp_path, {"marketplace_allowed_tiers": ["Verified"]})
    r = _install("gmail", {"marketplace_enabled": True}, tier="Verified")
    assert r.status_code == 403


def test_url_import_is_community_even_for_a_verified_id(tmp_path):
    _admin_policy(tmp_path, {"marketplace_allowed_tiers": ["Verified"]})
    r = _install("powerbi", {"marketplace_enabled": True}, skill_md="", install_url="https://example.com/evil.zip")
    assert r.status_code == 403


def test_allowed_tier_passes_the_gate(tmp_path):
    _admin_policy(tmp_path, {"marketplace_allowed_tiers": ["Verified"]})
    r = _install("powerbi", {"marketplace_enabled": True})
    assert r.status_code != 403


def test_no_policy_leaves_installs_unrestricted():
    assert _install("gmail", {"marketplace_enabled": True}).status_code != 403


def test_invalid_admin_tier_value_fails_closed(tmp_path):
    _admin_policy(tmp_path, {"marketplace_allowed_tiers": ["Everything"]})
    r = _install("gmail", {"marketplace_enabled": True})
    assert r.status_code == 403


def test_policy_parser_rejects_empty_and_non_list_tiers():
    import pytest

    for bad in ('{"marketplace_allowed_tiers": []}', '{"marketplace_allowed_tiers": "Verified"}'):
        with pytest.raises(ValueError):
            _policy.parse_policy(bad)
