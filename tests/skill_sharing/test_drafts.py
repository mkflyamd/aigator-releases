from unittest.mock import patch

import pytest

from skills._sharing import drafts
from skills._sharing.errors import ShareError


def _build(channel, people=("a@contoso.com", "b@contoso.com")):
    return drafts.build(channel, skill_id="my-skill", people=list(people), message="Link: aigator://share?d=abc")


def test_email_makes_one_draft_for_everyone():
    with patch("skills.email.tools._tool_email_open_compose", return_value={"_draft": "email-send"}) as compose:
        out = _build("email")
    compose.assert_called_once()
    kwargs = compose.call_args.kwargs
    assert kwargs["to"] == "a@contoso.com,b@contoso.com"
    assert "my-skill" in kwargs["subject"]
    assert kwargs["body"] == "Link: aigator://share?d=abc"
    assert out == {"drafts": [{"_draft": "email-send"}], "unmatched": []}


def test_teams_makes_one_draft_for_everyone():
    with patch("skills.teams.tools._tool_teams_open_compose", return_value={"_draft": "teams-message"}) as compose:
        out = _build("teams")
    compose.assert_called_once_with(to="a@contoso.com,b@contoso.com", message="Link: aigator://share?d=abc")
    assert out["drafts"] == [{"_draft": "teams-message"}]


def test_teams_failure_is_a_channel_error():
    with patch("skills.teams.tools._tool_teams_open_compose", return_value={"error": "Resolve the person first."}):
        with pytest.raises(ShareError) as err:
            _build("teams")
    assert err.value.code == "channel_unavailable"


def _slack_user(email, uid):
    return {"user_id": uid, "email": email, "team_id": "T1"}


def test_slack_drafts_one_dm_per_matched_person_and_lists_the_rest():
    def search(query, **kw):
        return {"users": [_slack_user("a@contoso.com", "U1")]} if query == "a@contoso.com" else {"users": []}

    with (
        patch("skills.slack.tools._handle_slack_search_users", side_effect=search),
        patch("skills.slack.tools._handle_slack_send_message", return_value={"_draft": "slack-dm"}) as send,
    ):
        out = _build("slack")
    send.assert_called_once_with(user_id="U1", team_id="T1", message="Link: aigator://share?d=abc")
    assert out == {"drafts": [{"_draft": "slack-dm"}], "unmatched": ["b@contoso.com"]}


def test_slack_matches_the_exact_address_not_a_substring():
    users = [_slack_user("ab@contoso.com", "U9")]
    with (
        patch("skills.slack.tools._handle_slack_search_users", return_value={"users": users}),
        patch("skills.slack.tools._handle_slack_send_message") as send,
    ):
        with pytest.raises(ShareError) as err:
            _build("slack", people=["b@contoso.com"])
    send.assert_not_called()
    assert err.value.code == "channel_unavailable"


def test_slack_not_connected_is_a_channel_error():
    with patch("skills.slack.tools._handle_slack_search_users", return_value={"error": "not_authed", "result": "Slack is not connected."}):
        with pytest.raises(ShareError) as err:
            _build("slack")
    assert err.value.code == "channel_unavailable"
    assert "Slack is not connected" in err.value.message


def test_unknown_channel_is_refused():
    with pytest.raises(ShareError) as err:
        _build("sms")
    assert err.value.code == "invalid"
