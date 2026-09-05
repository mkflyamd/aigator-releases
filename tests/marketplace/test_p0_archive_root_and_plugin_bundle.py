"""P0 regression tests — archive-root normalization + official plugin bundle with MCP.

Covers:
1. The Slack renamed-repository case: catalog URL says 'slack-mcp-plugin' but
   GitHub's codeload archive root is 'slack-skills-plugin-{sha}/' after rename.
2. Symlink security: rejected inside the selected subtree, silently skipped outside.
3. End-to-end install of an official plugin bundle that declares an MCP connection,
   verifying consent preview (capabilities) and the real install path.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "web"))

import io
import json
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from marketplace import github_fetcher
from marketplace.registry import (
    _normalize_plugin_source,
    _normalize_claude_plugins_official_entry,
)


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------


def _make_tarball(entries: dict, symlinks: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.type = tarfile.REGTYPE
            tf.addfile(info, io.BytesIO(data))
        for name, target in (symlinks or {}).items():
            info = tarfile.TarInfo(name=name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tf.addfile(info)
    return buf.getvalue()


def _mock_urlopen(tar_bytes: bytes):
    resp = MagicMock()
    resp.read = MagicMock(side_effect=lambda n=None: tar_bytes if n is None else tar_bytes[:n])
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.headers = {}
    return resp


# ---------------------------------------------------------------------------
# 1. Slack renamed-repository: archive root ≠ requested repo name
# ---------------------------------------------------------------------------


SLACK_SHA = "a1b2c3d4e5f6789012345678901234567890abcd"

SLACK_TARBALL_ENTRIES = {
    f"slack-skills-plugin-{SLACK_SHA}/SKILL.md": (
        b"---\nname: Slack\ndescription: Send and read Slack messages.\nversion: '1.0'\n---\n\n"
        b"# Slack\nSend and read Slack messages using MCP.\n"
    ),
    f"slack-skills-plugin-{SLACK_SHA}/.mcp.json": json.dumps(
        {
            "mcpServers": {
                "slack": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-slack"],
                    "env": {
                        "SLACK_BOT_TOKEN": "{SLACK_BOT_TOKEN}",
                        "SLACK_TEAM_ID": "{SLACK_TEAM_ID}",
                    },
                }
            }
        }
    ).encode(),
    f"slack-skills-plugin-{SLACK_SHA}/README.md": b"# Slack MCP Plugin\n",
}


def test_slack_renamed_repo_archive_root_detected_correctly():
    """_detect_archive_root finds 'slack-skills-plugin-{sha}/' even though the
    requested repo name is 'slack-mcp-plugin'."""
    tar_bytes = _make_tarball(SLACK_TARBALL_ENTRIES)
    buf = io.BytesIO(tar_bytes)
    with tarfile.open(fileobj=buf, mode="r:gz") as tf:
        root = github_fetcher._detect_archive_root(tf)
    assert root == f"slack-skills-plugin-{SLACK_SHA}/"


def test_slack_renamed_repo_full_download_extracts_files():
    """download_skill_tarball extracts the Slack plugin correctly despite the
    repo rename (the archive root differs from the requested repo name)."""
    tar_bytes = _make_tarball(SLACK_TARBALL_ENTRIES)
    resp = _mock_urlopen(tar_bytes)
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        result = github_fetcher.download_skill_tarball(
            "modelcontextprotocol",
            "slack-mcp-plugin",
            SLACK_SHA,
            "",
        )
    assert "SKILL.md" in result
    assert ".mcp.json" in result
    mcp = json.loads(result[".mcp.json"])
    assert "slack" in mcp["mcpServers"]


def test_slack_renamed_repo_symlink_inside_subtree_rejected():
    """A symlink INSIDE the extracted subtree is still rejected even with the
    renamed-repo root detection in place — the security invariant is preserved."""
    entries = dict(SLACK_TARBALL_ENTRIES)
    symlinks = {f"slack-skills-plugin-{SLACK_SHA}/evil": "/etc/passwd"}
    tar_bytes = _make_tarball(entries, symlinks)
    resp = _mock_urlopen(tar_bytes)
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        with pytest.raises(ValueError, match="symlink"):
            github_fetcher.download_skill_tarball(
                "modelcontextprotocol", "slack-mcp-plugin", SLACK_SHA, ""
            )


def test_slack_renamed_repo_symlink_outside_subtree_skipped():
    """A symlink that is NOT inside the selected plugin subtree (i.e., outside the
    requested subpath) is silently skipped — never extracted or followed."""
    sha = SLACK_SHA
    entries = {
        f"slack-skills-plugin-{sha}/plugins/slack/SKILL.md": b"# slack\n",
        f"slack-skills-plugin-{sha}/plugins/slack/.mcp.json": b"{}",
    }
    symlinks = {
        f"slack-skills-plugin-{sha}/outside-evil": "/etc/passwd",
    }
    tar_bytes = _make_tarball(entries, symlinks)
    resp = _mock_urlopen(tar_bytes)
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        result = github_fetcher.download_skill_tarball(
            "modelcontextprotocol", "slack-mcp-plugin", sha, "plugins/slack"
        )
    assert "SKILL.md" in result
    assert ".mcp.json" in result


# ---------------------------------------------------------------------------
# 2. catalog entry shape for the Slack plugin (as seen in marketplace.json)
# ---------------------------------------------------------------------------


SLACK_CATALOG_RAW = {
    "name": "slack",
    "description": "Send and read Slack messages via MCP.",
    "author": {"name": "Anthropic"},
    "category": "communication",
    "source": {
        "source": "git-subdir",
        "url": "https://github.com/modelcontextprotocol/slack-mcp-plugin.git",
        "path": "",
        "ref": "main",
        "sha": SLACK_SHA,
    },
}


def test_slack_catalog_entry_normalized_correctly():
    entry = _normalize_claude_plugins_official_entry(SLACK_CATALOG_RAW)
    assert entry["id"] == "slack"
    assert entry["tier"] == "Verified"
    assert entry["source"] == "claude-plugins-official"
    assert entry["installable"] is True
    assert entry["coding_class"] == "none"
    assert entry["plugin_source"]["sha"] == SLACK_SHA
    assert entry["plugin_source"]["url"] == (
        "https://github.com/modelcontextprotocol/slack-mcp-plugin.git"
    )


def test_slack_catalog_entry_parse_git_clone_url():
    """The normalized entry's url must be parseable by parse_git_clone_url so the
    installer can extract owner/repo for the codeload download."""
    entry = _normalize_claude_plugins_official_entry(SLACK_CATALOG_RAW)
    url = entry["plugin_source"]["url"]
    parsed = github_fetcher.parse_git_clone_url(url)
    assert parsed is not None
    owner, repo = parsed
    assert owner == "modelcontextprotocol"
    assert repo == "slack-mcp-plugin"


# ---------------------------------------------------------------------------
# 3. End-to-end capabilities preview for the Slack plugin bundle
# (get_claude_plugins_official_capabilities — read-only, no disk writes)
# ---------------------------------------------------------------------------


def test_slack_capabilities_preview_detects_mcp_server_and_secrets(tmp_path, monkeypatch):
    """get_claude_plugins_official_capabilities reports has_mcp=True and lists
    the MCP server with its required secrets (SLACK_BOT_TOKEN, SLACK_TEAM_ID)."""
    import marketplace.installer as installer
    import marketplace.github_fetcher as gf

    monkeypatch.setattr(installer, "PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(installer, "INSTALLED_SKILLS_DIR", tmp_path / "skills")

    tar_bytes = _make_tarball(SLACK_TARBALL_ENTRIES)
    resp = _mock_urlopen(tar_bytes)

    entry = _normalize_claude_plugins_official_entry(SLACK_CATALOG_RAW)

    with patch.object(gf.urllib.request, "urlopen", return_value=resp):
        caps = installer.get_claude_plugins_official_capabilities(entry)

    assert caps["ok"] is True
    assert caps["plugin_id"] == "slack"
    assert caps["skill_count"] >= 1
    assert caps["has_mcp"] is True
    assert caps["has_local_code"] is False

    servers = caps.get("mcp_servers", [])
    assert len(servers) >= 1
    slack_srv = next((s for s in servers if s["name"] == "slack"), None)
    assert slack_srv is not None
    secrets = slack_srv["needs_secrets"]
    assert "SLACK_BOT_TOKEN" in secrets
    assert "SLACK_TEAM_ID" in secrets


def test_slack_capabilities_resolved_ref_matches_catalog_sha(tmp_path, monkeypatch):
    """The resolved_ref returned by the preview must equal the catalog sha so the
    install call can echo it back as pinned_ref (TOCTOU fix)."""
    import marketplace.installer as installer
    import marketplace.github_fetcher as gf

    monkeypatch.setattr(installer, "PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(installer, "INSTALLED_SKILLS_DIR", tmp_path / "skills")

    tar_bytes = _make_tarball(SLACK_TARBALL_ENTRIES)
    resp = _mock_urlopen(tar_bytes)
    entry = _normalize_claude_plugins_official_entry(SLACK_CATALOG_RAW)

    with patch.object(gf.urllib.request, "urlopen", return_value=resp):
        caps = installer.get_claude_plugins_official_capabilities(entry)

    assert caps["resolved_ref"] == SLACK_SHA


# ---------------------------------------------------------------------------
# 4. End-to-end install of the Slack plugin bundle
# ---------------------------------------------------------------------------


def test_slack_full_install_registers_skill_and_mcp_connection(tmp_path, monkeypatch):
    """install_claude_plugins_official_plugin with the Slack renamed-repo tarball:
    extracts files, discovers SKILL.md, detects MCP server requiring secrets, and
    writes an install record with mcp_connection_ids."""
    import marketplace.installer as installer
    import marketplace.github_fetcher as gf
    import shared as _shared

    monkeypatch.setattr(installer, "PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(installer, "INSTALLED_SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(_shared, "MCP_TOOL_DIAGNOSTICS", {})

    registered_connections: list[dict] = []

    def fake_register(plugin_id, server_name, cfg, missing):
        cid = f"plugin:{plugin_id}:{server_name}"
        registered_connections.append(
            {"id": cid, "plugin_id": plugin_id, "name": server_name, "missing": missing}
        )
        return {"id": cid}

    tar_bytes = _make_tarball(SLACK_TARBALL_ENTRIES)
    resp = _mock_urlopen(tar_bytes)
    entry = _normalize_claude_plugins_official_entry(SLACK_CATALOG_RAW)

    with (
        patch.object(gf.urllib.request, "urlopen", return_value=resp),
        patch("marketplace.installer._mcp_manager", create=True),
        patch("marketplace.installer._parse_server_entry", create=True),
        patch("mcp.manager.register_plugin_mcp_server", side_effect=fake_register),
    ):
        result = installer.install_claude_plugins_official_plugin(
            entry, consented=True, pinned_ref=SLACK_SHA
        )

    assert result.get("ok") is True, f"Install failed: {result}"
    assert result["plugin_id"] == "slack"
    assert len(result.get("skill_ids", [])) >= 1

    installed = installer.load_installed()
    record = next((e for e in installed if e["id"] == "slack"), None)
    assert record is not None, "No install record for 'slack'"
    assert record.get("consented") is True
    assert record.get("sha") == SLACK_SHA

    plugin_dir = tmp_path / "plugins" / "cache" / "claude-plugins-official" / "slack"
    assert plugin_dir.exists(), "Plugin cache directory was not created"
    version_dirs = list(plugin_dir.iterdir())
    assert version_dirs, "No version directory found"
    skill_md = version_dirs[0] / "SKILL.md"
    assert skill_md.exists(), "SKILL.md was not extracted"
    mcp_json = version_dirs[0] / ".mcp.json"
    assert mcp_json.exists(), ".mcp.json was not extracted"
