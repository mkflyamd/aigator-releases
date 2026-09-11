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
        "command_count": 0,
        "has_mcp": False,
        "has_local_code": True,
        "mcp_servers": [],
        "has_compat_risk": False,
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


# ---------------------------------------------------------------------------
# P0 — _enrich_plugin_bundle_mcp_state: installed MCP state enrichment
# ---------------------------------------------------------------------------


def test_get_installed_enriches_plugin_bundle_with_mcp_status():
    """Plugin bundle entries in the installed list must include mcp_status
    derived from the live MCP connection state (not from consented)."""
    bundle_entry = {
        "id": "slack",
        "source": "claude-plugins-official",
        "tier": "Verified",
        "mcp_connection_ids": ["plugin:slack:slack"],
        "consented": True,
        "skill_ids": ["slack"],
        "version": "1.0",
    }
    live_connections = [
        {
            "id": "plugin:slack:slack",
            "name": "slack",
            "enabled": False,
            "missing_secrets": ["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
            "tool_compatibility": {"quarantined": 0},
        }
    ]
    with (
        patch("routes.marketplace.load_installed", return_value=[bundle_entry]),
        patch("routes.marketplace._load_native_skills", return_value=[]),
        patch("mcp.manager.list_with_status", return_value=live_connections),
    ):
        r = client.get("/api/marketplace/installed")
    assert r.status_code == 200
    skills = r.json()["skills"]
    slack = next((s for s in skills if s["id"] == "slack"), None)
    assert slack is not None
    mcp_status = slack.get("mcp_status")
    assert mcp_status is not None, "mcp_status must be present on plugin bundle"
    assert mcp_status["total"] == 1
    assert mcp_status["pending"] == 1
    assert mcp_status["enabled"] == 0


def test_get_installed_enriches_url_plugin_bundle_with_mcp_status():
    """A URL-imported bundle is identified by skill_ids, not its source."""
    bundle_entry = {
        "id": "my-url-bundle",
        "source": "url",
        "tier": "Unverified",
        "skill_ids": ["my-url-bundle__skill"],
        "mcp_connection_ids": ["plugin:my-url-bundle:mcp"],
    }
    live_connections = [{
        "id": "plugin:my-url-bundle:mcp",
        "enabled": True,
        "tool_compatibility": {"quarantined": 0},
    }]
    with (
        patch("routes.marketplace.load_installed", return_value=[bundle_entry]),
        patch("routes.marketplace._load_native_skills", return_value=[]),
        patch("mcp.manager.list_with_status", return_value=live_connections),
    ):
        response = client.get("/api/marketplace/installed")

    entry = response.json()["skills"][0]
    assert entry["source"] == "url"
    assert entry["mcp_status"]["enabled"] == 1


def test_get_installed_mcp_status_healthy_when_all_enabled():
    """A plugin with all MCP connections enabled and no secrets/errors shows healthy state."""
    bundle_entry = {
        "id": "datadog",
        "source": "claude-plugins-official",
        "tier": "Verified",
        "mcp_connection_ids": ["plugin:datadog:mcp"],
        "consented": True,
        "skill_ids": ["datadog"],
        "version": "1.0",
    }
    live_connections = [
        {
            "id": "plugin:datadog:mcp",
            "name": "mcp",
            "enabled": True,
            "tool_compatibility": {"quarantined": 0},
        }
    ]
    with (
        patch("routes.marketplace.load_installed", return_value=[bundle_entry]),
        patch("routes.marketplace._load_native_skills", return_value=[]),
        patch("mcp.manager.list_with_status", return_value=live_connections),
    ):
        r = client.get("/api/marketplace/installed")
    assert r.status_code == 200
    skills = r.json()["skills"]
    dd = next((s for s in skills if s["id"] == "datadog"), None)
    assert dd is not None
    mcp_status = dd.get("mcp_status")
    assert mcp_status is not None
    assert mcp_status["total"] == 1
    assert mcp_status["enabled"] == 1
    assert mcp_status["pending"] == 0
    assert mcp_status["failed"] == 0


def test_get_installed_standalone_skill_has_no_mcp_status():
    """Non-plugin-bundle (standalone) entries do not get mcp_status enrichment."""
    standalone = {
        "id": "docx",
        "source": "anthropic",
        "tier": "Community",
        "version": "1.0",
    }
    with (
        patch("routes.marketplace.load_installed", return_value=[standalone]),
        patch("routes.marketplace._load_native_skills", return_value=[]),
        patch("mcp.manager.list_with_status", return_value=[]),
    ):
        r = client.get("/api/marketplace/installed")
    assert r.status_code == 200
    skills = r.json()["skills"]
    docx = next((s for s in skills if s["id"] == "docx"), None)
    assert docx is not None
    assert "mcp_status" not in docx


def test_get_installed_mcp_enrichment_fails_soft():
    """If list_with_status() raises, installed entries are returned unchanged (no crash)."""
    bundle_entry = {
        "id": "slack",
        "source": "claude-plugins-official",
        "tier": "Verified",
        "mcp_connection_ids": ["plugin:slack:slack"],
        "consented": True,
    }
    with (
        patch("routes.marketplace.load_installed", return_value=[bundle_entry]),
        patch("routes.marketplace._load_native_skills", return_value=[]),
        patch("mcp.manager.list_with_status", side_effect=RuntimeError("mcp unavailable")),
    ):
        r = client.get("/api/marketplace/installed")
    assert r.status_code == 200
    skills = r.json()["skills"]
    slack = next((s for s in skills if s["id"] == "slack"), None)
    assert slack is not None
    # mcp_status absent — enrichment silently skipped
    assert "mcp_status" not in slack


def test_get_installed_mcp_status_quarantined():
    """A plugin with enabled connections but quarantined tools surfaces quarantined count."""
    bundle_entry = {
        "id": "jira",
        "source": "claude-plugins-official",
        "tier": "Verified",
        "mcp_connection_ids": ["plugin:jira:mcp"],
        "consented": True,
        "skill_ids": ["jira"],
        "version": "1.0",
    }
    live_connections = [
        {
            "id": "plugin:jira:mcp",
            "name": "mcp",
            "enabled": True,
            "tool_compatibility": {"quarantined": 3},
        }
    ]
    with (
        patch("routes.marketplace.load_installed", return_value=[bundle_entry]),
        patch("routes.marketplace._load_native_skills", return_value=[]),
        patch("mcp.manager.list_with_status", return_value=live_connections),
    ):
        r = client.get("/api/marketplace/installed")
    assert r.status_code == 200
    mcp_status = r.json()["skills"][0].get("mcp_status")
    assert mcp_status is not None
    # quarantined counts how many connections have ≥1 quarantined tool, not total tools
    assert mcp_status["quarantined"] == 1
    assert mcp_status["enabled"] == 1


# ---------------------------------------------------------------------------
# P0 — consent preview includes command_count
# ---------------------------------------------------------------------------


def test_consent_preview_includes_command_count():
    """The no-consent preview response must include command_count in capabilities
    so the frontend can show bundled commands in the Review & Install dialog."""
    import marketplace.github_fetcher as _gf
    import io
    import tarfile

    sha = _CPO_ENTRY["plugin_source"]["sha"]
    subpath = _CPO_ENTRY["plugin_source"]["path"]  # "skills"
    # Tarball root is "{repo}-{sha}/"; subpath "skills" is appended by the fetcher.
    # Files under the selected subtree are returned relative to that subtree.
    root = f"skills-{sha}/"
    prefix = root + subpath.strip("/") + "/"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel, data in {
            "SKILL.md": b"---\nname: AMD\n---\n# AMD\n",
            "commands/deploy.md": b"---\ndescription: Deploy\n---\ndeploy $ARGUMENTS",
            "commands/setup.md": b"---\ndescription: Setup\n---\nsetup $ARGUMENTS",
        }.items():
            name = prefix + rel
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    tar_bytes = buf.getvalue()

    import unittest.mock as _mock
    resp = _mock.MagicMock()
    resp.read = _mock.MagicMock(side_effect=lambda n=None: tar_bytes if n is None else tar_bytes[:n])
    resp.__enter__ = _mock.MagicMock(return_value=resp)
    resp.__exit__ = _mock.MagicMock(return_value=False)
    resp.headers = {}

    with (
        _mock.patch.object(_gf.urllib.request, "urlopen", return_value=resp),
        patch("routes.marketplace.fetch_catalog", return_value=[_CPO_ENTRY]),
    ):
        r = client.post("/api/marketplace/install", json={"skill_id": "amd-skills"})

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.json()}"
    body = r.json()
    assert body["ok"] is False
    assert body["consent_required"] is True
    caps = body["capabilities"]
    assert "command_count" in caps, "capabilities must include command_count"
    assert caps["command_count"] == 2, f"expected 2 commands, got {caps['command_count']}"
