"""Source-string wiring checks for the handoff UI (the DOM paths need a real browser)."""

from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
TERM = (STATIC / "tp-generic-agent-terminal.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_scripts_load_before_terminal_module():
    limit = INDEX.index("agent-limit-detect.js")
    handoff = INDEX.index("agent-handoff.js")
    terminal = INDEX.index("tp-generic-agent-terminal.js")
    assert limit < terminal and handoff < terminal


def test_tab_has_continue_button_excluded_from_tab_gestures():
    assert "gtp-tab-handoff" in TERM
    assert "agentHandoff.openDialog" in TERM
    assert "e.target.classList.contains('gtp-tab-handoff')" in TERM
    assert "e.target === handoff" in TERM


def test_start_sends_handoff_id_and_delivers_prompt():
    assert "handoff_id: opts.handoffId" in TERM
    assert TERM.count("handoff_id: opts.handoffId") == 2  # _ocFetch and fetch branches
    assert "data.handoff_prompt" in TERM
    assert "agentHandoff.deliver(sess, data.handoff_prompt)" in TERM
    assert "sess._handedOffAt = Date.now()" in TERM


def test_project_agent_is_not_overwritten_by_a_handoff_tab():
    assert "const stateAgent = opts.keepStateAgent ? state.agent : agent;" in TERM
    assert "state.agent = stateAgent;" in TERM
    assert "current.agent !== stateAgent" in TERM
    assert "current.agent === stateAgent" in TERM


def test_restart_and_close_use_the_session_agent():
    assert "agent: sess.agent || state.agent," in TERM
    assert "keepStateAgent: sess.agent !== state.agent" in TERM


def test_output_feeds_limit_detector_and_activity_clock():
    assert "sess._lastOutputAt = Date.now();" in TERM
    assert "agentLimitDetect.feed(sess, msg.data, (s) => agentHandoff.offerOnLimit(s))" in TERM
