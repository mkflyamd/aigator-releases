"""Phase B — claude-plugins-official plugin install (2026-08-07 milestone,
decisions #3/#4/#9): tarball @ pinned sha, recursive skills/*/SKILL.md
bundle registration, one install record, uninstall tears the whole tree down.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

import importlib
from unittest.mock import patch


def _reload_installer(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path / "skills")
    import marketplace.installer as m
    importlib.reload(m)
    return m


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


def _bundle_files(with_tools=False):
    files = {
        "skills/a/SKILL.md": b"---\nname: a\nversion: 2.0\n---\nDo a.",
        "skills/b/SKILL.md": b"---\nname: b\n---\nDo b.",
    }
    if with_tools:
        files["skills/a/tools.py"] = b"TOOL_DEFS = []\nTOOL_HANDLERS = {}\n"
    return files


def test_install_records_new_fields(tmp_path, monkeypatch):
    """Install record must carry skill_ids, sha, consented, source, marketplace_url."""
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert result["ok"] is True
    entry = next(e for e in m.load_installed() if e["id"] == "amd-skills")
    assert entry["source"] == "claude-plugins-official"
    assert entry["marketplace_url"] == "https://github.com/amd/skills.git"
    assert entry["sha"] == "37d424162b9fe1b55f8665fb1e82d47e670e7385"
    assert entry["consented"] is False
    # Namespaced by plugin_id (finding #2, 2026-08-07 milestone review) —
    # never the bare skill-folder name, which could collide across plugins.
    assert set(entry["skill_ids"]) == {"amd-skills__skills-a", "amd-skills__skills-b"}
    assert entry["tier"] == "Verified"


def test_install_recursive_bundle_registers_both_skills(tmp_path, monkeypatch):
    """Given a plugin with skills/a/SKILL.md + skills/b/SKILL.md, install must
    register BOTH — a naive single top-level SKILL.md assumption would find
    neither (this is the amd-skills real-world shape: 1 catalog entry -> N skills)."""
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert result["ok"] is True
    assert len(result["skill_ids"]) == 2
    # Namespaced ids (finding #2) — bare "a"/"b" would collide with any other
    # plugin that happens to bundle a same-named skill folder.
    assert set(result["skill_ids"]) == {"amd-skills__skills-a", "amd-skills__skills-b"}

    plugin_dir = tmp_path / "cache" / "claude-plugins-official" / "amd-skills"
    # Version resolved from the first (alphabetical) SKILL.md's frontmatter
    # since no .claude-plugin/plugin.json was present in the fetched tree.
    version_dir = plugin_dir / "2.0"
    assert (version_dir / "skills" / "a" / "SKILL.md").exists()
    assert (version_dir / "skills" / "b" / "SKILL.md").exists()


def test_install_falls_back_to_unknown_version_with_no_manifest_or_frontmatter_version(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    files = {"skills/a/SKILL.md": b"---\nname: a\n---\nNo version here."}
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files):
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)
    assert result["ok"] is True
    assert "unknown" in result["path"]


def test_install_does_not_overwrite_existing_version(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()) as mock_dl:
        m.install_claude_plugins_official_plugin(_AMD_ENTRY)
    version_file = (
        tmp_path / "cache" / "claude-plugins-official" / "amd-skills" / "2.0"
        / "skills" / "a" / "SKILL.md"
    )
    original_mtime = version_file.stat().st_mtime

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)
    assert result["ok"] is True
    assert version_file.stat().st_mtime == original_mtime


def test_reinstall_of_already_installed_version_does_not_overwrite_sha(tmp_path, monkeypatch):
    """Finding #6: when the version dir already exists on disk (skipped
    fetch/write), the existing install record's sha must not be silently
    replaced with a different value from a subsequent call's catalog entry —
    that would make installed-skills.json claim a sha that isn't what was
    actually fetched onto disk."""
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    original_entry = next(e for e in m.load_installed() if e["id"] == "amd-skills")
    original_sha = original_entry["sha"]
    assert original_sha == "37d424162b9fe1b55f8665fb1e82d47e670e7385"

    diverged_entry = dict(
        _AMD_ENTRY,
        plugin_source=dict(_AMD_ENTRY["plugin_source"], sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"),
    )
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        result = m.install_claude_plugins_official_plugin(diverged_entry)

    assert result["ok"] is True
    entries = [e for e in m.load_installed() if e["id"] == "amd-skills"]
    assert len(entries) == 1, "must not duplicate the record"
    assert entries[0]["sha"] == original_sha


def test_reinstall_with_no_existing_record_registers_from_disk(tmp_path, monkeypatch):
    """If the version dir exists but installed-skills.json has no matching
    record (e.g. a prior run crashed after writing files but before the
    upsert), re-install must still register normally rather than silently
    no-op with an empty skill_ids list.

    Fix #5 (2026-08-07 milestone adversarial review): the record's sha must
    be "" (unknown) here, NOT this call's freshly-resolved sha — we cannot
    verify it matches what actually produced the bytes already on disk from
    the earlier (possibly crashed) attempt. See
    test_reinstall_with_no_existing_record_and_diverged_sha_records_unknown_sha
    for the divergent-sha variant of this same scenario."""
    m = _reload_installer(tmp_path, monkeypatch)
    version_dir = tmp_path / "cache" / "claude-plugins-official" / "amd-skills" / "2.0"
    for rel, data in _bundle_files().items():
        target = version_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    assert not any(e.get("id") == "amd-skills" for e in m.load_installed())

    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert result["ok"] is True
    assert set(result["skill_ids"]) == {"amd-skills__skills-a", "amd-skills__skills-b"}
    entry = next(e for e in m.load_installed() if e["id"] == "amd-skills")
    assert entry["sha"] == ""


def test_install_has_tools_true_when_any_bundled_skill_has_tools_py(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files(with_tools=True)):
        m.install_claude_plugins_official_plugin(_AMD_ENTRY)
    entry = next(e for e in m.load_installed() if e["id"] == "amd-skills")
    assert entry["has_tools"] is True


def test_install_rejects_unparseable_source_url(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    bad_entry = dict(_AMD_ENTRY, plugin_source={"url": "https://gitlab.com/amd/skills", "path": "skills"})
    result = m.install_claude_plugins_official_plugin(bad_entry)
    assert result["ok"] is False


def test_install_download_failure_is_reported_not_raised(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", side_effect=ValueError("Repo or branch not found")):
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)
    assert result["ok"] is False
    assert "not found" in result["error"]


def test_uninstall_removes_plugin_cache_tree_and_all_registered_skills(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    plugin_root = tmp_path / "cache" / "claude-plugins-official" / "amd-skills"
    assert plugin_root.exists()

    result = m.uninstall_skill("amd-skills")
    assert result["ok"] is True
    assert not plugin_root.exists()
    assert not any(e["id"] == "amd-skills" for e in m.load_installed())


def test_uninstall_unknown_skill_still_returns_not_found(tmp_path, monkeypatch):
    """Existing single-skill uninstall behavior must be unaffected by the
    plugin-bundle extension."""
    m = _reload_installer(tmp_path, monkeypatch)
    result = m.uninstall_skill("does-not-exist")
    assert result["ok"] is False


def test_bundled_skills_are_discoverable_via_shared_load_installed_skill_prompts(tmp_path, monkeypatch):
    """End-to-end check that registering a bundle by placing it under
    PLUGINS_DIR/cache is enough for shared.load_installed_skill_prompts() to
    pick both skills up — this is the "match the existing mechanism" wiring
    (config.USER_SKILL_DIRS), not a separate registration call."""
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    import shared
    other_root = tmp_path / "no-such-agents-dir"
    monkeypatch.setattr(shared, "_USER_SKILL_DIRS", [tmp_path / "skills", other_root, tmp_path / "cache"])
    # Namespaced ids (finding #2) — shared.py must derive the SAME ids the
    # installer registered under, not the bare "a"/"b" skill-folder names.
    id_a, id_b = "amd-skills__skills-a", "amd-skills__skills-b"
    try:
        shared.load_installed_skill_prompts()
        assert id_a in shared.SKILL_PROMPTS
        assert id_b in shared.SKILL_PROMPTS
        assert "Do a." in shared.SKILL_PROMPTS[id_a]
    finally:
        shared.SKILL_PROMPTS.pop(id_a, None)
        shared.SKILL_PROMPTS.pop(id_b, None)
        shared.SKILL_REQUIRES.pop(id_a, None)
        shared.SKILL_REQUIRES.pop(id_b, None)


# ---------------------------------------------------------------------------
# Finding #2 (HIGH) — skill_id must be namespaced by plugin_id: a plugin
# whose SKILL.md sits at the version root registers under {plugin_id} itself
# (never the version string), and two plugins bundling a same-named skill
# folder register under distinct ids instead of silently colliding.
# ---------------------------------------------------------------------------

def test_namespaced_skill_id_top_level_skill_md_uses_bare_plugin_id_not_version(tmp_path):
    from marketplace.installer import namespaced_skill_id
    version_dir = tmp_path / "cache" / "src" / "single-skill-plugin" / "1.0.0"
    version_dir.mkdir(parents=True)
    # skill_dir IS the version dir — the plugin ships one top-level SKILL.md.
    result = namespaced_skill_id("single-skill-plugin", version_dir, version_dir)
    assert result == "single-skill-plugin"
    assert result != "1.0.0"


def test_namespaced_skill_id_distinct_for_two_plugins_sharing_a_skill_folder_name(tmp_path):
    """Two plugins each bundling a 'getting-started' skill folder must
    register under distinct ids — this was the silent cross-plugin
    shadowing bug (first in rglob wins, the other vanishes)."""
    from marketplace.installer import namespaced_skill_id
    plugin_a_version_dir = tmp_path / "cache" / "src" / "plugin-a" / "1.0.0"
    plugin_b_version_dir = tmp_path / "cache" / "src" / "plugin-b" / "2.0.0"
    skill_a = plugin_a_version_dir / "getting-started"
    skill_b = plugin_b_version_dir / "getting-started"
    skill_a.mkdir(parents=True)
    skill_b.mkdir(parents=True)

    id_a = namespaced_skill_id("plugin-a", plugin_a_version_dir, skill_a)
    id_b = namespaced_skill_id("plugin-b", plugin_b_version_dir, skill_b)
    assert id_a != id_b
    assert id_a == "plugin-a__getting-started"
    assert id_b == "plugin-b__getting-started"


# ---------------------------------------------------------------------------
# Increment 2, item 2 — consent threaded through to the install record, and
# get_claude_plugins_official_capabilities() (server-side consent-gate
# support: fetch-and-inspect, never writes to disk).
# ---------------------------------------------------------------------------

def test_install_with_consented_true_records_consented_true(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY, consented=True)
    assert result["ok"] is True
    entry = next(e for e in m.load_installed() if e["id"] == "amd-skills")
    assert entry["consented"] is True


def test_get_capabilities_reports_skill_count_mcp_and_local_code_without_writing(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    files = dict(_bundle_files(with_tools=True))
    files[".mcp.json"] = b'{"mcpServers": {}}'
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=files):
        caps = m.get_claude_plugins_official_capabilities(_AMD_ENTRY)

    assert caps["ok"] is True
    assert caps["plugin_id"] == "amd-skills"
    assert caps["skill_count"] == 2
    assert caps["has_mcp"] is True
    assert caps["has_local_code"] is True

    # Read-only: nothing written to disk, nothing in the install index.
    plugin_root = tmp_path / "cache" / "claude-plugins-official" / "amd-skills"
    assert not plugin_root.exists()
    assert not any(e.get("id") == "amd-skills" for e in m.load_installed())


def test_get_capabilities_no_mcp_no_tools(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        caps = m.get_claude_plugins_official_capabilities(_AMD_ENTRY)
    assert caps["ok"] is True
    assert caps["has_mcp"] is False
    assert caps["has_local_code"] is False


def test_get_capabilities_reports_error_on_bad_source_url(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    bad_entry = dict(_AMD_ENTRY, plugin_source={"url": "https://gitlab.com/amd/skills", "path": "skills"})
    caps = m.get_claude_plugins_official_capabilities(bad_entry)
    assert caps["ok"] is False


# ---------------------------------------------------------------------------
# Increment 2, item 3 — MCP-teardown extension point (decision #9): a no-op
# today, but called unconditionally on plugin-bundle uninstall so Increment 3
# (Phase E) only has to fill in the body.
# ---------------------------------------------------------------------------

def test_uninstall_calls_mcp_teardown_hook(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    with patch.object(m, "_teardown_plugin_mcp") as mock_teardown:
        result = m.uninstall_skill("amd-skills")
    assert result["ok"] is True
    mock_teardown.assert_called_once_with("amd-skills")


def test_teardown_plugin_mcp_is_a_noop_today(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    assert m._teardown_plugin_mcp("anything") is None


# ---------------------------------------------------------------------------
# Increment 2, item 4 — command discovery during install + cleanup during
# uninstall (decision #11).
# ---------------------------------------------------------------------------

def _bundle_files_with_commands():
    files = dict(_bundle_files())
    files["commands/greet.md"] = b"---\ndescription: Greets someone\n---\nHello, $1!"
    return files


def test_install_discovers_and_registers_commands(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files_with_commands()):
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    assert result["ok"] is True
    assert result["command_ids"] == ["greet"]
    entry = next(e for e in m.load_installed() if e["id"] == "amd-skills")
    assert entry["command_ids"] == ["greet"]

    from marketplace import commands as commands_mod
    try:
        assert "greet" in commands_mod.COMMAND_REGISTRY
        assert commands_mod.COMMAND_REGISTRY["greet"]["plugin_id"] == "amd-skills"
    finally:
        commands_mod.COMMAND_REGISTRY.pop("greet", None)


def test_uninstall_deregisters_plugin_commands(tmp_path, monkeypatch):
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files_with_commands()):
        m.install_claude_plugins_official_plugin(_AMD_ENTRY)

    from marketplace import commands as commands_mod
    assert "greet" in commands_mod.COMMAND_REGISTRY
    try:
        result = m.uninstall_skill("amd-skills")
        assert result["ok"] is True
        assert "greet" not in commands_mod.COMMAND_REGISTRY
    finally:
        commands_mod.COMMAND_REGISTRY.pop("greet", None)


def test_reinstall_with_no_existing_record_and_diverged_sha_records_unknown_sha(tmp_path, monkeypatch):
    """Fix #5 (2026-08-07 milestone adversarial review): the same bug class
    as finding #6 (the sibling "existing record found" branch, already
    fixed) reintroduced in the "version dir exists, no install record"
    fallback — this call's freshly-resolved sha may not be what actually
    produced the bytes already on disk from an earlier crashed install, so
    it must be recorded as sha="" (unknown), never the diverged value."""
    m = _reload_installer(tmp_path, monkeypatch)
    version_dir = tmp_path / "cache" / "claude-plugins-official" / "amd-skills" / "2.0"
    for rel, data in _bundle_files().items():
        target = version_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    assert not any(e.get("id") == "amd-skills" for e in m.load_installed())

    diverged_entry = dict(
        _AMD_ENTRY,
        plugin_source=dict(_AMD_ENTRY["plugin_source"], sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"),
    )
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        result = m.install_claude_plugins_official_plugin(diverged_entry)

    assert result["ok"] is True
    entry = next(e for e in m.load_installed() if e["id"] == "amd-skills")
    assert entry["sha"] == ""


# ---------------------------------------------------------------------------
# Fix #1 (HIGH, 2026-08-07 milestone adversarial review) — TOCTOU: the
# consent-preview call and the real install call must be pinned to the same
# content. get_claude_plugins_official_capabilities() reports the concrete
# ref it fetched (resolved_ref); install_claude_plugins_official_plugin's
# pinned_ref param, when given, is used INSTEAD of re-resolving from the
# entry's (possibly since-changed) plugin_source.
# ---------------------------------------------------------------------------

def test_pinned_ref_prevents_toctou_content_divergence(tmp_path, monkeypatch):
    """Preview resolves ref "content-v1" and reports it as resolved_ref. The
    entry's plugin_source then "changes" (simulating a catalog refresh
    landing between the preview and install calls) to ref "content-v2",
    which would fetch DIFFERENT content if re-resolved from scratch. Passing
    the preview's resolved_ref through as pinned_ref must still install the
    ORIGINAL content-v1 content."""
    m = _reload_installer(tmp_path, monkeypatch)

    entry_no_sha = dict(_AMD_ENTRY, plugin_source=dict(_AMD_ENTRY["plugin_source"]))
    entry_no_sha["plugin_source"].pop("sha", None)
    entry_no_sha["plugin_source"]["ref"] = "content-v1"

    files_v1 = {"skills/a/SKILL.md": b"---\nname: a\nversion: 1.0\n---\nOriginal content."}
    files_v2 = {"skills/a/SKILL.md": b"---\nname: a\nversion: 1.0\n---\nDifferent content."}

    def fake_download(owner, repo, branch, subpath):
        if branch == "content-v1":
            return dict(files_v1)
        if branch == "content-v2":
            return dict(files_v2)
        raise AssertionError(f"unexpected ref {branch!r}")

    with patch.object(m.github_fetcher, "download_skill_tarball", side_effect=fake_download):
        caps = m.get_claude_plugins_official_capabilities(entry_no_sha)
    assert caps["ok"] is True
    assert caps["resolved_ref"] == "content-v1"

    diverged_entry = dict(
        entry_no_sha,
        plugin_source=dict(entry_no_sha["plugin_source"], ref="content-v2"),
    )

    with patch.object(m.github_fetcher, "download_skill_tarball", side_effect=fake_download):
        result = m.install_claude_plugins_official_plugin(
            diverged_entry, consented=True, pinned_ref=caps["resolved_ref"]
        )
    assert result["ok"] is True

    installed_text = (
        tmp_path / "cache" / "claude-plugins-official" / "amd-skills" / "1.0"
        / "skills" / "a" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "Original content." in installed_text
    assert "Different content." not in installed_text


def test_no_pinned_ref_falls_back_to_resolving_from_entry(tmp_path, monkeypatch):
    """Legacy/simplified callers that never captured a preview's resolved_ref
    (pinned_ref=None, the default) must keep today's best-effort behavior:
    resolve straight from the entry, same as before fix #1."""
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()) as mock_dl:
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY, consented=True)
    assert result["ok"] is True
    mock_dl.assert_called_once_with(
        "amd", "skills", _AMD_ENTRY["plugin_source"]["sha"], "skills"
    )


def test_two_plugins_with_same_skill_folder_name_both_discoverable_via_shared(tmp_path, monkeypatch):
    """End-to-end: two DIFFERENT plugins bundling a same-named
    'getting-started' skill folder must both land in shared.SKILL_PROMPTS
    under distinct namespaced ids, not one silently shadowing the other."""
    cache_root = tmp_path / "cache"
    plugin_a_dir = cache_root / "claude-plugins-official" / "plugin-a" / "1.0.0" / "getting-started"
    plugin_b_dir = cache_root / "claude-plugins-official" / "plugin-b" / "1.0.0" / "getting-started"
    plugin_a_dir.mkdir(parents=True)
    plugin_b_dir.mkdir(parents=True)
    (plugin_a_dir / "SKILL.md").write_text(
        "---\nname: getting-started\n---\nPlugin A getting started.", encoding="utf-8"
    )
    (plugin_b_dir / "SKILL.md").write_text(
        "---\nname: getting-started\n---\nPlugin B getting started.", encoding="utf-8"
    )

    import shared
    other_root = tmp_path / "no-such-agents-dir"
    monkeypatch.setattr(shared, "_USER_SKILL_DIRS", [tmp_path / "skills", other_root, cache_root])
    id_a, id_b = "plugin-a__getting-started", "plugin-b__getting-started"
    try:
        shared.load_installed_skill_prompts()
        assert id_a in shared.SKILL_PROMPTS
        assert id_b in shared.SKILL_PROMPTS
        assert "Plugin A" in shared.SKILL_PROMPTS[id_a]
        assert "Plugin B" in shared.SKILL_PROMPTS[id_b]
    finally:
        shared.SKILL_PROMPTS.pop(id_a, None)
        shared.SKILL_PROMPTS.pop(id_b, None)
        shared.SKILL_REQUIRES.pop(id_a, None)
        shared.SKILL_REQUIRES.pop(id_b, None)


# ---------------------------------------------------------------------------
# PR #10 review fix — pinned_ref validation. pinned_ref is client-controlled;
# it was trusted verbatim over the catalog's pinned sha. A modified client
# could install an arbitrary branch/tag/commit while the install was labeled
# "Verified" against the catalog sha. Now: if the catalog has a pinned sha,
# pinned_ref MUST equal it.
# ---------------------------------------------------------------------------

def test_pinned_ref_mismatching_catalog_sha_is_rejected(tmp_path, monkeypatch):
    """If the catalog entry has a pinned sha, a pinned_ref that doesn't match
    must be rejected — otherwise a modified client could install unverified
    content under a "Verified" label."""
    m = _reload_installer(tmp_path, monkeypatch)
    bad_ref = "a-different-sha-not-in-catalog"
    with patch.object(m.github_fetcher, "download_skill_tarball") as mock_dl:
        result = m.install_claude_plugins_official_plugin(
            _AMD_ENTRY, consented=True, pinned_ref=bad_ref
        )
    assert result["ok"] is False
    assert "sha" in result["error"].lower()
    assert bad_ref in result["error"]
    # The fetcher must NOT have been called — the validation must happen
    # before any network request.
    mock_dl.assert_not_called()


def test_pinned_ref_matching_catalog_sha_is_accepted(tmp_path, monkeypatch):
    """A pinned_ref that matches the catalog's pinned sha must succeed — this
    is the normal consent-preview → install flow."""
    m = _reload_installer(tmp_path, monkeypatch)
    correct_sha = _AMD_ENTRY["plugin_source"]["sha"]
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()) as mock_dl:
        result = m.install_claude_plugins_official_plugin(
            _AMD_ENTRY, consented=True, pinned_ref=correct_sha
        )
    assert result["ok"] is True
    mock_dl.assert_called_once_with("amd", "skills", correct_sha, "skills")


def test_pinned_ref_accepted_when_catalog_has_no_sha(tmp_path, monkeypatch):
    """When the catalog entry has NO pinned sha (the ~53/280 entries with only
    a ref), pinned_ref must be accepted unchecked — refs are mutable, and the
    TOCTOU scenario is exactly when the ref changed between preview and
    install."""
    m = _reload_installer(tmp_path, monkeypatch)
    entry_no_sha = dict(_AMD_ENTRY, plugin_source=dict(_AMD_ENTRY["plugin_source"]))
    entry_no_sha["plugin_source"].pop("sha", None)
    entry_no_sha["plugin_source"]["ref"] = "content-v1"

    files_v1 = {"skills/a/SKILL.md": b"---\nname: a\nversion: 1.0\n---\nOriginal content."}

    def fake_download(owner, repo, branch, subpath):
        assert branch == "content-v1"
        return dict(files_v1)

    with patch.object(m.github_fetcher, "download_skill_tarball", side_effect=fake_download):
        result = m.install_claude_plugins_official_plugin(
            entry_no_sha, consented=True, pinned_ref="content-v1"
        )
    assert result["ok"] is True


def test_install_record_stores_resolved_ref_not_catalog_sha(tmp_path, monkeypatch):
    """The install record must store the ACTUALLY-fetched ref (resolved_ref),
    not the catalog entry's sha — so installed-skills.json reflects what's on
    disk. For a pinned-sha install, resolved_ref == catalog sha (validated
    equal). For a legacy unpinned install, resolved_ref may differ."""
    m = _reload_installer(tmp_path, monkeypatch)
    with patch.object(m.github_fetcher, "download_skill_tarball", return_value=_bundle_files()):
        result = m.install_claude_plugins_official_plugin(_AMD_ENTRY, consented=True)
    assert result["ok"] is True
    records = m.load_installed()
    record = next(r for r in records if r["id"] == "amd-skills")
    assert record["sha"] == _AMD_ENTRY["plugin_source"]["sha"]
