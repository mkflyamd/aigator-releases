"""Regression coverage for browser-mode Slack OAuth popup handling (#169)."""

from pathlib import Path


APP_JS = (Path(__file__).parent.parent / "static" / "app.js").read_text(encoding="utf-8")


def _slack_signin_handler() -> str:
    start = APP_JS.index("slackSigninBtn.addEventListener('click', async () => {")
    end = APP_JS.index("\n  });\n\nasync function checkSlackStatus", start)
    return APP_JS[start:end]


def test_browser_oauth_preopens_popup_before_fetch_and_navigates_it():
    """Browser OAuth must preserve the click gesture and never reopen after await."""
    handler = _slack_signin_handler()

    preopen = "window.open('about:blank', 'slack-auth', 'width=600,height=700')"
    assert preopen in handler
    assert handler.rfind("if (!_inShell)", 0, handler.index(preopen)) != -1
    assert handler.index(preopen) < handler.index("await fetch('/api/auth/slack/start')")
    assert "popup.location.href = d.url" in handler
    assert "window.open(d.url, 'slack-auth', 'width=600,height=700')" not in handler


def test_browser_oauth_handles_terminal_popup_states_and_cleans_up():
    """Blocked, closed, failed, and completed browser OAuth flows release UI state."""
    handler = _slack_signin_handler()

    assert "Popup blocked — please allow popups for this site and try again." in handler
    assert "if (!popup || popup.closed)" in handler
    assert "ev.origin !== 'http://localhost:3118'" in handler
    assert "ev.source !== popup" in handler
    assert "slack-auth-ok" in handler
    assert "slack-auth-fail" in handler
    assert "const cleanup = () =>" in handler
    assert "window.removeEventListener('message', handler)" in handler
    assert "clearInterval(poll)" in handler
