import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import patch

from skills import _drafts
from skills import _rich_text as rt

ORIG = {
    "subject": "Plan",
    "from_addr": "amy@amd.com",
    "from_name": "Amy",
    "to_recipients": [],
    "cc_recipients": [],
}


def setup_function(function):
    _drafts._pending_drafts.clear()


def _params(result):
    return _drafts.get_draft(result["data"]["draft_id"])["params"]


def test_email_compose_converts_markdown_body():
    from skills.email.tools import _tool_email_open_compose

    res = _tool_email_open_compose(to="bob@amd.com", subject="S", body="Hi **Bob**")
    assert _params(res)["body_html"] == "<p>Hi <strong>Bob</strong></p>"
    assert res["data"]["body_html"] == "<p>Hi <strong>Bob</strong></p>"
    assert res["data"]["format_capabilities"] == rt.capabilities("email")


def test_email_compose_sanitizes_llm_body_html():
    from skills.email.tools import _tool_email_open_compose

    res = _tool_email_open_compose(
        to="bob@amd.com", subject="S", body="x", body_html="<p>x</p><script>alert(1)</script>"
    )
    assert _params(res)["body_html"] == "<p>x</p>"
    assert res["data"]["body_html"] == "<p>x</p>"


def test_email_reply_seeds_body_html():
    from skills.email.tools import _tool_reply_email

    with patch("skills.email.tools._fetch_original_email_context", return_value=ORIG):
        res = _tool_reply_email("AAMk1", "Thanks, **done**")
    params = _params(res)
    assert params["body"] == "Thanks, **done**"
    assert params["body_html"] == "<p>Thanks, <strong>done</strong></p>"
    assert res["data"]["body_html"] == params["body_html"]
    assert res["data"]["format_capabilities"] == rt.capabilities("email")


def test_email_forward_seeds_body_html():
    from skills.email.tools import _tool_forward_email

    with patch("skills.email.tools._fetch_original_email_context", return_value=ORIG):
        res = _tool_forward_email("AAMk1", "bob@amd.com", "FYI")
    params = _params(res)
    assert params["comment"] == "FYI"
    assert params["body_html"] == "<p>FYI</p>"
    assert res["data"]["format_capabilities"] == rt.capabilities("email")


def test_slack_dm_seeds_body_html_with_mention_and_format():
    from skills.slack.tools import _handle_slack_send_message

    with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1", "team": "AMD"}), patch(
        "skills.slack.tools._resolve_user", return_value="Alex"
    ):
        res = _handle_slack_send_message(
            user_id="U1",
            team_id="T1",
            message="Hi @Alex *now*",
            mentions=[{"user_id": "U1", "name": "Alex"}],
        )
    params = _params(res)
    assert params["message"] == "Hi <@U1> *now*"
    assert 'data-mention-id="U1"' in params["body_html"]
    assert "<strong>now</strong>" in params["body_html"]
    assert res["data"]["body_html"] == params["body_html"]
    assert res["data"]["format_capabilities"] == rt.capabilities("slack")
    assert "underline" not in res["data"]["format_capabilities"]


def test_slack_post_seeds_body_html():
    from skills.slack.tools import _handle_slack_send_message

    with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1", "team": "AMD"}), patch(
        "skills.slack.tools._api", return_value={"ok": False}
    ):
        res = _handle_slack_send_message(channel_id="C1", team_id="T1", message="ship _it_")
    params = _params(res)
    assert params["message"] == "ship _it_"
    assert params["body_html"] == "<p>ship <em>it</em></p>"
    assert res["data"]["format_capabilities"] == rt.capabilities("slack")


def test_teams_compose_seeds_body_html_with_mention_chip():
    from skills.teams.tools import _tool_teams_open_compose

    res = _tool_teams_open_compose(
        to="peer@amd.com",
        message="Hi @Alex McKinney,\n\nplease review.",
        mentions=[
            {
                "id": 9,
                "mentionText": "Alex McKinney",
                "mentioned": {"user": {"id": "AAD1", "displayName": "Alex McKinney"}},
            }
        ],
    )
    params = _params(res)
    expected = "<p>Hi " + rt.mention_span("AAD1", "Alex McKinney", "teams") + ",</p><p>please review.</p>"
    assert params["body_html"] == expected
    assert 'itemtype="http://schema.skype.com/Mention"' in params["message"]
    assert res["data"]["body_html"] == expected
    assert res["data"]["format_capabilities"] == rt.capabilities("teams")
