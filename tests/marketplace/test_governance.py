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


def test_default_tiers_show_community(tmp_path):
    _no_admin_policy(tmp_path)
    with (
        patch("routes.marketplace.fetch_catalog", return_value=CATALOG),
        patch(
            "routes.marketplace._load_config",
            return_value={"marketplace_enabled": True},
        ),
        patch("routes.marketplace._load_native_skills", return_value=[]),
    ):
        r = client.get("/api/marketplace/catalog")
    assert sorted(s["id"] for s in r.json()["skills"]) == ["gmail", "powerbi"]


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

_CSRF = {"X-CSRF-Token": get_csrf_token("testserver")}


def _no_admin_policy(tmp_path):
    (tmp_path / "sandbox-policy.json").unlink(missing_ok=True)
    _policy._reset_cache()


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


def test_default_allows_community_installs(tmp_path):
    _no_admin_policy(tmp_path)
    assert _install("gmail", {"marketplace_enabled": True}).status_code != 403


def test_admin_policy_can_block_community_installs(tmp_path):
    _admin_policy(tmp_path, {"marketplace_allowed_tiers": ["Native", "Verified", "Mine"]})
    r = _install("gmail", {"marketplace_enabled": True})
    assert r.status_code == 403
    assert "not allowed by policy" in r.json()["detail"]


def test_default_allows_verified_installs(tmp_path):
    _no_admin_policy(tmp_path)
    assert _install("powerbi", {"marketplace_enabled": True}).status_code != 403


def _install_local(cfg):
    import base64
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("s/SKILL.md", "---\nname: s\ndescription: d\n---\n\nbody\n")
    body = {"kind": "zip", "name": "s.zip", "b64": base64.b64encode(buf.getvalue()).decode()}
    with patch("routes.marketplace._load_config", return_value=cfg):
        return client.post("/api/marketplace/install-local", json=body, headers=_CSRF)


def test_default_allows_a_local_zip_import(tmp_path):
    _no_admin_policy(tmp_path)
    r = _install_local({"marketplace_enabled": True})
    assert r.status_code == 200 and r.json()["consent_required"] is True


def test_admin_policy_can_block_local_imports(tmp_path):
    _admin_policy(tmp_path, {"marketplace_allowed_tiers": ["Native", "Verified"]})
    r = _install_local({"marketplace_enabled": True})
    assert r.status_code == 403
    assert "not allowed by policy" in r.json()["detail"]


def test_admin_policy_can_enable_community(tmp_path):
    _admin_policy(tmp_path, {"marketplace_allowed_tiers": ["Native", "Verified", "Community"]})
    assert _install("gmail", {"marketplace_enabled": True}).status_code != 403


def test_user_config_can_narrow_the_default(tmp_path):
    _no_admin_policy(tmp_path)
    cfg = {"marketplace_enabled": True, "marketplace_allowed_tiers": ["Verified"]}
    assert _install("gmail", cfg).status_code == 403


def test_invalid_admin_tier_value_fails_closed(tmp_path):
    _admin_policy(tmp_path, {"marketplace_allowed_tiers": ["Everything"]})
    r = _install("gmail", {"marketplace_enabled": True})
    assert r.status_code == 403


def test_policy_parser_rejects_empty_and_non_list_tiers():
    import pytest

    for bad in ('{"marketplace_allowed_tiers": []}', '{"marketplace_allowed_tiers": "Verified"}'):
        with pytest.raises(ValueError):
            _policy.parse_policy(bad)


# ── pinned installs (M_11) ────────────────────────────────────────────────────

PLUGINS = [
    {"id": "pinned-plugin", "tier": "Verified", "source": "claude-plugins-official", "installable": True,
     "plugin_source": {"url": "https://github.com/o/r", "sha": "a" * 40}},
    {"id": "floating-plugin", "tier": "Verified", "source": "claude-plugins-official", "installable": True,
     "plugin_source": {"url": "https://github.com/o/r", "ref": "main"}},
]


def _install_plugin(entry_id):
    with (
        patch("routes.marketplace.fetch_catalog", return_value=PLUGINS + CATALOG),
        patch("routes.marketplace._load_config", return_value={"marketplace_enabled": True}),
        patch("routes.marketplace._install_claude_plugins_official", return_value={"ok": True}),
    ):
        return client.post("/api/marketplace/install", json={"skill_id": entry_id}, headers=_CSRF)


def test_pinned_policy_refuses_unpinned_plugin_and_url_import(tmp_path):
    _admin_policy(tmp_path, {"require_pinned_installs": True, "marketplace_allowed_tiers": ["Verified", "Community"]})
    assert _install_plugin("floating-plugin").status_code == 403
    r = _install("gmail", {"marketplace_enabled": True}, skill_md="", install_url="https://example.com/x.zip")
    assert r.status_code == 403
    assert "pinned" in r.json()["detail"]


def test_pinned_policy_allows_sha_pinned_plugin_and_pasted_skill_text(tmp_path):
    _admin_policy(tmp_path, {"require_pinned_installs": True, "marketplace_allowed_tiers": ["Verified", "Community"]})
    assert _install_plugin("pinned-plugin").status_code == 200
    assert _install("gmail", {"marketplace_enabled": True}).status_code != 403


def test_without_the_policy_unpinned_plugins_install():
    assert _install_plugin("floating-plugin").status_code == 200


def test_pinned_policy_must_be_a_boolean():
    import pytest

    with pytest.raises(ValueError):
        _policy.parse_policy('{"require_pinned_installs": "yes"}')


# ── install audit log (M_09) ──────────────────────────────────────────────────

def test_successful_install_is_written_to_the_audit_log(caplog):
    import logging

    with (
        patch("routes.marketplace.fetch_catalog", return_value=CATALOG),
        patch("routes.marketplace._load_config", return_value={"marketplace_enabled": True}),
        patch("routes.marketplace.install_skill_md", return_value={"ok": True, "skill_id": "gmail"}),
        patch("routes.marketplace._record_grants"),
        patch("routes.marketplace.load_installed_skill_prompts"),
        patch("routes.marketplace.load_skill_tools", return_value={"ok": True}),
        caplog.at_level(logging.INFO, logger="aigator.skill_audit"),
    ):
        r = client.post(
            "/api/marketplace/install",
            json={"skill_id": "gmail", "skill_md": "---\nname: x\n---\nbody", "consent": True, "digest": "abc123"},
            headers=_CSRF,
        )
    assert r.status_code == 200
    assert "skill-install skill=gmail tier=Community source=catalog digest=abc123" in caplog.text


# ── admin hash allow-list (M_11) ──────────────────────────────────────────────

_SKILL_MD = "---\nname: demo-skill\ndescription: d\n---\nBody\n"


def _digest_of_skill_md():
    from marketplace.permissions import files_digest

    return files_digest({"SKILL.md": _SKILL_MD.encode()})


def _install_inline(tmp_path, monkeypatch):
    from marketplace import installer

    monkeypatch.setattr(installer, "INSTALLED_SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(installer, "PLUGINS_DIR", tmp_path / "plugins")
    return installer.install_skill_md("demo-skill", _SKILL_MD, "1.0", "Community")


def test_without_an_allow_list_any_package_installs(tmp_path, monkeypatch):
    assert _install_inline(tmp_path, monkeypatch)["ok"] is True


def test_allow_list_blocks_a_package_that_is_not_listed(tmp_path, monkeypatch):
    _admin_policy(tmp_path, {"approved_digests": ["not-this-one"]})
    res = _install_inline(tmp_path, monkeypatch)
    assert res == {"ok": False, "error": "digest_not_approved", "digest": _digest_of_skill_md()}
    assert not (tmp_path / "skills").exists()


def test_an_empty_allow_list_blocks_every_download(tmp_path, monkeypatch):
    _admin_policy(tmp_path, {"approved_digests": []})
    assert _install_inline(tmp_path, monkeypatch)["error"] == "digest_not_approved"


def test_allow_list_lets_a_listed_package_install(tmp_path, monkeypatch):
    _admin_policy(tmp_path, {"approved_digests": [_digest_of_skill_md()]})
    assert _install_inline(tmp_path, monkeypatch)["ok"] is True


def test_blocked_install_tells_the_user_which_digest_to_ask_for():
    with (
        patch("routes.marketplace.fetch_catalog", return_value=CATALOG),
        patch("routes.marketplace._load_config", return_value={"marketplace_enabled": True}),
        patch("routes.marketplace.install_skill_md",
              return_value={"ok": False, "error": "digest_not_approved", "digest": "abc123"}),
    ):
        r = client.post(
            "/api/marketplace/install",
            json={"skill_id": "gmail", "skill_md": "---\nname: x\n---\nbody", "consent": True, "digest": "abc123"},
            headers=_CSRF,
        )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "digest_not_approved"
    assert "abc123" in r.json()["detail"]["message"]


def test_allow_list_must_be_a_list_of_strings():
    import pytest

    for bad in ('"abc"', "[1]", '[""]', "null"):
        with pytest.raises(ValueError):
            _policy.parse_policy('{"approved_digests": %s}' % bad)
    assert _policy.parse_policy('{"approved_digests": ["a"]}').approved_digests == ("a",)


# ── the server sets the tier (M_07) ───────────────────────────────────────────

def test_client_cannot_choose_the_tier_of_an_installed_skill():
    with (
        patch("routes.marketplace.fetch_catalog", return_value=CATALOG),
        patch("routes.marketplace._load_config", return_value={"marketplace_enabled": True}),
        patch("routes.marketplace.install_skill_md", return_value={"ok": True, "skill_id": "gmail"}) as install,
        patch("routes.marketplace._record_grants"),
        patch("routes.marketplace.load_installed_skill_prompts"),
        patch("routes.marketplace.load_skill_tools", return_value={"ok": True}) as load_tools,
    ):
        r = client.post(
            "/api/marketplace/install",
            json={"skill_id": "unlisted-skill", "skill_md": "---\nname: x\n---\nbody", "tier": "Native",
                  "consent": True, "digest": "abc123"},
            headers=_CSRF,
        )
    assert r.status_code == 200
    assert install.call_args.args[3] == "Community"
    assert load_tools.call_args.args[2] == "Community"
