"""Phase E — plugin-bundled MCP servers (2026-08-07 milestone, decision #5,
Increment 3): a plugin's .mcp.json is parsed with the SAME normalizer the
manual "Connect an MCP server" add-modal uses and mapped onto mcp.manager's
existing connection model (plugin-derived id, ownership metadata), with a
self-contained server auto-enabling and an unresolved {PLACEHOLDER} secret
registering a disabled/pending connection instead of spawning with a broken
env. Uninstall tears every plugin-owned connection back down via the same
mcp.manager.remove() a user-initiated delete uses.
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

import importlib
from pathlib import Path
from unittest.mock import patch, MagicMock


def _reload_installer(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path / "skills")
    import marketplace.installer as m
    importlib.reload(m)
    return m


class _FakeConnStore:
    """Minimal in-memory stand-in for config.json:mcp_connections that
    actually persists across calls (a static return_value would make a
    second register/remove call "see" stale state — see mcp.manager's own
    concurrency test for the same pattern)."""
    def __init__(self):
        self.connections: list[dict] = []

    def load(self):
        return [dict(c) for c in self.connections]

    def save(self, conns):
        self.connections = [dict(c) for c in conns]


def _patch_mcp_store(monkeypatch):
    store = _FakeConnStore()
    monkeypatch.setattr("mcp.manager._load_connections", store.load)
    monkeypatch.setattr("mcp.manager._save_connections", store.save)
    return store


_AMD_ENTRY = {
    "id": "amd-skills",
    "name": "amd-skills",
    "tier": "Verified",
    "install_url": "https://github.com/amd/skills.git",
    "plugin_source": {
        "kind": "git-subdir",
        "url": "https://github.com/amd/skills.git",
        "path": "skills",
        "ref": "main",
        "sha": "37d424162b9fe1b55f8665fb1e82d47e670e7385",
    },
}


def _bundle_files():
    return {
        "skills/a/SKILL.md": b"---\nname: a\nversion: 2.0\n---\nDo a.",
        "skills/b/SKILL.md": b"---\nname: b\n---\nDo b.",
    }


def _mcp_json(servers: dict) -> bytes:
    return json.dumps({"mcpServers": servers}).encode()


# ---------------------------------------------------------------------------
# Item 1 — self-contained server auto-enables via the real add_or_update path.
# ---------------------------------------------------------------------------

def test_install_self_contained_stdio_server_registers_enabled_connection(tmp_path, monkeypatch):
    """A plugin's .mcp.json declaring a fully self-contained stdio server (no
    {PLACEHOLDER} env vars) results in an ENABLED mcp.manager connection
    under the plugin-derived id (decision #5's "no secret needed" case)."""
    m = _reload_installer(tmp_path, monkeypatch)
    store = _patch_mcp_store(monkeypatch)

    mock_client = MagicMock()
    mock_client.server_info.return_value = {"name": "filesystem-mcp", "version": "1.0"}
    mock_client.list_tools.return_value = [
        {"name": "list_dir", "description": "List a directory", "inputSchema": {"type": "object", "properties": {}}}
    ]

    files = dict(_bundle_files())
    files[".mcp.json"] = _mcp_json({
        "filesystem": {"command": "npx", "args": ["@modelcontextprotocol/server-filesystem", "/tmp"]}
    })

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files), \
         patch("mcp.manager.acquire_pooled", return_value=mock_client):
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert result["ok"] is True
    assert result["mcp_connection_ids"] == ["plugin:amd-skills:filesystem"]
    assert result["mcp_compatibility_warnings"] == []

    conn = next(c for c in store.connections if c["id"] == "plugin:amd-skills:filesystem")
    assert conn["enabled"] is True
    assert conn["plugin_id"] == "amd-skills"
    assert conn["transport"] == "stdio"
    assert len(conn["cached_tools"]) == 1

    entry = next(e for e in m.load_installed() if e["id"] == "amd-skills")
    assert entry["mcp_connection_ids"] == ["plugin:amd-skills:filesystem"]


# ---------------------------------------------------------------------------
# Item 1 — unresolved secret registers a disabled/pending connection, never
# a spawn attempt with a broken env value.
# ---------------------------------------------------------------------------

def test_install_server_needing_secret_registers_disabled_pending_connection(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    store = _patch_mcp_store(monkeypatch)

    files = dict(_bundle_files())
    files[".mcp.json"] = _mcp_json({
        "datadog": {
            "command": "npx",
            "args": ["-y", "@datadog/mcp-server"],
            "env": {"DATADOG_API_KEY": "{DATADOG_API_KEY}"},
        }
    })

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files), \
         patch("mcp.manager.StdioMCPClient") as mock_cls:
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert result["ok"] is True
    assert result["mcp_connection_ids"] == ["plugin:amd-skills:datadog"]
    mock_cls.assert_not_called()  # must never attempt to spawn with a broken/templated env

    conn = next(c for c in store.connections if c["id"] == "plugin:amd-skills:datadog")
    assert conn["enabled"] is False
    assert conn["missing_secrets"] == ["DATADOG_API_KEY"]
    assert conn["cached_tools"] == []


# ---------------------------------------------------------------------------
# Item 2 — uninstall tears every plugin-owned connection down: config.json
# entry removed, pooled process released, tools deregistered.
# ---------------------------------------------------------------------------

def test_install_server_with_secret_in_args_registers_disabled_pending_connection(tmp_path, monkeypatch):
    """Fix #1 (2026-08-07 milestone adversarial review): a plugin declaring a
    secret as a CLI flag (not an env var) must also be detected — never
    live-spawned with the literal placeholder string as an argument."""
    m = _reload_installer(tmp_path, monkeypatch)
    store = _patch_mcp_store(monkeypatch)

    files = dict(_bundle_files())
    files[".mcp.json"] = _mcp_json({
        "foo": {
            "command": "npx",
            "args": ["-y", "@foo/mcp", "--api-key", "{FOO_API_KEY}"],
        }
    })

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files), \
         patch("mcp.manager.StdioMCPClient") as mock_cls:
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert result["ok"] is True
    assert result["mcp_connection_ids"] == ["plugin:amd-skills:foo"]
    mock_cls.assert_not_called()  # must never attempt to spawn with a broken/templated arg

    conn = next(c for c in store.connections if c["id"] == "plugin:amd-skills:foo")
    assert conn["enabled"] is False
    assert conn["missing_secrets"] == ["FOO_API_KEY"]
    assert conn["cached_tools"] == []


def test_install_server_with_empty_string_env_registers_disabled_pending_connection(tmp_path, monkeypatch):
    """Fix #2 (2026-08-07 milestone adversarial review): an env var declared
    as an empty string ("user must fill this in" convention, no
    {PLACEHOLDER} syntax) must also be treated as a missing secret — never
    live-spawned with a blank credential."""
    m = _reload_installer(tmp_path, monkeypatch)
    store = _patch_mcp_store(monkeypatch)

    files = dict(_bundle_files())
    files[".mcp.json"] = _mcp_json({
        "datadog": {
            "command": "npx",
            "args": ["-y", "@datadog/mcp-server"],
            "env": {"DATADOG_API_KEY": ""},
        }
    })

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files), \
         patch("mcp.manager.StdioMCPClient") as mock_cls:
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert result["ok"] is True
    assert result["mcp_connection_ids"] == ["plugin:amd-skills:datadog"]
    mock_cls.assert_not_called()

    conn = next(c for c in store.connections if c["id"] == "plugin:amd-skills:datadog")
    assert conn["enabled"] is False
    assert conn["missing_secrets"] == ["DATADOG_API_KEY"]
    assert conn["cached_tools"] == []


def test_capabilities_preview_ignores_mcp_json_outside_skill_dirs(tmp_path, monkeypatch):
    """Fix #3 (2026-08-07 milestone adversarial review): the read-only
    consent-preview must scan the SAME set of .mcp.json files the real
    install-time registration does (plugin root + bundled skill dirs) — not
    every .mcp.json anywhere in the tarball tree. A server declared in a
    non-skill directory (e.g. docs/example/.mcp.json) must not show up as
    "will run" here when the real install would never register it."""
    m = _reload_installer(tmp_path, monkeypatch)

    files = dict(_bundle_files())
    files[".mcp.json"] = _mcp_json({"filesystem": {"command": "npx", "args": ["pkg"]}})
    files["docs/example/.mcp.json"] = _mcp_json({"rogue": {"command": "npx", "args": ["pkg2"]}})

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files):
        caps = m.get_claude_plugins_official_capabilities(_AMD_ENTRY)

    assert caps["ok"] is True
    names = {s["name"] for s in caps["mcp_servers"]}
    assert names == {"filesystem"}
    assert "rogue" not in names


def test_already_installed_fast_path_backfills_missing_mcp_registration(tmp_path, monkeypatch):
    """Fix #6 (2026-08-07 milestone adversarial review): an install record
    with no "mcp_connection_ids" key at all (simulating a pre-Phase-E
    install, before this key existed) must be backfilled with a real MCP
    registration when it hits the already-installed fast path — files are
    already on disk from the prior install."""
    m = _reload_installer(tmp_path, monkeypatch)
    store = _patch_mcp_store(monkeypatch)

    mock_client = MagicMock()
    mock_client.server_info.return_value = {"name": "filesystem-mcp", "version": "1.0"}
    mock_client.list_tools.return_value = [
        {"name": "list_dir", "description": "", "inputSchema": {"type": "object", "properties": {}}}
    ]

    files = dict(_bundle_files())
    files[".mcp.json"] = _mcp_json({"filesystem": {"command": "npx", "args": ["pkg"]}})

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files), \
         patch("mcp.manager.StdioMCPClient", return_value=mock_client):
        m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    # Simulate a pre-Phase-E record: strip the key entirely, and pretend the
    # connection was never actually registered (as it wouldn't have been,
    # before Phase E code existed).
    entries = m.load_installed()
    for e in entries:
        if e["id"] == "amd-skills":
            e.pop("mcp_connection_ids", None)
    m.save_installed(entries)
    store.connections = []

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files), \
         patch("mcp.manager.StdioMCPClient", return_value=mock_client):
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert result["ok"] is True
    assert result["mcp_connection_ids"] == ["plugin:amd-skills:filesystem"]
    assert result["mcp_compatibility_warnings"] == []
    entry = next(e for e in m.load_installed() if e["id"] == "amd-skills")
    assert entry["mcp_connection_ids"] == ["plugin:amd-skills:filesystem"]
    assert any(c["id"] == "plugin:amd-skills:filesystem" for c in store.connections)


def test_already_installed_fast_path_does_not_reregister_when_key_present(tmp_path, monkeypatch):
    """Idempotency guard (fix #6): a record that already HAS
    mcp_connection_ids — even an empty list, meaning a plugin correctly
    registered by Phase E code with zero declared servers — must NOT
    re-register on the already-installed fast path."""
    m = _reload_installer(tmp_path, monkeypatch)
    _patch_mcp_store(monkeypatch)

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    entry = next(e for e in m.load_installed() if e["id"] == "amd-skills")
    assert entry["mcp_connection_ids"] == []

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()), \
         patch("marketplace.installer._register_plugin_mcp_servers") as mock_register:
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    mock_register.assert_not_called()
    assert result["mcp_connection_ids"] == []


def test_uninstall_removes_plugin_mcp_connections_stops_process_deregisters_tools(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    store = _patch_mcp_store(monkeypatch)

    mock_client = MagicMock()
    mock_client.server_info.return_value = {"name": "filesystem-mcp", "version": "1.0"}
    mock_client.list_tools.return_value = [
        {"name": "list_dir", "description": "", "inputSchema": {"type": "object", "properties": {}}}
    ]

    files = dict(_bundle_files())
    files[".mcp.json"] = _mcp_json({"filesystem": {"command": "npx", "args": ["pkg"]}})

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files), \
         patch("mcp.manager.acquire_pooled", return_value=mock_client):
        m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert any(c["id"] == "plugin:amd-skills:filesystem" for c in store.connections)

    import shared
    aliases = shared.SKILL_TOOLS_MAP["plugin:amd-skills:filesystem"]
    assert len(aliases) == 1
    runtime_alias = next(iter(aliases))
    assert runtime_alias in shared.TOOL_DISPATCH

    with patch("mcp.manager.release_from_pool") as mock_release:
        result = m.uninstall_skill("amd-skills")

    assert result["ok"] is True
    # Same assertions a normal manual-MCP-connection-delete test would use:
    # removed from config.json:mcp_connections, pooled process released,
    # namespaced tools deregistered from shared dispatch.
    assert not any(c["id"] == "plugin:amd-skills:filesystem" for c in store.connections)
    mock_release.assert_called_once()
    assert runtime_alias not in shared.TOOL_DISPATCH


# ---------------------------------------------------------------------------
# Item 3 — get_claude_plugins_official_capabilities() reports mcp_servers
# summary (name + needs_secrets) alongside has_mcp, without writing anything.
# ---------------------------------------------------------------------------

def test_get_capabilities_reports_mcp_servers_summary_with_needs_secrets(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)

    files = dict(_bundle_files())
    files[".mcp.json"] = _mcp_json({
        "filesystem": {"command": "npx", "args": ["pkg"]},
        "datadog": {"command": "npx", "args": ["pkg2"], "env": {"DATADOG_API_KEY": "{DATADOG_API_KEY}"}},
    })

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files):
        caps = m.get_claude_plugins_official_capabilities(_AMD_ENTRY)

    assert caps["ok"] is True
    assert caps["has_mcp"] is True
    by_name = {s["name"]: s for s in caps["mcp_servers"]}
    assert by_name["filesystem"]["needs_secrets"] == []
    assert by_name["datadog"]["needs_secrets"] == ["DATADOG_API_KEY"]

    # Still read-only — nothing written to disk or the install index.
    plugin_root = tmp_path / "cache" / "claude-plugins-official" / "amd-skills"
    assert not plugin_root.exists()
    assert not any(e.get("id") == "amd-skills" for e in m.load_installed())


def test_get_capabilities_no_mcp_reports_empty_mcp_servers(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        caps = m.get_claude_plugins_official_capabilities(_AMD_ENTRY)
    assert caps["ok"] is True
    assert caps["has_mcp"] is False
    assert caps["mcp_servers"] == []


# ---------------------------------------------------------------------------
# Regression guard — a plugin with no .mcp.json anywhere in its tree must
# have zero MCP side effects.
# ---------------------------------------------------------------------------

def test_install_without_mcp_json_has_zero_mcp_side_effects(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    store = _patch_mcp_store(monkeypatch)

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert result["ok"] is True
    assert result["mcp_connection_ids"] == []
    assert store.connections == []
    entry = next(e for e in m.load_installed() if e["id"] == "amd-skills")
    assert entry["mcp_connection_ids"] == []


# ---------------------------------------------------------------------------
# Item 4 — runtime prerequisites (decision #6): registering a plugin's stdio
# MCP server must go through the exact same command-resolution path
# (stdio_client._resolve_command -> ensure_bundled_node_on_path) a manually
# -added connection uses — proven with a REAL StdioMCPClient against the
# repo's existing fake_mcp_server.py fixture (tests/mcp/fixtures), not a
# mocked class, so this actually exercises _resolve_command rather than
# assuming it by construction.
# ---------------------------------------------------------------------------

_FAKE_MCP_SERVER = str(
    Path(__file__).parent.parent / "mcp" / "fixtures" / "fake_mcp_server.py"
)


def test_self_contained_server_resolves_command_via_bundled_node_path_hook(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    _patch_mcp_store(monkeypatch)

    files = dict(_bundle_files())
    files[".mcp.json"] = _mcp_json({
        "fake": {"command": sys.executable, "args": [_FAKE_MCP_SERVER]}
    })

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files), \
         patch("mcp.stdio_client.ensure_bundled_node_on_path") as mock_ensure_node:
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert result["ok"] is True
    assert result["mcp_connection_ids"] == ["plugin:amd-skills:fake"]
    # The bundled-Node-on-PATH hook is called unconditionally by
    # StdioMCPClient._resolve_command on every spawn attempt (regardless of
    # command) — proving register_plugin_mcp_server -> add_or_update reaches
    # the identical resolution code a manual connection add uses, not a
    # bypassed/parallel path.
    assert mock_ensure_node.called

    from mcp.manager import _unregister
    _unregister("plugin:amd-skills:fake")


# ---------------------------------------------------------------------------
# Gap #1 (2026-08-07 milestone bug fix): a plugin's .claude-plugin/plugin.json
# can point at a custom-named MCP config file via a STRING mcpServers field
# instead of shipping the canonical .mcp.json filename. Real, confirmed
# example: datadog's plugin.json has
# `"mcpServers": "./.dd_claude-code_mcp.json"`.
# ---------------------------------------------------------------------------

_DATADOG_PLUGIN_JSON = json.dumps({
    "name": "datadog",
    "version": "0.7.14",
    "description": "Use Datadog directly in Claude Code through a preconfigured "
                    "Datadog MCP server.",
    "author": {"name": "Datadog"},
    "mcpServers": "./.dd_claude-code_mcp.json",
}).encode()

# Real datadog .mcp.json content (2026-08-07 milestone bug report) — secrets
# declared in bash-parameter-expansion syntax ("${VAR:-default}"), not bare
# {VAR} — this is gap #2's exact reproduction fixture.
_DATADOG_MCP_JSON = json.dumps({
    "mcpServers": {
        "mcp": {
            "type": "http",
            "url": "https://${DD_MCP_DOMAIN:-not-setup}/v1/mcp?referrer_ide=claude-code-plugin"
                   "&plugin_version=0.7.14&toolsets=${DD_MCP_TOOLSETS:-}",
            "headers": {
                "DD_API_KEY": "${DD_API_KEY:-}",
                "DD_APPLICATION_KEY": "${DD_APPLICATION_KEY:-}",
            },
        }
    }
}).encode()

# Real airtable .mcp.json content (2026-08-07 milestone bug report) — bare
# top-level format, no "mcpServers" wrapper key at all — gap #3's exact
# reproduction fixture. Secret-free (unauthenticated), so needs_secrets == [].
_AIRTABLE_MCP_JSON = json.dumps({
    "airtable": {"type": "http", "url": "https://mcp.airtable.com/mcp"},
}).encode()


def test_install_resolves_plugin_json_string_pointer_to_custom_named_mcp_file(tmp_path, monkeypatch):
    """Gap #1 + gap #2 end-to-end, on-disk install path
    (_discover_plugin_mcp_manifest): datadog's real plugin.json/mcp-config
    pair, with no canonical .mcp.json anywhere — discovered correctly, and
    its bash-style secrets registered as a disabled/pending connection
    (never live-spawned with the literal unresolved string)."""
    m = _reload_installer(tmp_path, monkeypatch)
    store = _patch_mcp_store(monkeypatch)

    files = dict(_bundle_files())
    files[".claude-plugin/plugin.json"] = _DATADOG_PLUGIN_JSON
    files[".dd_claude-code_mcp.json"] = _DATADOG_MCP_JSON

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files), \
         patch("mcp.manager.GenericMCPClient") as mock_cls:
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert result["ok"] is True
    assert result["mcp_connection_ids"] == ["plugin:amd-skills:mcp"]
    mock_cls.assert_not_called()  # never live-spawn with the literal "${VAR:-...}" string

    conn = next(c for c in store.connections if c["id"] == "plugin:amd-skills:mcp")
    assert conn["enabled"] is False
    assert set(conn["missing_secrets"]) == {
        "DD_MCP_DOMAIN", "DD_MCP_TOOLSETS", "DD_API_KEY", "DD_APPLICATION_KEY",
    }
    assert conn["cached_tools"] == []


def test_capabilities_preview_resolves_plugin_json_string_pointer(tmp_path, monkeypatch):
    """Gap #1 + gap #2, in-memory consent-preview path
    (_discover_plugin_mcp_manifest_from_files + has_mcp derivation): the
    exact reported symptom — "consent dialog shows no mention of MCP" for
    a plugin whose manifest lives at a non-canonical filename — must not
    reproduce after the fix. has_mcp must be True and needs_secrets must
    list the bare variable names, not the raw "${VAR:-default}" text."""
    m = _reload_installer(tmp_path, monkeypatch)

    files = dict(_bundle_files())
    files[".claude-plugin/plugin.json"] = _DATADOG_PLUGIN_JSON
    files[".dd_claude-code_mcp.json"] = _DATADOG_MCP_JSON

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files):
        caps = m.get_claude_plugins_official_capabilities(_AMD_ENTRY)

    assert caps["ok"] is True
    assert caps["has_mcp"] is True
    by_name = {s["name"]: s for s in caps["mcp_servers"]}
    assert set(by_name["mcp"]["needs_secrets"]) == {
        "DD_MCP_DOMAIN", "DD_MCP_TOOLSETS", "DD_API_KEY", "DD_APPLICATION_KEY",
    }


def test_plugin_json_pointer_escaping_plugin_dir_is_ignored(tmp_path, monkeypatch):
    """A malicious/malformed plugin.json pointing outside the plugin tree
    (path traversal) must resolve to zero servers, not raise or read outside
    the plugin's own files."""
    m = _reload_installer(tmp_path, monkeypatch)

    files = dict(_bundle_files())
    files[".claude-plugin/plugin.json"] = json.dumps({
        "name": "evil", "mcpServers": "../../../etc/passwd",
    }).encode()

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files):
        caps = m.get_claude_plugins_official_capabilities(_AMD_ENTRY)

    assert caps["ok"] is True
    assert caps["has_mcp"] is False
    assert caps["mcp_servers"] == []


def test_plugin_json_pointer_to_another_string_pointer_is_ignored(tmp_path, monkeypatch):
    """A pointer chain (pointed-to file's own mcpServers is ALSO a string)
    is not a real case — must degrade to "no servers found", never raise."""
    m = _reload_installer(tmp_path, monkeypatch)

    files = dict(_bundle_files())
    files[".claude-plugin/plugin.json"] = json.dumps({
        "name": "chained", "mcpServers": "./intermediate.json",
    }).encode()
    files["intermediate.json"] = json.dumps({"mcpServers": "./another.json"}).encode()
    files["another.json"] = _mcp_json({"real": {"command": "npx", "args": ["pkg"]}})

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files):
        caps = m.get_claude_plugins_official_capabilities(_AMD_ENTRY)

    assert caps["ok"] is True
    assert caps["has_mcp"] is False
    assert caps["mcp_servers"] == []


def test_plugin_json_inline_object_mcpservers_still_works(tmp_path, monkeypatch):
    """mcpServers as an inline OBJECT directly in plugin.json (not a string
    pointer) must be used directly — the other real, documented shape."""
    m = _reload_installer(tmp_path, monkeypatch)

    files = dict(_bundle_files())
    files[".claude-plugin/plugin.json"] = json.dumps({
        "name": "inline-plugin",
        "mcpServers": {"filesystem": {"command": "npx", "args": ["pkg"]}},
    }).encode()

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files):
        caps = m.get_claude_plugins_official_capabilities(_AMD_ENTRY)

    assert caps["ok"] is True
    assert caps["has_mcp"] is True
    names = {s["name"] for s in caps["mcp_servers"]}
    assert names == {"filesystem"}


# ---------------------------------------------------------------------------
# Gap #3 (2026-08-07 milestone bug fix): some real .mcp.json files skip the
# "mcpServers" wrapper key entirely — the server definitions sit directly at
# the top level. Real, confirmed example: Airtable's .mcp.json.
# ---------------------------------------------------------------------------

def test_install_bare_format_mcp_json_registers_secret_free_server(tmp_path, monkeypatch):
    """Gap #3 end-to-end: airtable's real, wrapper-key-free .mcp.json is
    discovered and registered as a self-contained (no secrets needed) http
    server, not silently invisible (has_mcp: false / zero side effects)."""
    m = _reload_installer(tmp_path, monkeypatch)
    store = _patch_mcp_store(monkeypatch)

    mock_client = MagicMock()
    mock_client.server_info.return_value = {"name": "airtable", "version": "1.0"}
    mock_client.list_tools.return_value = [
        {"name": "list_bases", "description": "", "inputSchema": {"type": "object", "properties": {}}}
    ]
    mock_client.call_probe.return_value = (False, "")

    files = dict(_bundle_files())
    files[".mcp.json"] = _AIRTABLE_MCP_JSON

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files), \
         patch("mcp.manager.GenericMCPClient", return_value=mock_client):
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert result["ok"] is True
    assert result["mcp_connection_ids"] == ["plugin:amd-skills:airtable"]

    conn = next(c for c in store.connections if c["id"] == "plugin:amd-skills:airtable")
    assert conn["enabled"] is True
    assert conn["transport"] == "http"
    assert conn["url"] == "https://mcp.airtable.com/mcp"


def test_capabilities_preview_bare_format_reports_secret_free_airtable(tmp_path, monkeypatch):
    """Gap #3, consent-preview path: has_mcp: true, needs_secrets: [] for
    airtable (unauthenticated — no secrets declared at all)."""
    m = _reload_installer(tmp_path, monkeypatch)

    files = dict(_bundle_files())
    files[".mcp.json"] = _AIRTABLE_MCP_JSON

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files):
        caps = m.get_claude_plugins_official_capabilities(_AMD_ENTRY)

    assert caps["ok"] is True
    assert caps["has_mcp"] is True
    by_name = {s["name"]: s for s in caps["mcp_servers"]}
    assert by_name["airtable"]["needs_secrets"] == []


def test_bare_format_negative_unrelated_json_not_misinterpreted():
    """Negative test (gap #3): a dict where a top-level value doesn't look
    like a server definition (e.g. a plain settings-shaped file, or a dict
    with non-dict values) must NOT be misinterpreted as a bare mcpServers
    map."""
    from marketplace.installer import _mcp_manifest_from_dict

    # Values are strings, not dicts at all.
    assert _mcp_manifest_from_dict({"name": "some-plugin", "version": "1.0"}) == {}

    # A dict of dicts, but none of them look like a server definition
    # (no type/command/url/args/env key).
    assert _mcp_manifest_from_dict({
        "author": {"name": "Someone", "email": "x@example.com"},
        "settings": {"theme": "dark"},
    }) == {}

    # Mixed: one value looks like a server, one doesn't — must NOT partially
    # misinterpret; the whole file is rejected as bare-format.
    assert _mcp_manifest_from_dict({
        "airtable": {"type": "http", "url": "https://mcp.airtable.com/mcp"},
        "author": {"name": "Someone"},
    }) == {}

    # Empty dict is not bare-format (nothing to recognize).
    assert _mcp_manifest_from_dict({}) == {}


def test_bare_format_wrapped_key_present_wins_even_if_shaped_like_bare():
    """When "mcpServers" key IS present, the wrapped form always wins —
    even if the top-level dict would otherwise look bare-format-shaped."""
    from marketplace.installer import _mcp_manifest_from_dict

    config = {
        "mcpServers": {"real": {"command": "npx", "args": ["pkg"]}},
        "decoy": {"type": "http", "url": "https://example.com"},
    }
    servers = _mcp_manifest_from_dict(config)
    assert set(servers.keys()) == {"real"}


# ---------------------------------------------------------------------------
# Fix 1 (adversarial review of this milestone's own fix #3): merge-order
# tie-break regression. A bundled skill dir living directly under the plugin
# root (depth-1 — both root's relpath "" and the skill dir's relpath have 0
# "/" characters) previously TIED under a slash-count sort in
# _discover_plugin_mcp_manifest_from_files, letting root merge FIRST and the
# skill dir LAST — so the skill dir's same-named server won on a collision,
# the opposite of the function's own docstring and a divergence from the
# on-disk sibling _discover_plugin_mcp_manifest (which never sorts by slash
# count — it appends plugin_dir last via plain list concatenation). Both
# on-disk and in-memory variants are tested here to prove they AGREE on this
# exact case, not just each independently claiming "root wins" in isolation.
# ---------------------------------------------------------------------------

def _write_tree(root: Path, files: dict) -> None:
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def test_from_files_root_wins_against_depth1_skill_dir_same_named_server(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    files = {
        "myskill/SKILL.md": b"---\nname: myskill\n---\nDo it.",
        ".mcp.json": _mcp_json({"shared": {"command": "root-cmd", "args": []}}),
        "myskill/.mcp.json": _mcp_json({"shared": {"command": "skill-cmd", "args": []}}),
    }
    servers = m._discover_plugin_mcp_manifest_from_files(files)
    assert servers["shared"]["command"] == "root-cmd"


def test_on_disk_root_wins_against_depth1_skill_dir_same_named_server(tmp_path, monkeypatch):
    """On-disk equivalent of the above, proving _discover_plugin_mcp_manifest
    and _discover_plugin_mcp_manifest_from_files produce IDENTICAL precedence
    for the same on-disk shape — the actual invariant being protected
    ("consent preview must match what actually installs")."""
    m = _reload_installer(tmp_path, monkeypatch)
    plugin_dir = tmp_path / "plugin_root"
    _write_tree(plugin_dir, {
        "myskill/SKILL.md": b"---\nname: myskill\n---\nDo it.",
        ".mcp.json": _mcp_json({"shared": {"command": "root-cmd", "args": []}}),
        "myskill/.mcp.json": _mcp_json({"shared": {"command": "skill-cmd", "args": []}}),
    })
    servers = m._discover_plugin_mcp_manifest(plugin_dir)
    assert servers["shared"]["command"] == "root-cmd"


# ---------------------------------------------------------------------------
# Fix 2 (adversarial review): on-disk vs in-memory path-traversal scope
# divergence for a bundled skill dir's plugin.json pointer. The in-memory
# resolver used to pass the SKILL DIR's own relpath as the traversal-guard
# base, letting ".." components in a declared pointer walk out of that skill
# dir's own subtree into a sibling dir (or the plugin root) as long as the
# final result stayed somewhere inside the overall tarball tree — the
# on-disk sibling always guards against base_dir="" first (rejecting ANY
# ".." usage outright), then joins the already-".."-free pointer onto the
# calling dir. Exact repro from the review: `_resolve_plugin_relative_path(
# 'skills/foo', '../bar/../../secret_outside')` normalizes to
# 'secret_outside' (valid in-tree, but outside skills/foo's own subtree).
# ---------------------------------------------------------------------------

_ESCAPE_POINTER_FILES = {
    "skills/foo/SKILL.md": b"---\nname: foo\n---\nDo foo.",
    "skills/foo/.claude-plugin/plugin.json": json.dumps({
        "name": "foo", "mcpServers": "../bar/../../secret_outside.json",
    }).encode(),
    "secret_outside.json": _mcp_json({"leaked": {"command": "npx", "args": ["pkg"]}}),
}


def test_plugin_json_pointer_from_skill_dir_cannot_escape_its_own_subtree_in_memory(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    servers = m._mcp_servers_declared_via_plugin_json_from_files(_ESCAPE_POINTER_FILES, "skills/foo")
    assert servers == {}


def test_plugin_json_pointer_from_skill_dir_cannot_escape_its_own_subtree_on_disk(tmp_path, monkeypatch):
    """On-disk equivalent — proves both functions reject the identical
    traversal shape, not just the in-memory one after this fix."""
    m = _reload_installer(tmp_path, monkeypatch)
    plugin_dir = tmp_path / "plugin_root"
    _write_tree(plugin_dir, _ESCAPE_POINTER_FILES)
    servers = m._mcp_servers_declared_via_plugin_json(plugin_dir / "skills" / "foo")
    assert servers == {}


def test_plugin_json_pointer_from_skill_dir_resolves_within_its_own_subtree(tmp_path, monkeypatch):
    """Positive control: a bundled skill dir's plugin.json pointing at a file
    WITHIN its own subtree must still resolve correctly after the fix — the
    fix must reject escaping pointers without breaking legitimate same-dir
    (or same-subtree) pointers."""
    m = _reload_installer(tmp_path, monkeypatch)
    files = {
        "skills/foo/SKILL.md": b"---\nname: foo\n---\nDo foo.",
        "skills/foo/.claude-plugin/plugin.json": json.dumps({
            "name": "foo", "mcpServers": "./config.json",
        }).encode(),
        "skills/foo/config.json": _mcp_json({"real": {"command": "npx", "args": ["pkg"]}}),
    }
    servers = m._mcp_servers_declared_via_plugin_json_from_files(files, "skills/foo")
    assert set(servers.keys()) == {"real"}
