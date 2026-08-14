"""Slack in-body <@UID> mentions must resolve to display names (not raw IDs)
in the agent-facing tools (read_channel / read_thread / search)."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from skills.slack import tools as slack_tools


def test_mention_regex_resolves_ids(monkeypatch):
    names = {"U0ARYKYUC67": "Taekmin Kim", "U0AP079TMRS": "Ben Lee"}
    monkeypatch.setattr(slack_tools, "_resolve_user", lambda uid: names.get(uid, uid))

    assert (
        slack_tools._resolve_mentions_in_text("Hi <@U0ARYKYUC67> can you let me in?")
        == "Hi @Taekmin Kim can you let me in?"
    )

    assert (
        slack_tools._resolve_mentions_in_text(
            "will you join? I heard <@U0AP079TMRS> is off"
        )
        == "will you join? I heard @Ben Lee is off"
    )


def test_mention_with_pipe_form(monkeypatch):
    monkeypatch.setattr(slack_tools, "_resolve_user", lambda uid: "Taekmin Kim")
    # Slack sometimes sends <@UID|handle>
    assert (
        slack_tools._resolve_mentions_in_text("<@U0ARYKYUC67|taekmin> hi")
        == "@Taekmin Kim hi"
    )


def test_no_mentions_untouched(monkeypatch):
    monkeypatch.setattr(slack_tools, "_resolve_user", lambda uid: "X")
    assert (
        slack_tools._resolve_mentions_in_text("plain text, no mentions")
        == "plain text, no mentions"
    )
    assert slack_tools._resolve_mentions_in_text("") == ""


def test_slackbot_mention(monkeypatch):
    monkeypatch.setattr(
        slack_tools, "_resolve_user", lambda uid: "should-not-be-called"
    )
    assert (
        slack_tools._resolve_mentions_in_text("<@USLACKBOT> reminder")
        == "@Slackbot reminder"
    )


def test_resolve_users_in_messages_does_body_and_sender(monkeypatch):
    names = {"U0ARYKYUC67": "Taekmin Kim", "U999": "Sender Person"}
    monkeypatch.setattr(slack_tools, "_resolve_user", lambda uid: names.get(uid, uid))
    msgs = [{"user": "U999", "text": "ping <@U0ARYKYUC67> now"}]
    out = slack_tools._resolve_users_in_messages(msgs)
    assert out[0]["user"] == "Sender Person"
    assert out[0]["text"] == "ping @Taekmin Kim now"
