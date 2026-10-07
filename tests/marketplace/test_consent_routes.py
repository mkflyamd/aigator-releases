import base64
import io
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marketplace import installer, state
from marketplace.permissions import files_digest
from routes.marketplace import router
from security import get_csrf_token

SKILL_MD = (
    "---\nname: demo-skill\ndescription: d\n"
    "permissions:\n  filesystem: []\n  network: [api.example.com]\n---\nBody\n"
)
SKILL_FILES = {"SKILL.md": SKILL_MD.encode()}


def _headers():
    return {"X-CSRF-Token": get_csrf_token()}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALLED_SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(installer, "PLUGINS_DIR", tmp_path / "plugins")
    app = FastAPI()
    app.include_router(router)
    with (
        patch("routes.marketplace.load_installed_skill_prompts") as prompts,
        patch("routes.marketplace.load_skill_tools") as load_tools,
        patch("routes.marketplace.fetch_catalog", return_value=[]),
    ):
        yield SimpleNamespace(
            client=TestClient(app),
            prompts=prompts,
            load_tools=load_tools,
            skills_dir=tmp_path / "skills",
        )


def _zip_b64(entries: dict[str, str]) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return base64.b64encode(buf.getvalue()).decode()


# ── CSRF ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/marketplace/install", "/api/marketplace/install-local"])
def test_install_routes_reject_a_missing_or_wrong_csrf_token(env, path):
    body = {"skill_id": "demo-skill", "skill_md": SKILL_MD, "kind": "zip", "name": "x"}
    assert env.client.post(path, json=body).status_code == 403
    assert env.client.post(path, json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert not env.skills_dir.exists()


# ── Plain skill: consent first, nothing written before it ────────────────────

def test_inline_skill_returns_a_summary_and_writes_nothing(env):
    r = env.client.post(
        "/api/marketplace/install",
        json={"skill_id": "demo-skill", "skill_md": SKILL_MD},
        headers=_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["consent_required"] is True
    assert body["skill_id"] == "demo-skill"
    assert body["summary"]["permissions"]["network"] == ["api.example.com"]
    assert body["summary"]["digest"] == files_digest(SKILL_FILES)
    assert any("api.example.com" in line for line in body["summary"]["lines"])
    assert not env.skills_dir.exists()
    assert installer.load_installed() == []
    env.load_tools.assert_not_called()


def test_consent_without_a_digest_is_refused(env):
    r = env.client.post(
        "/api/marketplace/install",
        json={"skill_id": "demo-skill", "skill_md": SKILL_MD, "consent": True},
        headers=_headers(),
    )
    assert r.status_code == 400
    assert "digest" in r.json()["detail"]
    assert not env.skills_dir.exists()


def test_a_digest_that_no_longer_matches_is_a_409_and_writes_nothing(env):
    r = env.client.post(
        "/api/marketplace/install",
        json={"skill_id": "demo-skill", "skill_md": SKILL_MD, "consent": True, "digest": "0" * 64},
        headers=_headers(),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "content_changed"
    assert not env.skills_dir.exists()
    assert installer.load_installed() == []


def test_consent_with_the_shown_digest_installs_and_records_the_grant(env):
    shown = env.client.post(
        "/api/marketplace/install",
        json={"skill_id": "demo-skill", "skill_md": SKILL_MD},
        headers=_headers(),
    ).json()["summary"]["digest"]

    seen_at_load = {}

    def _capture(skill_id, skill_dir, tier):
        seen_at_load["network"] = list(state.approved_permissions(skill_id).network)

    env.load_tools.side_effect = _capture

    r = env.client.post(
        "/api/marketplace/install",
        json={"skill_id": "demo-skill", "skill_md": SKILL_MD, "consent": True, "digest": shown},
        headers=_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    entry = state.get_entry("demo-skill")
    assert entry["permissions"] == {"filesystem": [], "network": ["api.example.com"], "invalid": False}
    assert entry["approved_at"]
    assert (env.skills_dir / "demo-skill" / "SKILL.md").exists()
    assert seen_at_load["network"] == ["api.example.com"]


def test_a_skill_with_no_declaration_is_recorded_with_no_grants(env):
    md = "---\nname: plain\ndescription: d\n---\nBody\n"
    digest = files_digest({"SKILL.md": md.encode()})
    r = env.client.post(
        "/api/marketplace/install",
        json={"skill_id": "plain", "skill_md": md, "consent": True, "digest": digest},
        headers=_headers(),
    )
    assert r.status_code == 200, r.text
    assert state.approved_permissions("plain").network == ()
    assert state.approved_permissions("plain").filesystem == ()


# ── Other plain paths ────────────────────────────────────────────────────────

def test_zip_url_returns_a_summary_without_installing(env):
    with patch(
        "marketplace.installer.preview_package",
        return_value={"ok": True, "files": SKILL_FILES},
    ) as preview:
        r = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "demo-skill", "install_url": "https://example.com/demo.zip"},
            headers=_headers(),
        )
    assert r.status_code == 200
    assert r.json()["consent_required"] is True
    assert r.json()["summary"]["digest"] == files_digest(SKILL_FILES)
    preview.assert_called_once_with(skill_md="", install_url="https://example.com/demo.zip")
    assert not env.skills_dir.exists()


def test_a_package_that_cannot_be_read_is_a_400(env):
    with patch(
        "marketplace.installer.preview_package",
        return_value={"ok": False, "error": "Could not download the file"},
    ):
        r = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "demo-skill", "install_url": "https://example.com/demo.zip"},
            headers=_headers(),
        )
    assert r.status_code == 400
    assert "Could not download" in r.json()["detail"]


def test_github_folder_plain_skill_consent_uses_the_fetched_package(env):
    caps = {"ok": True, "is_plugin": False, "skill_id": "demo-skill", "package": SKILL_FILES}
    with patch("marketplace.installer.get_github_url_capabilities", return_value=caps), patch(
        "marketplace.installer.install_github_url"
    ) as install:
        r = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "demo-skill", "install_url": "https://github.com/o/r/tree/main/demo"},
            headers=_headers(),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["consent_required"] is True and body["skill_id"] == "demo-skill"
    assert body["summary"]["digest"] == files_digest(SKILL_FILES)
    assert "package" not in str(body)
    install.assert_not_called()


def test_github_folder_bundle_consent_carries_capabilities_and_summary(env):
    caps = {
        "ok": True, "is_plugin": True, "skill_id": "my-bundle", "skill_count": 1,
        "command_count": 0, "has_mcp": False, "has_local_code": False,
        "mcp_servers": [], "has_compat_risk": False, "package": SKILL_FILES,
    }
    with patch("marketplace.installer.get_github_url_capabilities", return_value=caps):
        r = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "my-bundle", "install_url": "https://github.com/o/r/tree/main/b"},
            headers=_headers(),
        )
    body = r.json()
    assert body["consent_required"] is True and body["plugin_id"] == "my-bundle"
    assert body["capabilities"]["skill_count"] == 1
    assert body["summary"]["digest"] == files_digest(SKILL_FILES)


def test_github_folder_consent_dispatches_with_the_digest_and_records_the_grant(env):
    perms = {"filesystem": [], "network": [], "invalid": False}
    result = {"ok": True, "skill_id": "demo-skill", "permissions": perms}
    installer.save_installed([{"id": "demo-skill", "version": "1.0", "tier": "Community"}])
    with patch("marketplace.installer.install_github_url", return_value=result) as install:
        r = env.client.post(
            "/api/marketplace/install",
            json={
                "skill_id": "demo-skill",
                "install_url": "https://github.com/o/r/tree/main/demo",
                "consent": True,
                "digest": "d1",
                "orphan_resolution": "keep",
            },
            headers=_headers(),
        )
    assert r.status_code == 200, r.text
    install.assert_called_once_with(
        "https://github.com/o/r/tree/main/demo", "demo-skill", "1.0",
        orphan_resolution="keep", expected_digest="d1",
    )
    assert state.get_entry("demo-skill")["permissions"] == perms


def test_github_folder_content_changed_is_a_409(env):
    with patch(
        "marketplace.installer.install_github_url",
        return_value={"ok": False, "error": "content_changed"},
    ):
        r = env.client.post(
            "/api/marketplace/install",
            json={
                "skill_id": "demo-skill",
                "install_url": "https://github.com/o/r/tree/main/demo",
                "consent": True,
                "digest": "d1",
            },
            headers=_headers(),
        )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "content_changed"


def test_orphan_resolution_is_still_a_400_with_the_orphan_list(env):
    with patch(
        "marketplace.installer.install_github_url",
        return_value={"ok": False, "error": "orphan_resolution_required", "orphans": ["old.txt"]},
    ):
        r = env.client.post(
            "/api/marketplace/install",
            json={
                "skill_id": "demo-skill",
                "install_url": "https://github.com/o/r/tree/main/demo",
                "consent": True,
                "digest": "d1",
            },
            headers=_headers(),
        )
    assert r.status_code == 400
    assert r.json()["detail"]["orphans"] == ["old.txt"]


# ── Catalog plugin ───────────────────────────────────────────────────────────

_CPO = {
    "id": "amd-skills", "name": "amd-skills", "tier": "Verified",
    "source": "claude-plugins-official", "installable": True, "coding_class": "none",
}


def test_catalog_plugin_consent_carries_a_summary_and_no_package_bytes(env):
    caps = {
        "ok": True, "plugin_id": "amd-skills", "skill_count": 1, "has_mcp": False,
        "has_local_code": False, "mcp_servers": [], "package": SKILL_FILES,
    }
    with patch("routes.marketplace.fetch_catalog", return_value=[_CPO]), patch(
        "marketplace.installer.get_claude_plugins_official_capabilities", return_value=caps
    ):
        r = env.client.post(
            "/api/marketplace/install", json={"skill_id": "amd-skills"}, headers=_headers()
        )
    body = r.json()
    assert r.status_code == 200
    assert body["summary"]["digest"] == files_digest(SKILL_FILES)
    assert "package" not in body and "package" not in body["capabilities"]


def test_catalog_plugin_consent_requires_the_digest_and_passes_it_through(env):
    result = {"ok": True, "plugin_id": "amd-skills", "skill_ids": [], "permissions": {"filesystem": [], "network": [], "invalid": False}}
    with patch("routes.marketplace.fetch_catalog", return_value=[_CPO]), patch(
        "marketplace.installer.install_claude_plugins_official_plugin", return_value=result
    ) as install:
        missing = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "amd-skills", "consent": True},
            headers=_headers(),
        )
        ok = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "amd-skills", "consent": True, "digest": "d1", "pinned_ref": "abc"},
            headers=_headers(),
        )
    assert missing.status_code == 400
    assert ok.status_code == 200, ok.text
    install.assert_called_once()
    kwargs = install.call_args.kwargs
    assert kwargs["consented"] is True
    assert kwargs["pinned_ref"] == "abc"
    assert kwargs["expected_digest"] == "d1"


def test_catalog_plugin_content_changed_is_a_409(env):
    with patch("routes.marketplace.fetch_catalog", return_value=[_CPO]), patch(
        "marketplace.installer.install_claude_plugins_official_plugin",
        return_value={"ok": False, "error": "content_changed"},
    ):
        r = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "amd-skills", "consent": True, "digest": "d1"},
            headers=_headers(),
        )
    assert r.status_code == 409


# ── Local install ────────────────────────────────────────────────────────────

def test_local_zip_returns_a_summary_then_installs_with_the_digest(env):
    b64 = _zip_b64({"local-skill/SKILL.md": SKILL_MD})
    first = env.client.post(
        "/api/marketplace/install-local",
        json={"kind": "zip", "name": "local-skill.zip", "b64": b64},
        headers=_headers(),
    )
    assert first.status_code == 200
    body = first.json()
    assert body["consent_required"] is True and body["skill_id"] == ""
    assert body["summary"]["permissions"]["network"] == ["api.example.com"]
    assert not env.skills_dir.exists()
    env.load_tools.assert_not_called()

    second = env.client.post(
        "/api/marketplace/install-local",
        json={
            "kind": "zip", "name": "local-skill.zip", "b64": b64,
            "consent": True, "digest": body["summary"]["digest"],
        },
        headers=_headers(),
    )
    assert second.status_code == 200, second.text
    skill_id = second.json()["skill_id"]
    assert state.get_entry(skill_id)["permissions"]["network"] == ["api.example.com"]
    env.load_tools.assert_called_once()


def test_local_install_consent_without_a_digest_is_refused(env):
    r = env.client.post(
        "/api/marketplace/install-local",
        json={"kind": "zip", "name": "x.zip", "b64": _zip_b64({"s/SKILL.md": SKILL_MD}), "consent": True},
        headers=_headers(),
    )
    assert r.status_code == 400
    assert not env.skills_dir.exists()


def test_local_install_with_a_stale_digest_is_a_409(env):
    r = env.client.post(
        "/api/marketplace/install-local",
        json={
            "kind": "zip", "name": "x.zip", "b64": _zip_b64({"s/SKILL.md": SKILL_MD}),
            "consent": True, "digest": "0" * 64,
        },
        headers=_headers(),
    )
    assert r.status_code == 409
    assert not env.skills_dir.exists()
