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
    if (sess.ws && sess.ws.readyState === WebSocket.OPEN) {
      sess.ws.send(JSON.stringify({ type: 'input', data }));
    }
  });
}

function _ocFit(sess) {
  if (!sess || !sess.fitAddon || !sess.term) return;
  const el = sess.container;
  if (!el || !el.offsetParent || el.clientWidth < 40) return;
  const prevCols = sess.term.cols;
  const prevRows = sess.term.rows;
  try {
    sess.fitAddon.fit();
  } catch (_) {
    /* not visible yet */
  }
  // Only send resize + clear if dimensions actually changed. Sending a
  // resize when nothing changed makes TUI apps redraw needlessly; clearing
  // the buffer on a no-op resize would wipe the screen for nothing.
  if (sess.term.cols === prevCols && sess.term.rows === prevRows) return;
  // Clear the xterm viewport so stale content from the old size doesn't
  // bleed into the TUI's redraw at the new size. Without this, a resize
  // mid-popup leaves the old popup text interleaved with the new layout.
  sess.term.reset();
  if (sess.ws && sess.ws.readyState === WebSocket.OPEN) {
    sess.ws.send(
      JSON.stringify({
        type: 'resize',
        cols: sess.term.cols,
        rows: sess.term.rows,
      }),
    );
  }
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
