"""gpt-5-family models + the Responses API (@ai-sdk/openai) probe/routing.

Background: OpenCode force-adds reasoning_effort for any model id containing
"gpt-5". Azure's gateway rejects `tools + reasoning_effort` on
/v1/chat/completions ("use /v1/responses instead"). The
@ai-sdk/openai-compatible adapter (gator-gateway) only speaks
chat/completions; @ai-sdk/openai speaks the Responses API and fixes it — but
not every backend supports /responses, so capability is probed per-profile
(cached) and gpt-5 models are only routed to a gator-openai provider when the
probe says the gateway actually supports it. Otherwise they stay on the
chat/completions gateway like everything else.
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from skills.opencode_agent import instance_manager as im


class TestIsGpt5Family:
    def test_is_gpt5_family(self):
        for m in ["gpt-5", "gpt-5.6-luna", "gpt-5.1-codex", "GPT-5-CHAT"]:
            assert im._is_gpt5_family(m), f"{m} should be classified gpt-5 family"
        for m in ["gpt-4o", "o3-mini", "o1", "gemini-2.5-pro", "Claude-Sonnet-5"]:
            assert not im._is_gpt5_family(m), f"{m} must not be classified gpt-5 family"


class TestBuildProviderConfigRouting:
    def _profile(self):
        return {
            "base_url": "https://gw/Unified",
            "api_key": "k",
            "api_key_header": "H",
            "active_model": "gpt-5.6-luna",
        }

    def test_build_config_routes_gpt5_to_openai_when_supported(self):
        config = im._build_provider_config(
            self._profile(),
            ["Claude-Sonnet-5", "gpt-5.6-luna", "gpt-4o", "o3-mini"],
            use_responses_for_gpt5=True,
        )
        assert config["provider"]["gator-openai"]["npm"] == "@ai-sdk/openai"
        openai_models = config["provider"]["gator-openai"]["models"]
        gateway_models = config["provider"]["gator-gateway"]["models"]
        assert "gpt-5.6-luna" in openai_models
        assert "gpt-4o" in gateway_models and "gpt-4o" not in openai_models
        assert "o3-mini" in gateway_models and "o3-mini" not in openai_models
        assert "gator-openai" in config["enabled_providers"]
        assert config["model"] == "gator-openai/gpt-5.6-luna"
        assert config["provider"]["gator-openai"]["options"]["baseURL"] == "https://gw/Unified/v1"

    def test_build_config_keeps_gpt5_on_gateway_when_unsupported(self):
        config = im._build_provider_config(
            self._profile(),
            ["Claude-Sonnet-5", "gpt-5.6-luna", "gpt-4o", "o3-mini"],
        )  # use_responses_for_gpt5 defaults to False
        assert "gator-openai" not in config["provider"]
        assert "gpt-5.6-luna" in config["provider"]["gator-gateway"]["models"]
        assert "gator-openai" not in config["enabled_providers"]

    def test_default_model_prefers_claude(self):
        profile = {
            "base_url": "https://gw/Unified",
            "api_key": "k",
            "api_key_header": "H",
        }  # no active_model
        config = im._build_provider_config(
            profile,
            ["Claude-Sonnet-5", "gpt-5.6-luna"],
            use_responses_for_gpt5=True,
        )
        assert config["model"].startswith("gator-anthropic/")

    def test_no_mcp_in_config(self):
        profile = {
            "base_url": "https://gw/Unified",
            "api_key": "k",
            "api_key_header": "H",
            "active_model": "gpt-5.6-luna",
        }
        models = ["Claude-Sonnet-5", "gpt-5.6-luna", "gpt-4o"]
        for use_responses in (True, False):
            config = im._build_provider_config(profile, models, use_responses_for_gpt5=use_responses)
            assert "mcp" not in config


class TestGatewaySupportsResponsesProbeCache:
    def test_probe_supported_caches_and_returns_true(self, monkeypatch, tmp_path):
        monkeypatch.setattr(im, "_RESPONSES_PROBE_CACHE", tmp_path / "c.json")
        monkeypatch.setattr(im, "_probe_responses_endpoint", lambda *a, **k: True)
        assert im._gateway_supports_responses("https://gw/v1", "k", "H", "gpt-5.6-luna") is True

        def _boom(*a, **k):
            raise AssertionError("should not re-probe — cached positive within TTL")
        monkeypatch.setattr(im, "_probe_responses_endpoint", _boom)
        assert im._gateway_supports_responses("https://gw/v1", "k", "H", "gpt-5.6-luna") is True

    def test_probe_unsupported_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setattr(im, "_RESPONSES_PROBE_CACHE", tmp_path / "c.json")
        monkeypatch.setattr(im, "_probe_responses_endpoint", lambda *a, **k: False)
        assert im._gateway_supports_responses("https://gw/v1", "k", "H", "gpt-5.6-luna") is False
