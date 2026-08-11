"""Phase A — claude-plugins-official catalog fetcher + coding classifier
(2026-08-07 plugin-marketplace milestone, decisions #2 and #8).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

import json
from unittest.mock import patch, MagicMock

from marketplace.registry import (
    classify_coding,
    fetch_claude_plugins_official,
    _normalize_claude_plugins_official_entry,
    _normalize_plugin_source,
    refresh_catalog,
)


# ---------------------------------------------------------------------------
# Coding classifier (decision #8) — advisory, never category-blocking.
# ---------------------------------------------------------------------------

def test_classify_amd_skills_like_entry_is_none_and_installable():
    """category=='development' must NOT trigger a coding classification —
    amd-skills is the motivating counter-example from the spec."""
    entry = {
        "name": "amd-skills",
        "description": "AMD's verified Agent Skills in one plugin: route image/audio "
                        "through local AI on Ryzen AI, serve LLMs on AMD Instinct GPUs.",
        "category": "development",
    }
    assert classify_coding(entry) == "none"
    normalized = _normalize_claude_plugins_official_entry(entry)
    assert normalized["installable"] is True
    assert normalized["coding_class"] == "none"


def test_classify_lsp_entry_is_coding_hard_and_not_installable():
    entry = {
        "name": "clangd-lsp",
        "description": "C/C++ language server (clangd) for code intelligence",
        "category": "development",
        "lspServers": {"clangd": {"command": "clangd"}},
    }
    assert classify_coding(entry) == "coding_hard"
    normalized = _normalize_claude_plugins_official_entry(entry)
    assert normalized["installable"] is False
    assert normalized["coding_class"] == "coding_hard"


def test_classify_lsp_by_name_suffix_alone():
    """A '-lsp' name suffix alone (no lspServers key) is still coding_hard."""
    entry = {"name": "rust-analyzer-lsp", "description": "Rust language server"}
    assert classify_coding(entry) == "coding_hard"


def test_classify_code_review_entry_is_coding_soft_and_installable():
    entry = {
        "name": "code-review",
        "description": "Reviews the current diff for correctness bugs and cleanups.",
        "category": "productivity",
    }
    assert classify_coding(entry) == "coding_soft"
    normalized = _normalize_claude_plugins_official_entry(entry)
    assert normalized["installable"] is True
    assert normalized["coding_class"] == "coding_soft"


def test_classify_plain_entry_is_none():
    entry = {"name": "asana", "description": "Manage Asana tasks and projects"}
    assert classify_coding(entry) == "none"


# ---------------------------------------------------------------------------
# Catalog parse — trimmed fixture shaped like the real marketplace.json.
# ---------------------------------------------------------------------------

FIXTURE_MARKETPLACE_JSON = {
    "$schema": "https://example.com/schema.json",
    "name": "claude-plugins-official",
    "plugins": [
        {
            "name": "amd-skills",
            "description": "AMD's verified Agent Skills in one plugin.",
            "author": {"name": "AMD"},
            "category": "development",
            "source": {
                "source": "git-subdir",
                "url": "https://github.com/amd/skills.git",
                "path": "skills",
                "ref": "main",
                "sha": "37d424162b9fe1b55f8665fb1e82d47e670e7385",
            },
            "skills": ["./local-ai-use", "./serving-llms-on-instinct"],
            "homepage": "https://developer.amd.com/",
        },
        {
            "name": "clangd-lsp",
            "description": "C/C++ language server (clangd) for code intelligence",
            "version": "1.0.0",
            "author": {"name": "Anthropic"},
            "source": "./plugins/clangd-lsp",
            "category": "development",
            "lspServers": {"clangd": {"command": "clangd"}},
        },
        {
            "name": "code-review",
            "description": "Reviews the current diff for correctness bugs.",
            "source": "./plugins/code-review",
            "category": "productivity",
        },
        # Malformed: missing "name" entirely — must be skipped, not raise.
        {
            "description": "This entry has no name and should be dropped",
            "category": "productivity",
        },
    ],
}


def _mock_response(payload: dict):
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read = MagicMock(return_value=body)
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_fetch_claude_plugins_official_parses_fixture():
    resp = _mock_response(FIXTURE_MARKETPLACE_JSON)
    with patch("marketplace.registry.urllib.request.urlopen", return_value=resp):
        skills = fetch_claude_plugins_official()

    # Malformed (missing name) entry is skipped without raising.
    assert len(skills) == 3
    by_id = {s["id"]: s for s in skills}
    assert set(by_id) == {"amd-skills", "clangd-lsp", "code-review"}

    for s in skills:
        assert s["tier"] == "Verified"
        assert s["source"] == "claude-plugins-official"

    assert by_id["amd-skills"]["coding_class"] == "none"
    assert by_id["amd-skills"]["installable"] is True
    assert by_id["amd-skills"]["plugin_source"]["sha"] == "37d424162b9fe1b55f8665fb1e82d47e670e7385"

    assert by_id["clangd-lsp"]["coding_class"] == "coding_hard"
    assert by_id["clangd-lsp"]["installable"] is False
    # String "source" (local, within the marketplace repo itself) is normalized
    # to the same dict shape as git-subdir entries.
    assert by_id["clangd-lsp"]["plugin_source"]["path"] == "plugins/clangd-lsp"
    assert by_id["clangd-lsp"]["plugin_source"]["url"] == (
        "https://github.com/anthropics/claude-plugins-official.git"
    )

    assert by_id["code-review"]["coding_class"] == "coding_soft"
    assert by_id["code-review"]["installable"] is True


def test_fetch_claude_plugins_official_network_failure_returns_empty():
    with patch(
        "marketplace.registry.urllib.request.urlopen",
        side_effect=Exception("network error"),
    ):
        result = fetch_claude_plugins_official()
    assert result == []


def test_fetch_claude_plugins_official_non_dict_json_returns_empty():
    resp = _mock_response(["not", "a", "dict"])
    # json.dumps(list) still decodes fine; the function should reject non-dict top-level.
    with patch("marketplace.registry.urllib.request.urlopen", return_value=resp):
        result = fetch_claude_plugins_official()
    assert result == []


def test_fetch_claude_plugins_official_missing_plugins_key_returns_empty():
    resp = _mock_response({"name": "claude-plugins-official"})
    with patch("marketplace.registry.urllib.request.urlopen", return_value=resp):
        result = fetch_claude_plugins_official()
    assert result == []


# ---------------------------------------------------------------------------
# Finding #1 (HIGH, Increment 1) — the flag defaulted False through
# Increments 1-4b: no install route wired install_claude_plugins_official_
# plugin() until Increment 2, and the full consent/coding-redirect/secret-
# completion path wasn't complete until Increment 4b, so surfacing these
# ~280 entries any earlier would have let POST /api/marketplace/install fall
# through to install_skill_md (writes raw GitHub HTML as SKILL.md, reports
# ok:true) or exposed an incomplete install/consent experience.
#
# Flipped to default-True after Increment 4b landed — the full path (catalog
# -> consent -> coding-redirect -> install -> MCP -> secret-completion ->
# command-discovery) is now built and adversarially reviewed end to end. See
# docs/pluginArchitecture.md's Implementation log for the full history.
# ---------------------------------------------------------------------------

def test_refresh_catalog_default_fetches_claude_plugins_official(tmp_path, monkeypatch):
    """Default (flag absent) must fetch — this is now the live behavior."""
    import marketplace.registry as registry
    monkeypatch.setattr(registry, "_CATALOG_CACHE_FILE", tmp_path / "catalog_cache.json")
    official_entry = {
        "id": "amd-skills", "name": "amd-skills",
        "tier": "Verified", "source": "claude-plugins-official",
    }
    with patch.object(registry, "fetch_claude_plugins_official", return_value=[official_entry]) as mock_official, \
         patch.object(registry, "fetch_anthropic_skills", return_value=[]):
        registry.refresh_catalog({})  # marketplace_claude_plugins_official_enabled absent
    mock_official.assert_called_once()

    data = json.loads((tmp_path / "catalog_cache.json").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in data["skills"]}
    assert by_id["amd-skills"]["source"] == "claude-plugins-official"


def test_refresh_catalog_explicitly_disabled_does_not_fetch_claude_plugins_official(tmp_path, monkeypatch):
    """An admin/operator can still explicitly opt out."""
    import marketplace.registry as registry
    monkeypatch.setattr(registry, "_CATALOG_CACHE_FILE", tmp_path / "catalog_cache.json")
    with patch.object(registry, "fetch_claude_plugins_official") as mock_official, \
         patch.object(registry, "fetch_anthropic_skills", return_value=[
             {"id": "some-skill", "name": "Some Skill"}
         ]):
        registry.refresh_catalog({"marketplace_claude_plugins_official_enabled": False})
    mock_official.assert_not_called()

    data = json.loads((tmp_path / "catalog_cache.json").read_text(encoding="utf-8"))
    assert all(s.get("source") != "claude-plugins-official" for s in data["skills"])


# ---------------------------------------------------------------------------
# Finding #3 (MED-HIGH) — claude-plugins-official (Verified) must be ordered
# before fetch_anthropic_skills() (Community) in refresh_catalog's sources
# list, since merge_catalogs keeps the first source on a colliding id.
# ---------------------------------------------------------------------------

def test_refresh_catalog_verified_wins_over_community_on_id_collision(tmp_path, monkeypatch):
    import marketplace.registry as registry
    monkeypatch.setattr(registry, "_CATALOG_CACHE_FILE", tmp_path / "catalog_cache.json")
    verified_entry = {
        "id": "frontend-design", "name": "frontend-design",
        "tier": "Verified", "source": "claude-plugins-official",
    }
    community_entry = {
        "id": "frontend-design", "name": "frontend-design",
        "tier": "Community", "source": "anthropic",
    }
    with patch.object(registry, "fetch_claude_plugins_official", return_value=[verified_entry]), \
         patch.object(registry, "fetch_anthropic_skills", return_value=[community_entry]):
        registry.refresh_catalog({"marketplace_claude_plugins_official_enabled": True})

    data = json.loads((tmp_path / "catalog_cache.json").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in data["skills"]}
    assert by_id["frontend-design"]["tier"] == "Verified"
    assert by_id["frontend-design"]["source"] == "claude-plugins-official"


# ---------------------------------------------------------------------------
# Finding #5 (MED) — "github" source shape ({repo, commit}, no url) must be
# normalized to a usable url + ref, same as the git-subdir dict shape.
# ---------------------------------------------------------------------------

def test_normalize_plugin_source_github_shape_synthesizes_url():
    raw = {"source": "github", "repo": "fullstory/skills", "commit": "abc123def"}
    result = _normalize_plugin_source(raw)
    assert result["url"] == "https://github.com/fullstory/skills.git"
    assert result["sha"] == "abc123def"


def test_normalize_plugin_source_repo_without_url_or_source_key():
    """Some entries (e.g. jfrog) omit the "source" discriminator entirely but
    still have the {repo, sha} shape — detect via "repo" present + "url" absent."""
    raw = {"repo": "jfrog/skills", "sha": "deadbeef"}
    result = _normalize_plugin_source(raw)
    assert result["url"] == "https://github.com/jfrog/skills.git"
    assert result["sha"] == "deadbeef"


def test_normalize_plugin_source_github_shape_sha_takes_precedence_over_commit():
    raw = {"source": "github", "repo": "owner/name", "commit": "commit-ref", "sha": "pinned-sha"}
    result = _normalize_plugin_source(raw)
    assert result["sha"] == "pinned-sha"
