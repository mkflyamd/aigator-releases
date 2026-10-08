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
    assert "_genAgentStart(tabId, state.agent, state.projectId, state.repoPath" in restart
    assert restart.index("await _genAgentCloseBackendSession") < restart.index("_genAgentStart")


def test_restart_controls_use_awaited_restart_helper():
    assert "void _genAgentRestartSession(tabId, ptySessionId)" in SOURCE
    assert "void _genAgentRestartSession(sess.tabId, sess.ptySessionId);" in SOURCE
    assert "const restarted = await _genAgentRestartSession(sess.tabId, sess.ptySessionId);" in SOURCE
