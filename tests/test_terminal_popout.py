from pathlib import Path

ROOT = Path(__file__).parent.parent


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_popout_page_attaches_to_the_shared_agent_session():
    html = _read("web", "static", "terminal-popout.html")
    js = _read("web", "static", "terminal-popout.js")
    assert "/static/terminal-popout.js" in html
    assert "/api/terminal/agent?session_id=" in js
    assert "'&seq=' +" in js


def test_popout_page_follows_the_gator_style_guide():
    html = _read("web", "static", "terminal-popout.html")
    js = _read("web", "static", "terminal-popout.js")
    # Guide: 4px thin scrollbar on both axes, thumb in --border2.
    assert ".xterm-viewport::-webkit-scrollbar" in html
    assert "height: 4px" in html
    assert "scrollbar-color: var(--border2) transparent" in html
    # Same light/dark terminal theme choice as the in-app terminals.
    assert "gator-theme-effective" in html
    assert "terminal_theme" in js


def test_pop_out_button_is_wired_from_the_tab_to_the_shell():
    tab = _read("web", "static", "tp-generic-agent-terminal.js")
    preload = _read("shell", "preload.js")
    main = _read("shell", "main.js")
    assert "window.gatorShell.popOutTerminal(sess.ptySessionId, sess.label)" in tab
    assert "ipcRenderer.invoke('terminal:pop-out', sessionId, label)" in preload
    assert "ipcMain.handle('terminal:pop-out'" in main
    assert "e.sender !== gatorView.webContents" in main


def test_popped_out_tab_gives_up_the_pty_and_takes_it_back_when_the_window_closes():
    tab = _read("web", "static", "tp-generic-agent-terminal.js")
    helpers = _read("web", "static", "tp-term-helpers.js")
    preload = _read("shell", "preload.js")
    main = _read("shell", "main.js")
    # The tab stops reconnecting and resizing the shared PTY while parked.
    assert "sess._dead || sess._parked" in tab
    assert "sess._parked) return;" in helpers
    # The shell tells the main window when a pop-out closes, and can close one.
    assert "terminal:popout-closed" in main and "terminal:popout-closed" in preload
    assert "ipcMain.handle('terminal:close-pop-out'" in main
    assert "closeTerminalPopout" in preload and "closeTerminalPopout" in tab
    # Pop-outs close with the main window so they cannot keep the app alive.
    assert "popout.destroy()" in main
    # Returning joins at the live end (seq=-1) instead of replaying stale output.
    assert "sess._outputSeq = -1" in tab
