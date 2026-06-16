"""Auto skill-detection must chain MULTIPLE dependent skills in one turn — Issue #70.

A skill can need several others at once (the reported repro needs both /jira and
/outlook). The model names them as bare `/jira` / `/outlook` mentions. The detector
regex was fixed to catch bare tokens, but the retry loop still used
`_SKILL_REQUEST_RE.search(...)` — only the FIRST match — and capped
`_MAX_AUTO_ACTIVATE_RETRIES = 1`, so only one of the two ever activated and the
turn dead-ended asking the user to activate a skill that never loaded.

The fix collects ALL named, valid, not-yet-active skill ids from the turn (resolved
to internal ids, de-duplicated) and activates them together before the retry.
"""
import pathlib

import app  # noqa: F401 — importing populates the skill registries at startup
import shared
from routes.chat import _detect_requested_skills

CHAT_SRC = (pathlib.Path(__file__).parent.parent / "routes" / "chat.py").read_text(encoding="utf-8")


def test_detects_both_skills_named_in_one_turn():
    assert "jira" in shared.SKILL_PROMPTS, "jira skill must be registered at startup"
    assert "email" in shared.SKILL_PROMPTS, "email skill must be registered at startup"
    turn = "I need more tools to do this:\n/jira\n/outlook\n"
    found = _detect_requested_skills(turn, already_active=set())
    # /outlook resolves to the internal id 'email'; both must be collected (#70).
    assert "jira" in found and "email" in found, found


def test_skips_already_active_and_dedupes():
    turn = "/jira\n/jira\n/teams"
    found = _detect_requested_skills(turn, already_active={"jira"})
    assert found.count("teams") == 1, found
    assert "jira" not in found, "already-active skills must not be re-activated (#70)"


def test_ignores_unknown_tokens():
    found = _detect_requested_skills("/not-a-real-skill\n/also-fake", already_active=set())
    assert found == [], found


def test_never_auto_activates_gated_skills():
    # shell_runner/code_runner expose powerful tools and must go through the
    # explicit approval gate — the model naming them mid-turn must not self-grant
    # them via the auto-activate path (#70 security guard).
    found = _detect_requested_skills("/code_runner\n/shell_runner\n/jira", already_active=set())
    assert "code_runner" not in found and "shell_runner" not in found, found
    assert "jira" in found, "non-gated skills must still activate"


def test_loop_activates_all_detected_skills_not_just_first():
    # The retry loop must consult the multi-skill detector, not the single-match
    # `.search()` path that activated only the first mention.
    assert "_detect_requested_skills(" in CHAT_SRC, \
        "retry loop must use the multi-skill detector (#70)"
    # And it must allow more than one auto-activation pass so chained deps resolve.
    assert "_MAX_AUTO_ACTIVATE_RETRIES = 1" not in CHAT_SRC, \
        "a single retry can't cover multi-skill chains (#70)"
