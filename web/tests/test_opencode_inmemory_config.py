"""Track A — single-source in-memory OpenCode config injection.

Covers the security-critical Option-B repo-root MCP detection (§A6.1), the size
guardrail (§A3), the MCP-none invariant of the generated config, and the feature
flag. See docs/internal/OpenCodeConfigSingleSourceProposal.md (Track A).
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from skills.opencode_agent import instance_manager as im


def _write(repo, obj):
    (repo / "opencode.json").write_text(json.dumps(obj), encoding="utf-8")


# ── Option B: repo-root MCP detection (§A6.1) — conservative / fail-closed ────

class TestRepoRootMcpDetection:
    def test_no_file_ok(self, tmp_path):
        assert im._repo_root_has_runnable_mcp(str(tmp_path)) is False

    def test_no_mcp_key_ok(self, tmp_path):
        _write(tmp_path, {"model": "x", "provider": {}})
        assert im._repo_root_has_runnable_mcp(str(tmp_path)) is False

    def test_enabled_true_blocks(self, tmp_path):
        _write(tmp_path, {"mcp": {"s": {"type": "remote", "url": "u", "enabled": True}}})
        assert im._repo_root_has_runnable_mcp(str(tmp_path)) is True

    def test_omitted_enabled_blocks(self, tmp_path):
        # omitting `enabled` may default to enabled -> block
        _write(tmp_path, {"mcp": {"s": {"type": "remote", "url": "u"}}})
        assert im._repo_root_has_runnable_mcp(str(tmp_path)) is True

    def test_explicit_false_proceeds(self, tmp_path):
        _write(tmp_path, {"mcp": {"s": {"type": "remote", "url": "u", "enabled": False}}})
        assert im._repo_root_has_runnable_mcp(str(tmp_path)) is False

    def test_mixed_one_runnable_blocks(self, tmp_path):
        _write(tmp_path, {"mcp": {
            "ok": {"type": "remote", "url": "u", "enabled": False},
            "bad": {"type": "remote", "url": "u", "enabled": True},
        }})
        assert im._repo_root_has_runnable_mcp(str(tmp_path)) is True

    def test_non_false_value_blocks(self, tmp_path):
        # a non-boolean/odd value can't be classified confidently -> fail closed
        _write(tmp_path, {"mcp": {"s": {"type": "remote", "url": "u", "enabled": "false"}}})
        assert im._repo_root_has_runnable_mcp(str(tmp_path)) is True

    def test_malformed_json_fails_closed(self, tmp_path):
        (tmp_path / "opencode.json").write_text("{ this is not json ", encoding="utf-8")
        assert im._repo_root_has_runnable_mcp(str(tmp_path)) is True

    def test_mcp_wrong_shape_fails_closed(self, tmp_path):
        _write(tmp_path, {"mcp": ["not", "a", "dict"]})
        assert im._repo_root_has_runnable_mcp(str(tmp_path)) is True

    def test_entry_not_dict_fails_closed(self, tmp_path):
        _write(tmp_path, {"mcp": {"s": "just-a-string"}})
        assert im._repo_root_has_runnable_mcp(str(tmp_path)) is True


# ── _spawn_instance blocks (Option B) when a runnable repo-root MCP is present ─

class TestSpawnBlocksOnRepoMcp:
    def _patch_common(self, monkeypatch):
        import llm.registry as reg
        monkeypatch.setattr(im, "find_bundled_opencode", lambda: im.Path("fake-bin"))
        monkeypatch.setattr(reg, "get_active_profile", lambda: {"api_key": "k"})
        monkeypatch.setattr(reg, "available_models", lambda: ["m"])
        monkeypatch.setattr(im, "_inmemory_config_enabled", lambda: True)
        # _opencode_preflight runs `opencode --version` once per process (cached via
        # _preflight_ok) before the MCP guard below — stub it out like an already-warm
        # process, so this test's Popen trap only catches the real server spawn.
        monkeypatch.setattr(im, "_opencode_preflight", lambda *a, **k: None)

    def test_blocks_and_writes_nothing(self, tmp_path, monkeypatch):
        self._patch_common(monkeypatch)
        _write(tmp_path, {"mcp": {"s": {"type": "remote", "url": "u", "enabled": True}}})
        before = (tmp_path / "opencode.json").read_text(encoding="utf-8")
        # Popen must never be reached; make it explode if it is.
        monkeypatch.setattr(im.subprocess, "Popen", lambda *a, **k: pytest.fail("Popen reached"))
        with pytest.raises(RuntimeError, match="project-defined MCPs"):
            im._spawn_instance("proj", str(tmp_path))
        # repo file untouched
        assert (tmp_path / "opencode.json").read_text(encoding="utf-8") == before


# ── Size guardrail (§A3) ──────────────────────────────────────────────────────

class TestSizeGuard:
    def test_small_ok(self):
        im._guard_spawn_size('{"model":"x"}', ["a"], {"K": "v"})  # no raise

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows per-var UTF-16 limit")
    def test_oversize_config_raises_windows(self):
        huge = '{"x":"' + ("a" * 40000) + '"}'
        with pytest.raises(RuntimeError, match="too large"):
            im._guard_spawn_size(huge, ["a"], {"K": "v"})


# ── Generated config carries NO mcp key (Track A is MCP-none) ─────────────────

class TestConfigMcpNone:
    def test_build_provider_config_has_no_mcp(self):
        profile = {"api_key": "k", "api_key_header": "x-api-key",
                   "anthropic_url": "https://a", "base_url": "https://b"}
        cfg = im._build_provider_config(profile, ["claude-x", "gpt-y"])
        assert "mcp" not in cfg, "Track A must not propagate MCPs"


# ── Feature flag ──────────────────────────────────────────────────────────────

class TestFeatureFlag:
    def test_default_true(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "load_config", lambda: {})
        assert im._inmemory_config_enabled() is True

    def test_respects_false(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "load_config", lambda: {"opencode_inmemory_config": False})
        assert im._inmemory_config_enabled() is False
