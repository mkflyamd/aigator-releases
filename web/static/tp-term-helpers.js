// tp-term-helpers.js — shared xterm.js helpers used by the generic-agent
// terminal (tp-generic-agent-terminal.js). Extracted from the now-removed
// tp-opencode-terminal.js (deprecated serve+attach path) so the bare/generic
// agents keep the same terminal behavior without depending on dead code.
//
// Loaded before tp-generic-agent-terminal.js (see index.html script order).

const _OC_FETCH_TIMEOUT_MS = 45000;

function _ocFetch(url, opts) {
  const finalOpts = { ...opts, signal: AbortSignal.timeout(_OC_FETCH_TIMEOUT_MS) };
  return typeof _caFetchWithCsrfRetry === 'function'
    ? _caFetchWithCsrfRetry(url, finalOpts)
    : fetch(url, finalOpts);
}

function _ocXtermTheme() {
  // Delegate to the code agent's config-driven theme (dark/light/auto).
  // Default dark — TUI apps (Crush, Claude Code) use color schemes designed
  // for dark backgrounds. Users can toggle via the topbar button.
  if (typeof _caXtermTheme === 'function') return _caXtermTheme();
  return { background: '#0b0d12', foreground: '#d4d4d4', cursor: '#d4d4d4' };
}

// Output right after the user's own input (typing, a click's focus/mouse report),
// a resize we sent, or a (re)connect is an echo or repaint, not the agent working.
const _OC_ECHO_QUIET_MS = 1500;

function _ocNoteEcho(sess) {
  sess._quietUntil = Date.now() + _OC_ECHO_QUIET_MS;
}

function _ocSpawnTerm(sess) {
  /* global Terminal, FitAddon */
  sess.term = new Terminal({
    fontFamily: 'Consolas, "Courier New", monospace',
    fontSize: 13,
    cursorBlink: true,
    theme: _ocXtermTheme(),
    scrollback: 5000,
    // convertEol: false — TUI apps (Crush, Claude Code, OpenCode) send raw
    // ANSI escape sequences with precise cursor positioning and their own \r\n
    // line endings. convertEol: true would convert their \n to \r\n, turning
    // their \r\n into \r\r\n — an extra carriage return that garbles popup
    // overlays and full-screen TUI layouts. The bottom-dock terminal.js uses
    // convertEol: true because it's designed for shell command output (bare
    // \n from a command should wrap); this terminal is for TUI apps.
    convertEol: false,
  });
  sess.fitAddon = new FitAddon.FitAddon();
  sess.term.loadAddon(sess.fitAddon);
  sess.term.open(sess.container);

  sess.container.addEventListener(
    'paste',
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      const txt = (e.clipboardData || window.clipboardData).getData('text');
      if (txt && sess.term) sess.term.paste(txt);
    },
    true,
  );

  sess.term.attachCustomKeyEventHandler((e) => {
    if (e.type !== 'keydown') return true;
    if (e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey && (e.key === 'c' || e.key === 'C')) {
      if (sess.term.hasSelection()) {
        const sel = sess.term.getSelection();
        if (sel) navigator.clipboard.writeText(sel).catch(() => {});
        sess.term.clearSelection();
        return false;
      }
      return true;
    }
    if (e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey && (e.key === 'v' || e.key === 'V')) {
      return false;
    }
    if (e.ctrlKey && e.shiftKey && !e.altKey && !e.metaKey && (e.key === 'v' || e.key === 'V')) {
      navigator.clipboard
        .readText()
        .then((txt) => {
          if (txt && sess.term) sess.term.paste(txt);
        })
        .catch(() => {});
      return false;
    }
    return true;
  });

  sess.term.onData((data) => {
    if (!(sess.ws && sess.ws.readyState === WebSocket.OPEN)) return;
    // Swallow xterm's automatic Device-Attributes reply at startup — but ONLY
    // for the bare shell agent ('terminal'), where the reply echoes as a stray
    // "[?1;2c" after the drawn prompt. TUI agents (opencode-bare, crush, codex,
    // claude) NEED the DA1 reply forwarded: they send ESC[c during their TUI
    // initialization and wait for the response before drawing their UI. Dropping
    // it for those agents causes them to stall and render a blank or cursor-only
    // pane — exactly the symptom we saw with opencode.
    if (sess.agent === 'terminal' && !sess._sawUserInput) {
      if (/^\x1b\[\?[0-9;]*c$/.test(data)) {
        return; // startup DA1 auto-reply for bare shell — drop it
      }
      if (!/^\x1b\[[0-9;]*[a-zA-Z]$/.test(data)) {
        sess._sawUserInput = true;
      }
    }
    _ocNoteEcho(sess);
    sess.ws.send(JSON.stringify({ type: 'input', data }));
  });
}

// A pane squeezed below a few rows is mid-layout, not a size worth telling the agent about.
const _OC_MIN_FIT_HEIGHT = 60;

// force: also tell the PTY when xterm's own size is unchanged. Needed when the
// websocket (re)opens, because the PTY's size is independent of xterm's and may
// be stale (e.g. a reattached shell keeps the size of its previous viewer).
function _ocFit(sess, force) {
  if (!sess || !sess.fitAddon || !sess.term || sess._parked) return;
  // The terminal holds a replayed size, not the pane's, until the replay ends.
  if (sess._replayingSizes && sess._replayWs === sess.ws) return;
  const el = sess.container;
  if (!el || !el.offsetParent || el.clientWidth < 40 || el.clientHeight < _OC_MIN_FIT_HEIGHT) {
    // A hidden panel cannot be measured, but a (re)connect still has to tell the
    // PTY the last fitted size so a TUI redraws. A never-fitted xterm still holds
    // its 80x24 default, which would be a bogus size for the PTY.
    if (force && sess._ocFitted) _ocSendSize(sess);
    return;
  }
  const prevCols = sess.term.cols;
  const prevRows = sess.term.rows;
  try {
    sess.fitAddon.fit();
    sess._ocFitted = true;
  } catch (_) {
    /* not visible yet */
  }
  // Output written while hidden leaves xterm's scroll area a screen short; fit() no-ops at the same size.
  try {
    sess.term._core?.viewport?.syncScrollArea?.(true);
  } catch (_) {
    /* xterm internals changed */
  }
  // Only send resize + clear if dimensions actually changed. Sending a
  // resize when nothing changed makes TUI apps redraw needlessly; clearing
  // the buffer on a no-op resize would wipe the screen for nothing.
  const changed = sess.term.cols !== prevCols || sess.term.rows !== prevRows;
  if (!changed && !force) return;
  // A post-start reset clears the TUI frame xterm has already painted. That
  // is especially visible for a newly opened second session: it receives and
  // renders OpenCode's first frame, then this late fit wipes it and leaves a
  // blank canvas until OpenCode eventually redraws. A reset is safe only
  // before the session has produced visible output; after that, let the PTY's
  // resize notification drive the application's normal redraw.
  if (changed && !sess._hasOutput) sess.term.reset();
  if (changed && sess._hasOutput) {
    sess._trimArmed = true;
    _ocTrimSoon(sess);
  }
  if (_ocSendSize(sess)) _ocNoteEcho(sess);
}

// The agent repaints its whole screen on a real resize and xterm's reflow wraps the old one
// differently, so a screenful of ghost lands in scrollback. Once the repaint has gone quiet, drop
// the scrollback in xterm only (nothing goes to the PTY; History keeps the full session). Skipped
// while the user has scrolled up or the alternate buffer is showing.
const _OC_TRIM_QUIET_MS = 300;

function _ocTrimSoon(sess) {
  clearTimeout(sess._trimTimer);
  sess._trimTimer = setTimeout(() => {
    const term = sess.term;
    if (!sess._trimArmed || !term || sess._closing) return;
    sess._trimArmed = false;
    term.write('', () => {
      const buf = term.buffer.active;
      if (buf.type !== 'normal' || buf.viewportY !== buf.baseY) return;
      term.write('\x1b[3J');
    });
  }, _OC_TRIM_QUIET_MS);
}

// Every real size change makes the agent repaint its whole screen and leave a ghost copy, so the
// size goes out once per websocket and again only when it changes. A new socket always sends: its
// PTY may hold a stale size.
function _ocSendSize(sess) {
  const ws = sess.ws;
  if (!sess.term || !ws || ws.readyState !== WebSocket.OPEN) return false;
  const { cols, rows } = sess.term;
  if (sess._sentWs === ws && sess._sentCols === cols && sess._sentRows === rows) return false;
  ws.send(JSON.stringify({ type: 'resize', cols, rows }));
  _ocMarkSizeSent(sess);
  return true;
}

// A reconnect replays the buffered output together with the sizes the agent drew it at, so it lays
// out as drawn. xterm queues writes but resizes at once, so each resize waits behind the output
// written before it. The pane's own size comes back when the replay ends; nothing goes to the PTY.
function _ocReplaySize(sess, cols, rows) {
  const term = sess.term;
  if (!term || !Number.isInteger(cols) || !Number.isInteger(rows) || cols < 2 || rows < 1) return;
  if (!sess._replayingSizes || sess._replayWs !== sess.ws) {
    sess._replayingSizes = true;
    sess._replayWs = sess.ws;
    sess._replayPane = { cols: term.cols, rows: term.rows };
  }
  term.write('', () => term.resize(cols, rows));
}

function _ocReplayEnd(sess) {
  const term = sess.term;
  if (!term || !sess._replayingSizes) return;
  term.write('', () => {
    sess._replayingSizes = false;
    let size = null;
    try {
      size = sess.fitAddon && sess.fitAddon.proposeDimensions();
    } catch (_) {
      /* not visible yet */
    }
    if (!size || !(size.cols > 0) || !(size.rows > 0)) size = sess._replayPane;
    if (size.cols !== term.cols || size.rows !== term.rows) term.resize(size.cols, size.rows);
    // A pane that changed during the replay was not told to the PTY; _ocSendSize skips a size it already sent.
    _ocSendSize(sess);
  });
}

function _ocMarkSizeSent(sess) {
  sess._sentWs = sess.ws;
  sess._sentCols = sess.term.cols;
  sess._sentRows = sess.term.rows;
}

function _ocGuardSize(sess) {
  const observer = new ResizeObserver(() => {
    if (sess._closing) return;
    clearTimeout(sess._resizeDebounce);
    sess._resizeDebounce = setTimeout(() => {
      if (!sess._closing) _ocFit(sess);
    }, 80);
  });
  observer.observe(sess.container);
  sess._sizeObserver = observer;
}

function _ocHeaderTabStripId() {
  return 'oc-header-tabstrip';
}

function _ocRemoveHeaderTabStrip() {
  document.getElementById(_ocHeaderTabStripId())?.remove();
}
