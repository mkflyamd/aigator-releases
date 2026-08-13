"""Provider-level stream/header timeouts on generated opencode.json configs
(issue #156).

Root cause of the observed "silent wedge" hangs: a request dispatches, then
zero bytes arrive - no error, no close - for 8+ minutes with no self-recovery,
because no timeout was configured to make OpenCode give up. chunkTimeout
(no SSE chunk for N ms) turns that into a fast, properly logged error instead
of an indefinite freeze; headerTimeout catches "connected but never responded
at all". Deliberately no overall `timeout` cap - a legitimately long agentic
response streaming steadily for minutes must not be aborted for being long.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skills.opencode_agent import instance_manager as im


def _profile(**overrides):
    base = {
        "base_url": "https://gw/Unified",
        "api_key": "k",
        "api_key_header": "H",
        "active_model": "Claude-Sonnet-5",
    }
    base.update(overrides)
    return base


class TestProviderTimeouts:
    def test_gator_anthropic_has_chunk_and_header_timeout(self):
        config = im._build_provider_config(_profile(), ["Claude-Sonnet-5"])
        opts = config["provider"]["gator-anthropic"]["options"]
        assert opts["chunkTimeout"] == im._PROVIDER_CHUNK_TIMEOUT_MS
        assert opts["headerTimeout"] == im._PROVIDER_HEADER_TIMEOUT_MS

    def test_gator_gateway_has_chunk_and_header_timeout(self):
        config = im._build_provider_config(_profile(), ["gpt-4o"])
        opts = config["provider"]["gator-gateway"]["options"]
        assert opts["chunkTimeout"] == im._PROVIDER_CHUNK_TIMEOUT_MS
        assert opts["headerTimeout"] == im._PROVIDER_HEADER_TIMEOUT_MS

    def test_gator_openai_responses_provider_has_chunk_and_header_timeout(self):
        config = im._build_provider_config(
            _profile(active_model="gpt-5.6-luna"),
            ["gpt-5.6-luna"],
            use_responses_for_gpt5=True,
        )
        opts = config["provider"]["gator-openai"]["options"]
        assert opts["chunkTimeout"] == im._PROVIDER_CHUNK_TIMEOUT_MS
        assert opts["headerTimeout"] == im._PROVIDER_HEADER_TIMEOUT_MS

    def test_no_overall_timeout_cap_set(self):
        """A long-but-alive streaming response must not be aborted for being
        long - only chunkTimeout (silence) should be able to fire."""
        config = im._build_provider_config(_profile(), ["Claude-Sonnet-5"])
        for provider in config["provider"].values():
            assert "timeout" not in provider["options"]

    def test_chunk_timeout_is_generous_not_aggressive(self):
        # Both observed hangs sat silent for 8+ minutes with zero recovery -
        # this must be well under that, but generous enough to not fire on
        # normal tool-call/reasoning pauses (nowhere near a minute).
        assert 30_000 <= im._PROVIDER_CHUNK_TIMEOUT_MS <= 120_000
