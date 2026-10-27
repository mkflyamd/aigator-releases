"""Messages about meeting transcripts must select the teams skill, which owns
find_meeting_transcripts / save_meeting_transcript."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import app  # noqa: F401  (loads the skills the classifier menu is built from)
from routes.chat import _classify_skill_ids, _infer_skills_from_message


def test_transcript_messages_select_teams():
    for msg in (
        "Find the transcript for my AMD <> Cohere meeting and save it to OneDrive",
        "save the meeting transcripts from this week",
        "put the .vtt in my drive",
    ):
        assert "teams" in _infer_skills_from_message(msg), msg


def test_classifier_description_mentions_transcripts():
    assert "transcript" in _classify_skill_ids()["teams"].lower()


def test_existing_selection_unchanged():
    assert "teams" in _infer_skills_from_message("send a message to Bob")
    assert "teams" not in _infer_skills_from_message("what is on my calendar today")
