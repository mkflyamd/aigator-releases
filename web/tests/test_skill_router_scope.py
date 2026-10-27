"""The direct router answers with one no-tools call, so it may only take messages that are a pure lookup."""

import pytest

import app  # noqa: F401 — registers the built-in intents
from skill_router import match_intent

SCHEDULE_PROMPT = (
    "Create a schedule that runs every Friday at 12:00. Look at my calendar for the current week. "
    "For each meeting that has a transcript, save the original VTT to OneDrive and create one "
    "OneNote section for the week and one page per meeting. Don't send anything to anyone."
)


@pytest.mark.parametrize(
    "msg,tool",
    [
        ("check my calendar", "read_calendar"),
        ("What meetings do I have today?", "read_calendar"),
        ("what's on my calendar", "read_calendar"),
        ("can you show me my schedule today please", "read_calendar"),
        ("check my inbox", "read_email"),
        ("show my unread email", "read_email"),
        ("what are my tickets", "list_jira_issues"),
        ("check teams", "read_teams_chats"),
    ],
)
def test_pure_lookups_still_go_direct(msg, tool):
    assert match_intent(msg)["tool"] == tool


@pytest.mark.parametrize(
    "msg",
    [
        SCHEDULE_PROMPT,
        "schedule a weekly check of my calendar",
        "every friday look at my calendar and email me a summary",
        "remind me daily to check my calendar",
        "check my calendar for tomorrow",
        "check my calendar and save the transcripts to onedrive",
        "check my inbox and reply to the first one",
    ],
)
def test_anything_beyond_the_lookup_is_left_to_the_model(msg):
    assert match_intent(msg) is None
