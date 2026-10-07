"""A short follow-up ("try fireworks") carries forward the skills the chat has been using.

Slack's keywords are phrases ("in slack"), so a chat that just says "Slack" never matched,
the Slack tools were not offered, and the model's call was rejected with tool_not_offered.
"""

import pathlib

import app  # noqa: F401 — importing populates the skill registries at startup
from routes.chat import _skills_in_history_text

CHAT_SRC = (pathlib.Path(__file__).parent.parent / "routes" / "chat.py").read_text(encoding="utf-8")


def test_a_chat_that_names_slack_carries_slack_forward():
    assert "slack" in _skills_in_history_text("slack search for release came back empty. want me to retry?")


def test_a_skill_name_inside_a_longer_word_does_not_carry_forward():
    assert "slack" not in _skills_in_history_text("use the slack-gif-creator skill")
    assert "slack" not in _skills_in_history_text("the slackware install")


def test_keyword_phrases_still_carry_forward():
    assert "jira" in _skills_in_history_text("create a ticket for this")


def test_failure_banner_is_held_back_when_an_auto_activation_retry_follows():
    assert "_held_stall" in CHAT_SRC
    held = CHAT_SRC.index("_held_stall = chunk")
    sent = CHAT_SRC.index("yield _held_stall")
    retry = CHAT_SRC.index("_all_active.extend(_new_skills)")
    assert held < sent < retry, "the banner is only sent when no retry follows"
