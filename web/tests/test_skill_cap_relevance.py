"""The auto-skill cap must keep the skills a request needs, whatever order the candidates arrive in."""

import itertools

import app  # noqa: F401 — populates registries
from routes import chat

PROMPT = (
    "Create a schedule that runs every Friday at 12:00pm. Look at my calendar for the current week. "
    "For each meeting that has a transcript, save the original VTT to OneDrive and create one OneNote "
    "section for the week (once) and one page per meeting."
)
KEYWORD_HITS = ["calendar", "teams", "code_runner"]
CLASSIFIED = ["calendar", "teams", "onenote", "sharepoint", "file_ops", "shell_runner"]
CANDIDATES = ["calendar", "sharepoint", "file_ops", "code_runner", "teams", "onenote", "shell_runner"]


def _kept(order):
    ranked = sorted(
        order,
        key=lambda s: (chat._skill_provenance_rank(s), *chat._auto_skill_relevance(s, PROMPT, KEYWORD_HITS, CLASSIFIED)),
    )
    return set(ranked[: chat._MAX_AUTO_SKILLS])


def test_the_skills_the_request_needs_survive_in_any_candidate_order():
    expected = {"calendar", "teams", "onenote", "sharepoint"}
    for order in itertools.islice(itertools.permutations(CANDIDATES), 0, 5040, 37):
        assert _kept(list(order)) == expected


def test_a_skill_named_in_the_message_outranks_one_only_the_classifier_picked():
    named = chat._auto_skill_relevance("onenote", PROMPT, [], ["file_ops", "onenote"])
    unnamed = chat._auto_skill_relevance("file_ops", PROMPT, [], ["file_ops", "onenote"])
    assert named < unnamed


def test_short_skill_ids_match_whole_words_only():
    assert chat._auto_skill_relevance("ppt", "write a description", [], [])[0] == 0
