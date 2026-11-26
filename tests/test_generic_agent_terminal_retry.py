"""Regression checks for generic-agent terminal reconnect state transitions."""

from pathlib import Path


SOURCE = (
    Path(__file__).parent.parent / "web" / "static" / "tp-generic-agent-terminal.js"
).read_text(encoding="utf-8")
STYLE = (Path(__file__).parent.parent / "web" / "static" / "style.css").read_text(
    encoding="utf-8"
)


def test_retry_counter_is_not_reset_when_websocket_opens():
    onopen = SOURCE.split("sess.ws.onopen = () => {", 1)[1].split("  };", 1)[0]
    assert "sess._retryAttempt = 0" not in onopen


def test_retry_counter_resets_only_after_visible_pty_output():
    output = SOURCE.split("if (msg.type === 'output') {", 1)[1].split("    } else if (msg.type === 'notready')", 1)[0]
    assert "const hasVisibleOutput = _genAgentIsVisibleOutput(msg.data);" in output
    assert "if (hasVisibleOutput) sess._retryAttempt = 0;" in output


def test_restart_overlay_removes_loading_layer_and_stays_clickable():
    overlay = SOURCE.split("function _genAgentShowRestartOverlay", 1)[1].split(
        "function _genAgent", 1
    )[0]
    css = STYLE.split(".oc-restart-overlay {", 1)[1].split("}", 1)[0]
    assert "_genAgentHideLoadingState(sess.tabId, sess.container)" in overlay
    assert "z-index: 20" in css
    assert "pointer-events: auto" in css


def test_restart_waits_for_backend_cleanup_before_spawning_replacement():
    restart = SOURCE.split("async function _genAgentRestartSession", 1)[1].split(
        "function _genAgentShowStartPrompt", 1
    )[0]
    assert "const cleanedUp = await _genAgentCloseBackendSession(state, sess);" in restart
    assert "_genAgentCloseSession(tabId, ptyId, true);" in restart
    assert (
        "_genAgentStart(tabId, sess.agent || state.agent, state.projectId, state.repoPath"
        in restart
    )
    assert restart.index("await _genAgentCloseBackendSession") < restart.index("_genAgentStart")


def test_restart_controls_use_awaited_restart_helper():
    assert "void _genAgentRestartSession(tabId, ptySessionId)" in SOURCE
    assert "void _genAgentRestartSession(sess.tabId, sess.ptySessionId);" in SOURCE
    assert "const restarted = await _genAgentRestartSession(sess.tabId, sess.ptySessionId);" in SOURCE


def test_suspended_terminal_offers_resume_and_restart_resumes_the_stored_session():
    handler = SOURCE.split("} else if (msg.type === 'suspended') {", 1)[1].split(
        "} else if (msg.type === 'exit')", 1
    )[0]
    assert "sess._dead = true;" in handler
    assert "sess._resumeId = msg.session_id || null;" in handler
    assert "_genAgentShowRestartOverlay(sess, msg.data || 'Suspended - click to resume');" in handler
    restart = SOURCE.split("async function _genAgentRestartSession", 1)[1].split(
        "function _genAgentShowStartPrompt", 1
    )[0]
    assert "resumeId: sess._resumeId || undefined," in restart
    assert "sess._resumeId ? 'Resume session' : 'Restart session'" in SOURCE


def test_a_failed_resume_offers_a_resume_retry_not_a_fresh_start():
    start = SOURCE.split("async function _genAgentStart(", 1)[1].split(
        "function _genAgentAttachTerminal", 1
    )[0]
    assert "(err && err.message) || 'Could not start ' + agent,\n          opts.resumeId," in start
    prompt = SOURCE.split("function _genAgentShowStartPrompt(", 1)[1].split(
        "function _genAgentHideStartPrompt", 1
    )[0]
    assert "errMsg, resumeId) {" in SOURCE
    assert "resumeId ? 'Resume' : 'Start'" in prompt
    assert "_genAgentStart(tabId, agent, projectId, repoPath, resumeId ? { resumeId } : undefined)" in " ".join(
        prompt.split()
    )


def test_each_terminal_tells_the_backend_whether_it_is_on_screen():
    report = SOURCE.split("function _genAgentReportVisible(", 1)[1].split("document.addEventListener", 1)[0]
    assert "JSON.stringify({ type: 'visible', value: visible })" in report
    assert "document.visibilityState === 'hidden'" in SOURCE.split("function _genAgentIsVisible(", 1)[1].split(
        "function _genAgentReportVisible", 1
    )[0]
    assert "document.addEventListener('visibilitychange'" in SOURCE
    activate = SOURCE.split("function _genAgentActivateSession(", 1)[1].split("function _genAgentNewSession", 1)[0]
    assert "state.order.forEach((id) => _genAgentReportVisible(state.sessions[id]));" in activate
    opened = SOURCE.split("sess.ws.onopen = () => {", 1)[1].split("sess.ws.onmessage", 1)[0]
    assert "_genAgentReportVisible(sess, true);" in opened
