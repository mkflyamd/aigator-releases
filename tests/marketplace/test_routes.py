import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "web"))

from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import patch
from routes.marketplace import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

SAMPLE_SKILL = {
    "id": "powerbi",
    "name": "Power BI",
    "tier": "Verified",
    "description": "Read reports",
    "version": "1.0",
    "install_url": "",
    "install_count": 0,
    "category": "Productivity",
    "license": "MIT",
    "has_tools": False,
    "source": "verified",
}


def test_get_catalog_returns_list():
    with (
        patch("routes.marketplace.fetch_catalog", return_value=[SAMPLE_SKILL]),
        patch(
            "routes.marketplace._load_config",
            return_value={"marketplace_enabled": True},
        ),
        patch("routes.marketplace._load_native_skills", return_value=[]),
    ):
        r = client.get("/api/marketplace/catalog")
    assert r.status_code == 200
    assert r.json()["skills"][0]["id"] == "powerbi"


def test_get_installed_returns_list():
    with (
        patch("routes.marketplace.load_installed", return_value=[]),
        patch("routes.marketplace._load_native_skills", return_value=[]),
    ):
        r = client.get("/api/marketplace/installed")
    assert r.status_code == 200
    assert r.json()["skills"] == []


def test_install_requires_content():
    r = client.post(
        "/api/marketplace/install",
        json={"skill_id": "x", "skill_md": "", "install_url": ""},
    )
    assert r.status_code == 400


def test_create_skill():
    with patch(
        "routes.marketplace.create_user_skill",
        return_value={"ok": True, "skill_id": "my-wf"},
    ):
        r = client.post(
            "/api/marketplace/create",
            json={"name": "My WF", "description": "desc", "instructions": "do X"},
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_uninstall_skill():
    with patch(
        "routes.marketplace.uninstall_skill",
        return_value={"ok": True, "skill_id": "powerbi"},
    ):
        r = client.delete("/api/marketplace/uninstall/powerbi")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_marketplace_disabled():
    with patch(
        "routes.marketplace._load_config", return_value={"marketplace_enabled": False}
    ):
        r = client.get("/api/marketplace/catalog")
    assert r.json()["disabled"] is True
    assert r.json()["skills"] == []


# ── Increment 2, item 1+2: claude-plugins-official install routing +
# server-side consent gate (decisions #3/#4/#7/#8) ─────────────────────────

_CPO_ENTRY = {
    "id": "amd-skills",
    "name": "amd-skills",
    "tier": "Verified",
    "source": "claude-plugins-official",
    "installable": True,
    "coding_class": "none",
    "install_url": "https://github.com/amd/skills.git",
    "plugin_source": {
        "kind": "git-subdir",
        "url": "https://github.com/amd/skills.git",
        "path": "skills",
        "ref": "main",
        "sha": "37d424162b9fe1b55f8665fb1e82d47e670e7385",
    },
}

_CPO_LSP_ENTRY = {
    **_CPO_ENTRY,
    "id": "clangd-lsp",
    "name": "clangd-lsp",
    "installable": False,
    "coding_class": "coding_hard",
}


def test_install_routes_claude_plugins_official_entry_to_plugin_installer():
    """A source=="claude-plugins-official" catalog entry must go through
    install_claude_plugins_official_plugin, never install_skill_md /
    _install_github_folder (Increment 1 review: those corrupt-install it)."""
    with (
        patch("routes.marketplace.fetch_catalog", return_value=[_CPO_ENTRY]),
        patch(
            "marketplace.installer.install_claude_plugins_official_plugin",
            return_value={
                "ok": True,
                "plugin_id": "amd-skills",
                "skill_ids": ["amd-skills__a"],
            },
        ) as mock_install,
        patch("routes.marketplace.load_installed_skill_prompts"),
        patch("routes.marketplace.install_skill_md") as mock_legacy_install,
    ):
        r = client.post(
            "/api/marketplace/install", json={"skill_id": "amd-skills", "consent": True}
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    mock_install.assert_called_once()
    mock_legacy_install.assert_not_called()


def test_install_without_consent_is_refused_and_returns_capabilities():
    """No consent=true -> refused, capability summary returned, nothing
    installed (decision #7)."""
    caps = {
        "ok": True,
        "plugin_id": "amd-skills",
        "skill_count": 2,
        "has_mcp": False,
        "has_local_code": True,
        "mcp_servers": [],
    }
    with (
        patch("routes.marketplace.fetch_catalog", return_value=[_CPO_ENTRY]),
        patch(
            "marketplace.installer.get_claude_plugins_official_capabilities",
            return_value=caps,
        ),
        patch(
            "marketplace.installer.install_claude_plugins_official_plugin"
        ) as mock_install,
    ):
        r = client.post("/api/marketplace/install", json={"skill_id": "amd-skills"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["consent_required"] is True
    assert body["capabilities"] == {
        "skill_count": 2,
        "has_mcp": False,
        "has_local_code": True,
        "mcp_servers": [],
    }
    mock_install.assert_not_called()


def test_install_with_consent_true_installs_and_threads_consented():
    with (
        patch("routes.marketplace.fetch_catalog", return_value=[_CPO_ENTRY]),
        patch(
            "marketplace.installer.install_claude_plugins_official_plugin",
            return_value={"ok": True, "plugin_id": "amd-skills", "skill_ids": []},
        ) as mock_install,
        patch("routes.marketplace.load_installed_skill_prompts"),
    ):
        r = client.post(
            "/api/marketplace/install", json={"skill_id": "amd-skills", "consent": True}
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    mock_install.assert_called_once()
    _, kwargs = mock_install.call_args
    assert kwargs.get("consented") is True


def test_install_response_enriches_commands_from_registry():
    """Decision #12 (2026-08-07 milestone, Increment 4b): a successful
    claude-plugins-official install response must enrich its command_ids
    (already on the install record per decision #11/Increment 2) into full
    {name, description, plugin_id} objects — read from COMMAND_REGISTRY —
    so the frontend can call window.registerPluginCommand() per command
    without a second round-trip."""
    with (
        patch("routes.marketplace.fetch_catalog", return_value=[_CPO_ENTRY]),
        patch(
            "marketplace.installer.install_claude_plugins_official_plugin",
            return_value={
                "ok": True,
                "plugin_id": "amd-skills",
                "command_ids": ["standup"],
            },
        ),
        patch("routes.marketplace.load_installed_skill_prompts"),
        patch(
            "routes.marketplace.COMMAND_REGISTRY",
            {
                "standup": {
                    "body": "...",
                    "description": "Daily standup template",
                    "plugin_id": "amd-skills",
                }
            },
        ),
    ):
        r = client.post(
            "/api/marketplace/install", json={"skill_id": "amd-skills", "consent": True}
        )
    assert r.status_code == 200
    assert r.json()["commands"] == [
        {
            "name": "standup",
            "description": "Daily standup template",
            "plugin_id": "amd-skills",
        }
    ]


def test_install_response_commands_empty_when_no_command_ids():
    """A plugin with no commands must return an empty list, not omit the key
    or error — keeps the frontend's `Array.isArray(body.commands)` check
    from needing a null-guard."""
    with (
        patch("routes.marketplace.fetch_catalog", return_value=[_CPO_ENTRY]),
        patch(
            "marketplace.installer.install_claude_plugins_official_plugin",
            return_value={"ok": True, "plugin_id": "amd-skills"},
        ),
        patch("routes.marketplace.load_installed_skill_prompts"),
    ):
        r = client.post(
            "/api/marketplace/install", json={"skill_id": "amd-skills", "consent": True}
        )
    assert r.status_code == 200
    assert r.json()["commands"] == []


# ── Command discovery (decision #12, 2026-08-07 milestone, Increment 4b) ──


def test_list_commands_endpoint():
    fake_registry = {
        "standup": {
            "body": "...",
            "description": "Daily standup template",
            "plugin_id": "amd-skills",
        },
        "review": {"body": "...", "description": "", "plugin_id": "code-review"},
    }
    with patch("routes.marketplace.COMMAND_REGISTRY", fake_registry):
        r = client.get("/api/marketplace/commands")
    assert r.status_code == 200
    assert r.json()["commands"] == [
        {"name": "review", "description": "", "plugin_id": "code-review"},
        {
            "name": "standup",
            "description": "Daily standup template",
            "plugin_id": "amd-skills",
        },
    ]


def test_list_commands_endpoint_empty():
    with patch("routes.marketplace.COMMAND_REGISTRY", {}):
        r = client.get("/api/marketplace/commands")
    assert r.status_code == 200
    assert r.json() == {"commands": []}


def test_install_coding_hard_entry_refused_regardless_of_consent():
    """decision #8: installable=False (LSP / coding_hard) entries must be
    refused even when the caller passes consent=true."""
    with (
        patch("routes.marketplace.fetch_catalog", return_value=[_CPO_LSP_ENTRY]),
        patch(
            "marketplace.installer.install_claude_plugins_official_plugin"
        ) as mock_install,
        patch(
            "marketplace.installer.get_claude_plugins_official_capabilities"
        ) as mock_caps,
    ):
        r = client.post(
            "/api/marketplace/install", json={"skill_id": "clangd-lsp", "consent": True}
        )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_installable"
    assert "Coding Agent" in r.json()["detail"]["message"]
    mock_install.assert_not_called()
    mock_caps.assert_not_called()


def test_install_entry_missing_installable_key_is_refused():
    """Fix #3 (2026-08-07 milestone adversarial review): a catalog entry with
    no `installable` key at all (stale cache, future schema drift) must
    fail CLOSED — refused, not silently treated as installable via a
    fail-open default."""
    entry_no_installable = {k: v for k, v in _CPO_ENTRY.items() if k != "installable"}
    with (
        patch("routes.marketplace.fetch_catalog", return_value=[entry_no_installable]),
        patch(
            "marketplace.installer.install_claude_plugins_official_plugin"
        ) as mock_install,
        patch(
            "marketplace.installer.get_claude_plugins_official_capabilities"
        ) as mock_caps,
    ):
        r = client.post(
            "/api/marketplace/install", json={"skill_id": "amd-skills", "consent": True}
        )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_installable"
    mock_install.assert_not_called()
    mock_caps.assert_not_called()


def test_install_non_claude_plugins_official_entry_unaffected():
    """A catalog entry with a different source must still go through the
    existing install_skill_md path — the new routing must not disrupt any
    other install path."""
    other_entry = {"id": "powerbi", "source": "verified"}
    with (
        patch("routes.marketplace.fetch_catalog", return_value=[other_entry]),
        patch(
            "routes.marketplace.install_skill_md",
            return_value={"ok": True, "skill_id": "powerbi"},
        ) as mock_legacy,
        patch("routes.marketplace.load_installed_skill_prompts"),
        patch("routes.marketplace.load_skill_tools"),
    ):
        r = client.post(
            "/api/marketplace/install",
            json={"skill_id": "powerbi", "skill_md": "---\nname: x\n---\nbody"},
        )
    assert r.status_code == 200
    mock_legacy.assert_called_once()


# ── Cleanup #7 (2026-08-07 milestone adversarial review) — real two-call
# consent hand-off, against the ACTUAL installer (not mocked at both steps),
# to catch a regression where each call's response shape is individually
# correct but the state hand-off between them is broken. ──────────────────


def test_preview_then_consent_install_real_state_handoff(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path)
    monkeypatch.setattr(
        "marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path / "skills"
    )
    import importlib
    import marketplace.installer as m

    importlib.reload(m)

    files = {"skills/a/SKILL.md": b"---\nname: a\nversion: 1.0\n---\nDo a."}

    with (
        patch.object(m.github_fetcher, "download_skill_tarball", return_value=files),
        patch("routes.marketplace.fetch_catalog", return_value=[_CPO_ENTRY]),
        patch("routes.marketplace.load_installed_skill_prompts"),
    ):
        # Call 1: no consent -> preview-only. Nothing installed, no files on disk.
        r1 = client.post("/api/marketplace/install", json={"skill_id": "amd-skills"})
        assert r1.status_code == 200
        body1 = r1.json()
        assert body1["ok"] is False
        assert body1["consent_required"] is True
        resolved_ref = body1["resolved_ref"]
        assert resolved_ref == _CPO_ENTRY["plugin_source"]["sha"]

        assert not any(e.get("id") == "amd-skills" for e in m.load_installed())
        plugin_root = tmp_path / "cache" / "claude-plugins-official" / "amd-skills"
        assert not plugin_root.exists()

        # Call 2: consent=True + the pinned_ref echoed back from call 1 ->
        # real install against the actual installer.
        r2 = client.post(
            "/api/marketplace/install",
            json={
                "skill_id": "amd-skills",
                "consent": True,
                "pinned_ref": resolved_ref,
            },
        )
        assert r2.status_code == 200
        assert r2.json()["ok"] is True

    installed = m.load_installed()
    entry = next((e for e in installed if e.get("id") == "amd-skills"), None)
    assert entry is not None
    assert (plugin_root / "1.0" / "skills" / "a" / "SKILL.md").exists()
