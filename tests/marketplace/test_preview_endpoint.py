import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "web"))

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from routes.marketplace import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Preview endpoint tests (P1 MVP: now calls get_github_url_capabilities)
# ---------------------------------------------------------------------------


def _fake_caps(**overrides):
    """Build a minimal get_github_url_capabilities return value."""
    base = {
        "ok": True,
        "is_plugin": False,
        "skill_id": "docx",
        "name": "docx",
        "description": "edit Word",
        "skill_count": 1,
        "command_count": 0,
        "has_mcp": False,
        "has_local_code": False,
        "mcp_servers": [],
        "has_compat_risk": False,
        "files_count": 2,
        "total_size": 400,
    }
    base.update(overrides)
    return base


def test_preview_returns_manifest(tmp_path, monkeypatch):
    import config, marketplace.installer as inst
    monkeypatch.setattr(config, "INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)

    with patch(
        "marketplace.installer.get_github_url_capabilities",
        return_value=_fake_caps(skill_id="docx", name="docx", description="edit Word",
                                files_count=2, total_size=400),
    ):
        r = _client().post(
            "/api/marketplace/preview",
            json={"url": "https://github.com/f/b/tree/m/skills/docx"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["skill_id"] == "docx"
    assert body["name"] == "docx"
    assert body["description"] == "edit Word"
    assert body["total_size"] == 400
    assert body["files_count"] == 2
    assert body["existing_files"] == []
    assert body["orphans"] == []
    assert body["is_plugin"] is False


def test_preview_rejects_bad_url():
    r = _client().post(
        "/api/marketplace/preview", json={"url": "https://gitlab.com/foo/bar"}
    )
    assert r.status_code == 400
    assert "Unsupported URL" in r.json()["detail"]


def test_preview_reports_overwrite(tmp_path, monkeypatch):
    import config, marketplace.installer as inst
    monkeypatch.setattr(config, "INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)
    import importlib; importlib.reload(inst)
    inst.install_skill_md("docx", "---\nname: docx\n---\n", "1.0", "Community")

    with patch(
        "marketplace.installer.get_github_url_capabilities",
        return_value=_fake_caps(skill_id="docx"),
    ):
        r = _client().post(
            "/api/marketplace/preview",
            json={"url": "https://github.com/f/b/tree/m/docx"},
        )
    assert r.status_code == 200
    assert "overwrite" in r.json()["warnings"]


def test_preview_rejects_missing_skill_md():
    """get_github_url_capabilities returns error when no SKILL.md."""
    with patch(
        "marketplace.installer.get_github_url_capabilities",
        return_value={"ok": False, "error": "No SKILL.md found at this URL"},
    ):
        r = _client().post(
            "/api/marketplace/preview",
            json={"url": "https://github.com/f/b/tree/m/skills/docx"},
        )
    assert r.status_code == 400
    assert "SKILL.md" in r.json()["detail"]


def test_preview_returns_plugin_flags_for_bundle(tmp_path, monkeypatch):
    """Preview of a plugin bundle returns is_plugin=True and capability fields."""
    import config, marketplace.installer as inst
    monkeypatch.setattr(config, "INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)

    with patch(
        "marketplace.installer.get_github_url_capabilities",
        return_value=_fake_caps(
            is_plugin=True, has_mcp=True, skill_count=3, command_count=2,
            mcp_servers=[{"name": "my-mcp", "needs_secrets": ["TOKEN"]}],
        ),
    ):
        r = _client().post(
            "/api/marketplace/preview",
            json={"url": "https://github.com/owner/repo/tree/main/my-plugin"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["is_plugin"] is True
    assert body["has_mcp"] is True
    assert body["skill_count"] == 3
    assert body["command_count"] == 2
    assert len(body["mcp_servers"]) == 1


def test_preview_returns_orphans_for_reinstall(monkeypatch, tmp_path):
    """Preview of a re-import returns existing_files correctly."""
    import marketplace.installer as inst, config
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr(config, "INSTALLED_SKILLS_DIR", tmp_path)

    skill_dir = tmp_path / "foo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: foo\n---\n")
    (skill_dir / "helpers.py").write_text("old")
    inst.save_installed([{"id": "foo", "version": "1.0", "tier": "Community"}])

    with patch(
        "marketplace.installer.get_github_url_capabilities",
        return_value=_fake_caps(skill_id="foo", name="foo"),
    ):
        resp = _client().post(
            "/api/marketplace/preview",
            json={"url": "https://github.com/owner/repo/tree/main/skills/foo"},
        )
    body = resp.json()
    assert resp.status_code == 200
    assert sorted(body["existing_files"]) == ["SKILL.md", "helpers.py"]


def test_preview_first_install_has_empty_existing_files(monkeypatch, tmp_path):
    import marketplace.installer as inst, config
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr(config, "INSTALLED_SKILLS_DIR", tmp_path)

    with patch(
        "marketplace.installer.get_github_url_capabilities",
        return_value=_fake_caps(skill_id="foo", name="foo"),
    ):
        resp = _client().post(
            "/api/marketplace/preview",
            json={"url": "https://github.com/owner/repo/tree/main/skills/foo"},
        )
    body = resp.json()
    assert body["existing_files"] == []
    assert body["orphans"] == []


# ---------------------------------------------------------------------------
# Install endpoint tests — standalone skill path (no consent, no MCP)
# ---------------------------------------------------------------------------


def test_install_standalone_skill_no_consent_routes_to_folder_installer(tmp_path, monkeypatch):
    """A GitHub tree URL with no MCP/commands and no consent still uses
    _install_github_folder (standalone skill path)."""
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)

    # get_github_url_capabilities returns is_plugin=False → standalone path
    with (
        patch(
            "marketplace.installer.get_github_url_capabilities",
            return_value=_fake_caps(is_plugin=False),
        ),
        patch(
            "marketplace.installer._install_github_folder",
            return_value={"ok": True, "skill_id": "docx"},
        ) as fake_inst,
    ):
        r = _client().post(
            "/api/marketplace/install",
            json={
                "skill_id": "docx",
                "install_url": "https://github.com/foo/bar/tree/main/skills/docx",
            },
        )
    assert r.status_code == 200
    fake_inst.assert_called_once()


def test_install_plugin_bundle_without_consent_returns_consent_required(tmp_path, monkeypatch):
    """A GitHub tree URL with MCP/commands and no consent returns consent_required."""
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)

    with patch(
        "marketplace.installer.get_github_url_capabilities",
        return_value=_fake_caps(is_plugin=True, has_mcp=True,
                                mcp_servers=[{"name": "s", "needs_secrets": []}]),
    ):
        r = _client().post(
            "/api/marketplace/install",
            json={
                "skill_id": "my-plugin",
                "install_url": "https://github.com/owner/repo/tree/main/my-plugin",
                "consent": False,
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["consent_required"] is True
    assert body["capabilities"]["has_mcp"] is True


def test_install_plugin_bundle_with_consent_calls_url_plugin_installer(tmp_path, monkeypatch):
    """A GitHub tree URL with consent=True routes to install_github_url_plugin."""
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)

    with patch(
        "marketplace.installer.install_github_url_plugin",
        return_value={
            "ok": True,
            "plugin_id": "my-plugin",
            "path": str(tmp_path),
            "skill_ids": ["my-plugin"],
            "command_ids": [],
            "mcp_connection_ids": [],
            "mcp_compatibility_warnings": [],
        },
    ) as fake_inst:
        r = _client().post(
            "/api/marketplace/install",
            json={
                "skill_id": "my-plugin",
                "install_url": "https://github.com/owner/repo/tree/main/my-plugin",
                "consent": True,
            },
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    fake_inst.assert_called_once_with(
        "https://github.com/owner/repo/tree/main/my-plugin",
        "my-plugin",
        consented=True,
    )


def test_install_orphan_resolution_passed_to_folder_installer(monkeypatch, tmp_path):
    """orphan_resolution is forwarded to _install_github_folder for standalone skills."""
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)
    captured = {}

    def fake_install(install_url, skill_id, version="1.0", orphan_resolution=None):
        captured["orphan_resolution"] = orphan_resolution
        return {"ok": True, "skill_id": skill_id}

    with (
        patch("marketplace.installer.get_github_url_capabilities",
              return_value=_fake_caps(is_plugin=False)),
        patch("marketplace.installer._install_github_folder", side_effect=fake_install),
    ):
        resp = _client().post(
            "/api/marketplace/install",
            json={
                "skill_id": "foo",
                "install_url": "https://github.com/owner/repo/tree/main/skills/foo",
                "orphan_resolution": "delete",
            },
        )
    assert resp.status_code == 200
    assert captured["orphan_resolution"] == "delete"
