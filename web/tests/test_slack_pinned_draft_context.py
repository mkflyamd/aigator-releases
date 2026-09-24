"""Slack pins must carry workspace identity before they can create a draft."""

from pathlib import Path
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
    assert "if (ctx.slack_url_workspace_id) pinMeta.slack_url_workspace_id" in shell_source


def test_safe_destination_rejection_is_not_scrubbed_into_false_success():
    app_source = (ROOT / "web" / "app.py").read_text(encoding="utf-8")
    chat_source = (ROOT / "web" / "routes" / "chat.py").read_text(encoding="utf-8")

    assert '"destination_context_missing", "workspace_mismatch"' in app_source
    assert "Do NOT call slack_send_message for this legacy pin" in chat_source


def test_slack_dm_draft_uses_a_neutral_message_icon():
    app_source = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    slack_dm = app_source.split("'slack-dm':", 1)[1].split("'slack-announce':", 1)[0]

    assert "paneIcon: '\\uD83D\\uDCAC'" in slack_dm
    assert "\\uD83D\\uDC8C" not in slack_dm
