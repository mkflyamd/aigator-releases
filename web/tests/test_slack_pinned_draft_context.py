"""Slack pins must carry workspace identity before they can create a draft."""

from pathlib import Path
import re
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def test_missing_workspace_id_is_an_actionable_draft_rejection():
    from skills.slack.tools import _handle_slack_send_message

    with patch(
        "skills.slack.mcp_client._load_token",
        return_value={"team_id": "T_CONNECTED", "team": "AMD"},
    ):
        result = _handle_slack_send_message(channel_id="C_CHANNEL", message="Status update")

    assert result["error"] == "destination_context_missing"
    assert "reselect the channel" in result["_user_message"].lower()
    assert "_draft" not in result


def test_pinned_slack_context_preserves_workspace_identity_for_new_pins():
    shell_source = (ROOT / "shell" / "main.js").read_text(encoding="utf-8")

    assert "slack_url_workspace_id: ctx.team_id || ctx.team || null" in shell_source
    assert re.search(
        r"if \(ctx\.slack_url_workspace_id\)\s+pinMeta\.slack_url_workspace_id",
        shell_source,
    )


def test_safe_destination_rejection_is_not_scrubbed_into_false_success():
    app_source = (ROOT / "web" / "app.py").read_text(encoding="utf-8")
    chat_source = (ROOT / "web" / "routes" / "chat.py").read_text(encoding="utf-8")

    assert 'result.get("code") == "workspace_mismatch"' in app_source
    assert "Do NOT call slack_send_message for this legacy pin" in chat_source


def test_slack_dm_draft_uses_a_neutral_message_icon():
    app_source = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    slack_dm = app_source.split("'slack-dm':", 1)[1].split("'slack-announce':", 1)[0]

    assert "paneIcon: '\\uD83D\\uDCAC'" in slack_dm
    assert "\\uD83D\\uDC8C" not in slack_dm


def test_channel_picker_offers_active_slack_channel_without_directory_access():
    app_source = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "const addCurrentSlackChannel" in app_source
    assert "channel_id: channelId" in app_source
    assert "team_id: slackStatus.team_id" in app_source
    assert "addCurrentSlackChannel();" in app_source


def test_channel_picker_uses_known_channels_when_slack_directory_is_restricted():
    slack_source = (ROOT / "web" / "routes" / "slack.py").read_text(encoding="utf-8")
    app_source = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "Directory access can be restricted" in slack_source
    assert "_KNOWN_CHANNELS.items()" in slack_source
    assert "existing.channel_name = name" in app_source


def test_shell_seeds_known_channel_cache_from_native_slack_sidebar():
    shell_source = (ROOT / "shell" / "main.js").read_text(encoding="utf-8")

    assert "recordSlackSidebarChannels" in shell_source
    assert "[data-qa-channel-sidebar-channel-id]" in shell_source
    assert ".p-channel_sidebar__name" in shell_source
    assert "scanSlackSidebar(lastCtx.team)" in shell_source


def test_seen_channels_are_bound_to_oauth_team_not_enterprise_url_id():
    slack_source = (ROOT / "web" / "routes" / "slack.py").read_text(encoding="utf-8")

    assert "observed channels to the connected OAuth identity" in slack_source
    assert 'team_id = (_load_token().get("team_id")' in slack_source


def test_slack_channel_empty_state_matches_mention_cta_experience():
    app_source = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "function _renderSlackChannelEmptyState" in app_source
    assert "No matching Slack channel" in app_source
    assert "Open Slack channel" in app_source
    assert "Reconnect Slack" in app_source
