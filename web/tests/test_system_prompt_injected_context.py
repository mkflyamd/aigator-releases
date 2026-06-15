"""System prompt must tell the agent that injected context is REAL — Issue #15.

When the agent hits a capability gap (e.g. no github_create_comment tool) it would
retroactively call previously-injected context (a real uploaded file path) "fabricated"
— eroding trust in every prior answer. The system prompt needs an explicit rule:
injected context (file paths, pinned items, search results) is authentic, and an
inability to complete a task is a MISSING CAPABILITY, not fabricated context.
"""
import pathlib

SKILL = (pathlib.Path(__file__).parent.parent / "skills" / "aigator" / "SKILL.md").read_text(encoding="utf-8")
LOW = SKILL.lower()


def test_prompt_states_injected_context_is_real():
    assert "injected" in LOW
    assert "real" in LOW or "authentic" in LOW, \
        "prompt must state injected context (paths/pins/search results) is real/authentic (#15)"


def test_prompt_distinguishes_capability_gap_from_fabrication():
    # The rule must tie 'can't complete the task' to a missing capability,
    # explicitly NOT to fabricated/made-up context.
    assert "capability" in LOW, "prompt must name 'missing capability' as the cause of an incomplete task (#15)"
    assert any(w in LOW for w in ("fabricat", "made up", "made-up", "invent")), \
        "prompt must forbid labeling real injected context as fabricated/made up/invented (#15)"
