"""slack_read_thread must reject an empty channel_id loudly.

Parity with the Teams fix: a Slack thread's replies are addressable only within
their channel. A malformed pin that lost its channel would otherwise call the
Slack API with a blank channel. The tool must return a clear error and must NOT
hit the network.
"""

from unittest.mock import patch


def test_read_thread_empty_channel_fails_loudly():
    from skills.slack import tools

    with (
        patch.object(tools, "is_slack_authenticated", return_value=True),
        patch.object(tools, "_api") as mock_api,
    ):
        result = tools._handle_slack_read_thread(
            channel_id="", message_ts="1785265966.526289"
        )
    assert "error" in result
    assert "channel_id" in result["error"].lower()
    # Must not have touched the Slack API with a blank channel.
    mock_api.assert_not_called()


def test_read_thread_whitespace_channel_fails_loudly():
    from skills.slack import tools

    with (
        patch.object(tools, "is_slack_authenticated", return_value=True),
        patch.object(tools, "_api") as mock_api,
    ):
        result = tools._handle_slack_read_thread(
            channel_id="   ", message_ts="1785265966.526289"
        )
    assert "error" in result
    mock_api.assert_not_called()


def test_read_thread_valid_channel_proceeds():
    """A real channel_id must proceed to the API (guard doesn't over-trigger)."""
    from skills.slack import tools

    with (
        patch.object(tools, "is_slack_authenticated", return_value=True),
        patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}),
        patch.object(
            tools, "_api", return_value={"ok": True, "messages": []}
        ) as mock_api,
    ):
        tools._handle_slack_read_thread(
            channel_id="C07UXNA49RB", message_ts="1785265966.526289"
        )
    # The guard must let a real channel through to the API call.
    mock_api.assert_called_once()
    called_params = mock_api.call_args.args[1]
    assert called_params["channel"] == "C07UXNA49RB"
