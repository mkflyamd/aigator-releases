"""Source-string wiring checks for the agent history UI (the DOM paths need a real browser)."""

from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
TERM = (STATIC / "tp-generic-agent-terminal.js").read_text(encoding="utf-8")
HANDOFF = (STATIC / "agent-handoff.js").read_text(encoding="utf-8")


def test_spawn_requests_carry_the_resume_id():
    assert TERM.count("resume_id: opts.resumeId") == 2  # _ocFetch and fetch branches


def test_activating_a_session_marks_it_viewed():
    assert "if (sess) sess._viewedAt = Date.now();" in TERM


def test_output_in_the_viewed_terminal_counts_as_seen():
    assert "if (window.agentHistory && agentHistory.isViewing(sess)) sess._viewedAt = sess._lastOutputAt;" in TERM


def test_handoff_dialog_takes_a_stored_session():
    assert "opts.stored" in HANDOFF
    assert "keepStateAgent: !!state.agent" in HANDOFF
    assert "_genAgentEnsureTermsContainer(opts.tabId)" in HANDOFF
