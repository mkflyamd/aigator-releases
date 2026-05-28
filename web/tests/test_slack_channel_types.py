"""Tests for Slack channel-type filter fix — Slack Connect channels (Issue #45)."""

import json
import pathlib
from unittest.mock import patch

SRC = (pathlib.Path(__file__).parent.parent / "routes" / "slack.py").read_text()


# ── Static source checks ──────────────────────────────────────────────────────

class TestExternalChannelHelperExists:
    """The route module must define a helper that fetches external_shared channels."""

    def test_fetch_external_channels_function_exists(self):
        assert "_fetch_external_channels" in SRC, (
            "routes/slack.py must define _fetch_external_channels() to fetch "
            "Slack Connect channels via conversations.list (the MCP tool does not "
            "support external_shared as a channel_types value)."
        )

    def test_external_shared_referenced_in_helper(self):
        helper_start = SRC.find("def _fetch_external_channels")
        assert helper_start != -1
        helper_body = SRC[helper_start: helper_start + 1200]
        assert "external_shared" in helper_body or "is_ext_shared" in helper_body, (
            "_fetch_external_channels must identify Slack Connect channels. "
            "Use is_ext_shared flag from conversations.list."
        )

    def test_helper_filters_by_is_ext_shared(self):
        helper_start = SRC.find("def _fetch_external_channels")
        assert helper_start != -1
        helper_body = SRC[helper_start: helper_start + 1200]
        assert "is_ext_shared" in helper_body, (
            "_fetch_external_channels must filter channels by is_ext_shared=True. "
            "Slack Connect channels appear as private_channel with that flag set."
        )

    def test_channels_endpoint_calls_fetch_external(self):
        route_start = SRC.find("async def slack_channels()")
        assert route_start != -1
        route_body = SRC[route_start: route_start + 2500]
        assert "_fetch_external_channels" in route_body, (
            "The slack_channels route must call _fetch_external_channels() and "
            "merge the results so Slack Connect channels appear in the pane."
        )

    def test_dm_search_still_has_im_mpim(self):
        dm_start = SRC.find("async def slack_dms")
        assert dm_start != -1
        block = SRC[dm_start: dm_start + 600]
        assert "im" in block and "mpim" in block, (
            "/api/slack/dms must still include im and mpim channel types."
        )


# ── Behavioural tests ─────────────────────────────────────────────────────────

def _make_conv_list_response(channels: list) -> dict:
    return {"ok": True, "channels": channels, "response_metadata": {"next_cursor": ""}}


def _run_fetch_external(web_api_mock):
    """Import routes.slack and call _fetch_external_channels with _slack_web_api patched."""
    import sys
    for key in list(sys.modules.keys()):
        if "routes.slack" in key or key == "routes.slack":
            del sys.modules[key]

    with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test-token"), \
         patch("skills.slack.mcp_client._load_token", return_value={"team_id": "TTEST"}):
        import routes.slack as slack_mod
        with patch.object(slack_mod, "_slack_web_api", side_effect=web_api_mock):
            return slack_mod._fetch_external_channels()


class TestFetchExternalChannelsLogic:
    """Unit-test _fetch_external_channels with a mocked Web API."""

    def test_returns_ext_shared_channel_with_is_ext_shared_flag(self):
        # Slack Connect channels come back as private_channel with is_ext_shared=True
        ch = {"id": "CEXT001", "name": "ext-amd-cohere", "is_ext_shared": True,
              "purpose": {"value": "Cohere"}, "topic": {"value": ""}}

        def fake_api(endpoint, params=None):
            types = (params or {}).get("types", "")
            if types == "private_channel":
                return _make_conv_list_response([ch])
            return _make_conv_list_response([])

        result = _run_fetch_external(fake_api)
        assert any(c["channel_id"] == "CEXT001" for c in result), (
            "_fetch_external_channels must include channels with is_ext_shared=True"
        )

    def test_excludes_non_ext_shared_channels(self):
        regular = {"id": "CINT001", "name": "general", "is_ext_shared": False,
                   "purpose": {"value": ""}, "topic": {"value": ""}}

        def fake_api(endpoint, params=None):
            return _make_conv_list_response([regular])

        result = _run_fetch_external(fake_api)
        assert not any(c["channel_id"] == "CINT001" for c in result), (
            "_fetch_external_channels must not include regular internal channels"
        )

    def test_tolerates_api_error_gracefully(self):
        def fake_api(endpoint, params=None):
            return {"ok": False, "error": "missing_scope"}

        result = _run_fetch_external(fake_api)
        assert isinstance(result, list), "Must return a list even on API error"
        assert result == [], "On error, should return empty list"
