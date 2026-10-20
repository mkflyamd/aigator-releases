import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app
from skills import _drafts

MENTION = (
    '<span data-mention-id="{id}" data-mention-name="{name}" '
    'data-mention-service="{svc}">@{name}</span>'
)


def setup_function(function):
    _drafts._pending_drafts.clear()


def _approve(client, draft_id, body=None):
    from security import get_csrf_token

    return client.post(
        f"/api/drafts/{draft_id}/approve",
        headers={"X-CSRF-Token": get_csrf_token("testserver")},
        json=body,
    )


def _slack_api(posted):
    def api(api_method, params, method="GET"):
        if api_method == "conversations.info":
            return {"ok": True, "channel": {"id": "C1"}}
        if api_method == "conversations.open":
            return {"ok": True, "channel": {"id": "D1"}}
        if api_method == "chat.postMessage":
            posted.append(params)
            return {"ok": True, "ts": "1.2"}
        raise AssertionError(api_method)

    return api


def _send_slack(draft_type, params, body):
    posted: list[dict] = []
    did = _drafts.create_draft(draft_type, params, {})
    with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}), patch(
        "routes.slack._slack_web_api", side_effect=_slack_api(posted)
    ):
        r = _approve(TestClient(app), did, body)
    assert r.status_code == 200, r.text
    return posted[0]["text"]


POST = {"channel_id": "C1", "team_id": "T1", "message": "old", "body_html": "<p>old</p>"}
DM = {"user_id": "U9", "team_id": "T1", "message": "old", "body_html": "<p>old</p>"}
EDIT = (
    "<p><strong>Ship</strong> it "
    + MENTION.format(id="U1", name="Alex", svc="slack")
    + "</p>"
)


def test_slack_post_sends_mrkdwn_from_edited_html():
    assert _send_slack("slack-post", dict(POST), {"edited_html": EDIT}) == "*Ship* it <@U1>"


def test_slack_dm_sends_mrkdwn_from_edited_html():
    assert _send_slack("slack-dm", dict(DM), {"edited_html": EDIT}) == "*Ship* it <@U1>"


def test_slack_stored_body_html_is_rendered_without_edit():
    params = dict(POST, body_html="<p><strong>hi</strong></p>")
    assert _send_slack("slack-post", params, None) == "*hi*"


def test_slack_plain_edited_message_wins_over_stale_body_html():
    params = dict(POST, body_html="<p><strong>stale</strong></p>")
    assert _send_slack("slack-post", params, {"edited_message": "plain edit"}) == "plain edit"


def test_slack_legacy_draft_without_body_html_still_sends_message():
    assert _send_slack("slack-post", {"channel_id": "C1", "team_id": "T1", "message": "hi"}, None) == "hi"


def _send_teams(params, body):
    did = _drafts.create_draft("teams-message", params, {})
    with patch("routes.teams.tp_teams_send_message", return_value={"ok": True}) as send:
        r = _approve(TestClient(app), did, body)
    assert r.status_code == 200, r.text
    return send.call_args.args[0]


TEAMS = {
    "to": "bob@amd.com",
    "message": "old",
    "chat_id": "19:abc@thread.v2",
    "recipients": [],
    "mentions": [],
    "body_html": "<p>old</p>",
}
TEAMS_EDIT = (
    "<p><b>Hi</b> "
    + MENTION.format(id="AAD1", name="Alex", svc="teams")
    + '</p><script>alert(1)</script>'
)


def test_teams_edited_html_sends_html_with_skype_mentions():
    req = _send_teams(dict(TEAMS), {"edited_html": TEAMS_EDIT})
    assert req.html is True
    assert 'itemtype="http://schema.skype.com/Mention"' in req.message
    assert "<b>Hi</b>" in req.message
    assert "<script" not in req.message
    assert req.mentions[0]["mentioned"]["user"]["id"] == "AAD1"


def test_teams_stored_body_html_renders_without_edit():
    params = dict(TEAMS, body_html="<p>Hi " + MENTION.format(id="AAD1", name="Alex", svc="teams") + "</p>")
    req = _send_teams(params, None)
    assert req.html is True
    assert req.mentions[0]["mentioned"]["user"]["id"] == "AAD1"


def test_teams_legacy_draft_without_body_html_is_unchanged():
    legacy = {k: v for k, v in TEAMS.items() if k != "body_html"}
    req = _send_teams(legacy, None)
    assert req.message == "old"
    assert req.html is False
