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


HANDOFF = (STATIC / "agent-handoff.js").read_text(encoding="utf-8")


def test_output_branch_tracks_bracketed_paste_mode():
    assert "agentHandoff.trackBracketedPaste(" in TERM
    assert "sess._bracketedPaste = paste.enabled;" in TERM
    assert "sess._bracketedPasteTail = paste.tail;" in TERM
    # tracked in the same branch that stamps the output clock
    assert TERM.index("sess._lastOutputAt = Date.now();") < TERM.index("sess._bracketedPaste = paste.enabled;")
    assert "const BRACKETED_ON = ESC + '[?2004h';" in HANDOFF
    assert "const BRACKETED_OFF = ESC + '[?2004l';" in HANDOFF


def test_readiness_requires_bracketed_paste():
    assert "if (!s.bracketedPaste) return false;" in HANDOFF
    # the probe deliver() uses builds the session-shaped object from the flag
    assert "bracketedPaste: !!sess._bracketedPaste," in HANDOFF
    assert "draftPrompt(sess, prompt, sessionProbe)" in HANDOFF


def test_paste_text_is_stripped_of_terminal_controls():
    assert r"\\u0000-\\u0008\\u000b-\\u001f\\u007f-\\u009f" in HANDOFF
    assert "replace(CONTROL_CHARS, '')" in HANDOFF


def test_continue_checks_for_a_start_in_flight_before_closing():
    assert "function _genAgentStartInFlight(tabId)" in TERM
    assert "state && state._starting" in TERM
    assert "_genAgentStartInFlight(tabId)" in HANDOFF
    click = HANDOFF.index("go.addEventListener('click'")
    block = HANDOFF[click : HANDOFF.index("overlay.appendChild(box);", click)]
    assert block.index("startInFlight(tabId)") < block.index("close();")
    assert "Another agent is still starting. Try again in a moment." in block


def test_malformed_prepare_response_is_caught_with_the_dialog_render():
    inner = HANDOFF[HANDOFF.index("async function openDialog") :]
    assert inner.index("prep = body;") < inner.index("renderDialog(prep") < inner.index("} catch (_) {")
    assert inner.index("} finally {") > inner.index("renderDialog(prep")
    assert "dialogBusy = false;" in inner
