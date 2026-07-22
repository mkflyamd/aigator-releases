// tp-opencode-terminal.js — full-fidelity xterm.js terminal(s) for the
// OpenCode coding agent, rendered into #tp-detail-col (the Code tab's
// middle pane). Supports multiple simultaneous sessions per (tab, project)
// pair via a tab strip, mirroring terminal.js's own multi-session pattern
// (STATE.sessions / _renderTabs / _activate) - reuses its .gtp-tabs /
// .gtp-terms CSS classes directly rather than inventing parallel ones.
//
// Deliberately full xterm.js emulation rather than an ANSI-stripped
// chat-bubble trace - OpenCode's real interactive TUI needs cursor
// positioning, colors, and the alternate screen buffer, not just a log of
// text output.

// tabId -> { termsEl, projectId, repoPath, activeSessionId,
//            live: { sessionId: sess } }
// `live` only holds sessions with an actually-connected terminal - a tab
// strip can (and normally does) list sessions that aren't in `live` yet;
// clicking one lazily attaches it (see _ocActivateOrReattach). The tab strip
// itself doesn't live here - it's mounted in the persistent #tp-detail-header
// toolbar (see _ocEnsureHeaderTabStrip), not in the content area.
let _ocTerminals = {};

// CSRF-protected POST helper: retries once with a fresh token on a stale-token
// 403 (see _caFetchWithCsrfRetry in tp-code-agent.js). Falls back to a plain
// fetch if that helper isn't loaded for some reason, rather than hard-failing.
function _ocFetch(url, opts) {
  return typeof _caFetchWithCsrfRetry === 'function' ? _caFetchWithCsrfRetry(url, opts) : fetch(url, opts);
}

function _ocTermsContainerId(tabId) {
  return 'oc-terms-' + tabId;
}
function _ocTermHostId(tabId, sessionId) {
  return 'oc-term-' + tabId + '-' + sessionId;
}

// xterm.js paints to a canvas, so it doesn't pick up [data-theme] CSS changes
// on its own — compute the palette from the current theme and re-apply it
// live on every open session (see the 'gator:theme-change' listener below).
function _ocXtermTheme() {
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  return light
    ? { background: '#ffffff', foreground: '#0f172a', cursor: '#0f172a' }
    : { background: '#0b0d12', foreground: '#d4d4d4', cursor: '#d4d4d4' };
}

window.addEventListener('gator:theme-change', () => {
  const theme = _ocXtermTheme();
  Object.values(_ocTerminals).forEach(state => {
    Object.values(state.live || {}).forEach(sess => {
      if (sess.term) sess.term.options.theme = theme;
    });
  });
});

function _ocSpawnTerm(sess) {
  /* global Terminal, FitAddon */
  sess.term = new Terminal({
    fontFamily: 'Consolas, "Courier New", monospace',
    fontSize: 13,
    cursorBlink: true,
    theme: _ocXtermTheme(),
    scrollback: 5000,
    convertEol: true,
  });
  sess.fitAddon = new FitAddon.FitAddon();
  sess.term.loadAddon(sess.fitAddon);
  sess.term.open(sess.container);

  // Same paste-ownership pattern as terminal.js: one capture-phase listener,
  // so xterm's own textarea listener never double-handles the same paste.
  sess.container.addEventListener('paste', (e) => {
    e.preventDefault();
    e.stopPropagation();
    const txt = (e.clipboardData || window.clipboardData).getData('text');
    if (txt && sess.term) sess.term.paste(txt);
  }, true);

  sess.term.attachCustomKeyEventHandler((e) => {
    if (e.type !== 'keydown') return true;
    if (e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey && (e.key === 'c' || e.key === 'C')) {
      if (sess.term.hasSelection()) {
        const sel = sess.term.getSelection();
        if (sel) navigator.clipboard.writeText(sel).catch(() => {});
        sess.term.clearSelection();
        return false;
      }
      return true; // no selection - let Ctrl+C pass through as a real interrupt
    }
    if (e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey && (e.key === 'v' || e.key === 'V')) {
      return false; // browser's paste event (owned above) handles it
    }
    if (e.ctrlKey && e.shiftKey && !e.altKey && !e.metaKey && (e.key === 'v' || e.key === 'V')) {
      navigator.clipboard.readText().then((txt) => {
        if (txt && sess.term) sess.term.paste(txt);
      }).catch(() => {});
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
  // Never fit before the container is actually laid out with a real width.
  // fitAddon.fit() on a display:none / zero-width element computes a tiny
  // column count (~8), and sending THAT as a PTY resize makes a fast-starting
  // shell render its startup banner hard-wrapped at ~8 cols in ConPTY's byte
  // stream - which never un-wraps once emitted, even after xterm grows. This
  // raced only for instant-output agents (the bare terminal / a shell);
  // OpenCode's ~30s cold start always finished laying out first, hiding it.
  // offsetParent is null when display:none; clientWidth guards the brief
  // window where it's shown but not yet sized. The ResizeObserver
  // (_ocGuardSize) re-fits once the container has real dimensions.
  const el = sess.container;
  if (!el || !el.offsetParent || el.clientWidth < 40) return;
  try {
    sess.fitAddon.fit();
    if (sess.ws && sess.ws.readyState === WebSocket.OPEN) {
      sess.ws.send(JSON.stringify({ type: 'resize', cols: sess.term.cols, rows: sess.term.rows }));
    }
  } catch (e) { /* not visible yet */ }
}

// Collapse OpenCode's TUI sidebar by sending its sidebar-toggle keybind:
// leader (Ctrl+X, 0x18) then 'b'. Sent as one atomic write so the two land
// consecutively in the PTY stream (opencode's leader expects 'b' promptly
// after the leader key). Called once per fresh session (see _ocConnect's
// first-output handler) - the toggle is stateful, so it must never fire on a
// reattach/reconnect or it would flip an already-hidden sidebar back on.
// There is no OpenCode config to hide the sidebar or its footer (verified
// against the config schema), so this keystroke is the only mechanism.
function _ocCollapseSidebar(sess) {
  if (!sess || !sess.ws || sess.ws.readyState !== WebSocket.OPEN) return;
  try {
    sess.ws.send(JSON.stringify({ type: 'input', data: '\x18b' }));
  } catch (_) {}
}

// Real gap found via user report: editing an MCP config file (OpenCode's
// global opencode.jsonc, or a project one) has no effect on an
// already-running opencode server - it only reads MCP config once at
// startup. The result was a silently-failed MCP tool with no signal
// anywhere except OpenCode's own internal logs, which Gator doesn't even
// capture (instance_manager._spawn_instance pipes serve's stdout/stderr to
// DEVNULL). GET /mcp is OpenCode's own documented status endpoint
// (confirmed via its /doc OpenAPI spec, not scraped log text) - checked
// once, a few seconds after the terminal's first paint (not a poll loop),
// giving a local MCP time to spawn via npx on first connect.
async function _ocCheckMcpStatus(sess) {
  if (!sess || sess._closing || !sess.container || !sess.container.isConnected) return;
  const state = _ocTerminals[sess.tabId];
  if (!state || !state.projectId) return;
  let status;
  try {
    const resp = await fetch('/api/opencode/mcp_status?project_id=' + encodeURIComponent(state.projectId));
    if (!resp.ok) return;
    status = await resp.json();
  } catch (_) { return; }
  if (!status || typeof status !== 'object') return;
  const failed = Object.entries(status).filter(([, v]) => v && v.status === 'failed');
  if (failed.length === 0) return;
  // The session may have moved on (closed, switched away) while the fetch
  // was in flight - don't paint a banner into a container nobody's looking at.
  if (sess._closing || !sess.container || !sess.container.isConnected) return;
  _ocShowMcpBanner(sess, failed);
}

// One dismissible banner per session container - a stale MCP failure isn't
// fatal to the terminal (unlike a crashed process, see
// _ocShowRestartOverlay), so this stays a slim heads-up the user can act on
// or ignore, not a full blocking overlay.
function _ocShowMcpBanner(sess, failedEntries) {
  if (!sess.container || sess.container.querySelector('.oc-mcp-banner')) return;
  const [name, info] = failedEntries[0];
  const extra = failedEntries.length > 1 ? ` (+${failedEntries.length - 1} more)` : '';

  const banner = document.createElement('div');
  banner.className = 'oc-mcp-banner';
  banner.innerHTML =
    '<span class="oc-mcp-banner-icon">⚠️</span>' +
    '<span class="oc-mcp-banner-body">' +
      '<div class="oc-mcp-banner-title">A tool ("' + escapeHtml(name) + '") failed to connect' + extra + '</div>' +
      '<div class="oc-mcp-banner-detail">' + escapeHtml(info && info.error ? info.error : 'This can happen if its settings changed while this session was running.') + '</div>' +
      '<div class="oc-mcp-banner-actions">' +
        '<button type="button" class="oc-mcp-banner-restart">Restart to fix</button>' +
        '<button type="button" class="oc-mcp-banner-dismiss">Dismiss</button>' +
      '</div>' +
    '</span>';
  sess.container.appendChild(banner);

  banner.querySelector('.oc-mcp-banner-dismiss').addEventListener('click', () => banner.remove());

  const restartBtn = banner.querySelector('.oc-mcp-banner-restart');
  restartBtn.addEventListener('click', async () => {
    const state = _ocTerminals[sess.tabId];
    if (!state) { banner.remove(); return; }
    restartBtn.disabled = true;
    restartBtn.textContent = 'Restarting…';
    try {
      const headers = typeof _caHeadersAsync === 'function' ? await _caHeadersAsync() : { 'Content-Type': 'application/json' };
      const resp = await _ocFetch('/api/opencode/restart', {
        method: 'POST',
        headers,
        body: JSON.stringify({ project_id: state.projectId, repo_path: state.repoPath }),
      });
      if (!resp.ok) throw new Error(await _ocErrorDetail(resp));
      // Server side is fresh now; redo the client side too (detach the old
      // attach, dispatch a new one) so the terminal actually talks to it -
      // reusing the same crash-recovery flow, just with a genuinely fresh
      // server underneath instead of a dead one.
      await _ocRestartSession(sess.tabId, state.projectId, state.repoPath, sess.sessionId);
    } catch (err) {
      restartBtn.disabled = false;
      restartBtn.textContent = 'Restart to fix';
      restartBtn.title = err && err.message ? err.message : 'Restart failed — try again';
      return;
    }
    banner.remove();
  });
}

function _ocConnect(sess, retryDelay) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = proto + '//' + location.host + '/api/terminal/agent?session_id=' + encodeURIComponent(sess.ptySessionId);
  const wasRetrying = !!retryDelay;

  sess.ws = new WebSocket(url);
  sess.ws.onopen = () => {
    if (wasRetrying && sess._retryAttempt) {
      sess.term && sess.term.write('\r\n\x1b[32m[reconnected]\x1b[0m\r\n');
    }
    sess._retryAttempt = 0;
    _ocFit(sess);
    sess.term && sess.term.focus();
  };
  sess.ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === 'output') {
      sess.term && sess.term.write(msg.data);
      if (!sess._hasOutput) {
        // First real paint from opencode - now (not at socket-connect time)
        // is when the terminal is worth showing. Drops the loading animation
        // and reveals the terminal in one go, so there's no blank-black gap.
        sess._hasOutput = true;
        _ocRevealSession(sess);
        // On a freshly-created session (set in _ocDispatch), collapse
        // OpenCode's sidebar now that its TUI is up and accepting keybinds -
        // hides the redundant "path:branch • OpenCode <version>" footer and
        // gives the transcript full width. Once only; the toggle is stateful.
        if (sess._collapseSidebarOnFirstOutput) {
          sess._collapseSidebarOnFirstOutput = false;
          _ocCollapseSidebar(sess);
        }
        // Real gap found via user report: a manually-edited MCP config has
        // no effect on an already-running opencode server (it only reads
        // MCP config at startup) - the resulting failure was silent unless
        // the user went looking at OpenCode's own logs. One check, a few
        // seconds after the terminal comes up (giving a local MCP time to
        // spawn via npx on first connect), not continuous polling.
        setTimeout(() => _ocCheckMcpStatus(sess), 3000);
      }
    } else if (msg.type === 'exit') {
      // Real bug found via user report: this used to just print a line and
      // let onclose's unconditional retry loop keep hammering a session
      // that the server just told us is gone for good (process exited, or
      // "Session not found" after a Gator restart wiped the in-memory PTY
      // registry) - forever, capped at 30s between attempts, with no way to
      // break out except knowing to close the tab and click "+" yourself.
      // An explicit exit message means the backend has already concluded
      // this session is unrecoverable - stop retrying and offer a real way
      // out instead of retrying into the same dead end.
      sess._dead = true;
      sess.term && sess.term.write('\r\n\x1b[33m[' + (msg.data || 'Session ended') + ']\x1b[0m\r\n');
      _ocShowRestartOverlay(sess, msg.data || 'Session ended');
    }
  };
  sess.ws.onerror = () => { /* onclose handles retry */ };
  sess.ws.onclose = () => {
    if (!sess.term || sess._closing || sess._dead) return;
    // Real bug found via user report: this only printed the "reconnecting"
    // message on the FIRST disconnect (delay === 0) - every subsequent retry
    // was completely silent. A genuinely-dead session already breaks out via
    // the 'exit' message handler above (sess._dead + restart overlay), so
    // anything still hitting this path is a transient drop that's expected
    // to recover - but with no visible feedback past attempt 1, a reload
    // that takes more than one retry to clear looks exactly like a frozen,
    // unresponsive terminal instead of one that's quietly still trying.
    const attempt = (sess._retryAttempt || 0) + 1;
    sess._retryAttempt = attempt;
    // Tuned faster than the old 1s→30s schedule: this path now mostly serves
    // a live dev reload (a few seconds) rather than a genuinely gone server
    // (which exits via the 'exit' message on the very next connect attempt
    // regardless of how soon it's tried), so there's no need for a long
    // backoff here.
    const next = Math.min(500 * attempt, 8000);
    sess.term.write('\r\n\x1b[33m[disconnected — reconnecting (attempt ' + attempt + ') in '
      + Math.round(next / 1000) + 's…]\x1b[0m\r\n');
    setTimeout(() => {
      if (!sess.term || sess._closing || sess._dead) return;
      _ocConnect(sess, next);
    }, next);
  };
}

// Confirmed-unrecoverable session - stop retrying (see onmessage's 'exit'
// handler above) and give the user an actual way out instead of a dead
// terminal with no affordance. Overlays the session's own container so the
// tab strip entry itself stays put; restarting swaps in a fresh session
// under the same tab.
function _ocShowRestartOverlay(sess, reason) {
  if (!sess.container) return;
  if (sess.container.querySelector('.oc-restart-overlay')) return; // already showing
  const overlay = document.createElement('div');
  overlay.className = 'oc-restart-overlay';
  const msg = document.createElement('div');
  msg.className = 'oc-restart-msg';
  msg.textContent = reason || 'Session ended';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'oc-restart-btn';
  btn.textContent = 'Restart session';
  btn.addEventListener('click', () => {
    overlay.remove();
    const state = _ocTerminals[sess.tabId];
    if (state) _ocRestartSession(sess.tabId, state.projectId, state.repoPath, sess.sessionId);
  });
  overlay.appendChild(msg);
  overlay.appendChild(btn);
  sess.container.appendChild(overlay);
}

// Drops the dead session (never touches the backend - the underlying
// OpenCode process is already gone, there's nothing to terminate) and
// dispatches a brand-new one in its place, renamed back to the old label so
// the tab's identity/position in the strip feels continuous rather than
// appearing as an unrelated new tab.
async function _ocRestartSession(tabId, projectId, repoPath, oldSessionId) {
  const entry = _ocGetProjEntry(tabId, projectId);
  const oldItem = entry.list.find((s) => s.sessionId === oldSessionId);
  const oldLabel = oldItem ? oldItem.label : null;

  _ocDetachSession(tabId, oldSessionId);
  _ocRemoveSessionFromList(tabId, projectId, oldSessionId);

  try {
    const data = await _ocDispatch(tabId, projectId, repoPath, null, { forceNew: true });
    if (oldLabel && data && data.session_id) {
      const freshItem = _ocGetProjEntry(tabId, projectId).list.find((s) => s.sessionId === data.session_id);
      if (freshItem) {
        freshItem.label = oldLabel;
        _ocSaveTabSessions();
        _ocRenderTabs(tabId);
      }
    }
  } catch (err) {
    _ocShowDispatchError(err.message, tabId);
  }
}

// Second race found via real testing: xterm.js can be initialized
// (term.open(container)) while the container has zero size - the same
// pane-opening timing this whole file already works around - and its
// FitAddon.fit() then fails silently (caught by _ocFit's own try/catch,
// "not visible yet"). A ResizeObserver reacts to the actual size change
// instead of guessing when layout is "probably" done.
function _ocGuardSize(sess) {
  // Debounced, not immediate: a ResizeObserver fires on EVERY layout tick
  // during a drag-resize or CSS-transitioned panel resize, not just once at
  // the end - measured up to 7 firings within ~150ms for one resize gesture,
  // with wildly oscillating intermediate column counts (e.g. 95→67→123→81→
  // 116→84→74). Each one was being sent to the PTY as its own resize
  // message. A TUI that does incremental, cursor-positioned redraws (a
  // scrolling status line, not a full-screen clear+redraw) can end up
  // drawing at inconsistent coordinates across that storm of intermediate
  // sizes before anything settles - real bug found via user report, seen as
  // scattered/torn text mid-resize. Debouncing means the PTY only ever sees
  // the FINAL settled size. 80ms is short enough that a deliberate, one-shot
  // _ocFit call elsewhere (onopen, reveal-on-activate) still reads as
  // immediate to the user, but long enough to coalesce an entire drag
  // gesture's worth of intermediate ticks into one send.
  const observer = new ResizeObserver(() => {
    if (sess._closing) return;
    clearTimeout(sess._resizeDebounce);
    sess._resizeDebounce = setTimeout(() => { if (!sess._closing) _ocFit(sess); }, 80);
  });
  observer.observe(sess.container);
  sess._sizeObserver = observer;
}

// The terminals container for this Gator tab. #tp-detail-col is a SINGLE
// element SHARED by every third-pane skill (Teams/Email/etc.), each of which
// does `#tp-detail-col.innerHTML = ...` on open - so our container gets
// detached from the column every time the user leaves the Code tab. The one
// invariant that matters: xterm/WebSocket objects live in state.live (JS
// memory), fully decoupled from the DOM, so a detached container keeps its
// live terminals intact. We therefore create the container ONCE per tab and
// RE-MOUNT the same element on return (never recreate it - that would orphan
// the live terminals), keyed by _ocTermsContainerId.
//
// An earlier version used a MutationObserver to auto-re-append the container
// whenever anything removed it. That was wrong: it fought the legitimate
// innerHTML wipes other skills do to the shared column, jamming the OpenCode
// terminal into the Email/Teams pane. Removed - the mount lifecycle is now
// explicit (_ocMountActiveTab), driven by openThirdPane/switchTab.
function _ocEnsureTermsContainer(tabId) {
  const detailCol = document.getElementById('tp-detail-col');
  if (!detailCol) return null;

  let state = _ocTerminals[tabId];
  if (state && state.termsEl) {
    // Reuse the existing element (keeps its live xterm children) - just make
    // sure it's mounted in the current column, which a skill switch will have
    // detached it from. Also clear any leftover display:none from a diff that
    // was open when the user last left (_ocHideTerminal) - the diff element
    // itself got wiped by the other skill's render, so the terminal should be
    // visible again on return.
    if (state.termsEl.parentElement !== detailCol) {
      detailCol.appendChild(state.termsEl);
      state.termsEl.style.display = '';
    }
    return state;
  }

  const termsEl = document.createElement('div');
  termsEl.id = _ocTermsContainerId(tabId);
  termsEl.className = 'gtp-terms';
  detailCol.appendChild(termsEl);

  state = _ocTerminals[tabId] = state || { live: {}, activeSessionId: null, projectId: null, repoPath: null };
  state.termsEl = termsEl;
  return state;
}

// ── Loading state (keep the user engaged during the real network wait) ─────
// Every dispatch/reattach that needs a backend round trip (cold subprocess
// spawn, session create, PTY attach) previously showed nothing until it
// resolved - real latency measured up to ~16s cold, and still several
// hundred ms to a few seconds even warm (session create + PTY attach happen
// on every call, not just cold starts). Mirrors third-pane.js's existing
// _gatorLoading() (same gator/dots animation used for Teams/Email loading)
// with coding-flavored tips instead of the generic ones.
const _OC_LOADING_TIPS = [
  'Waking up the compiler',
  'Cloning into the swamp',
  'Untangling imports',
  'Warming up the REPL',
  'Chomping through node_modules',
  'Spinning up a sandbox',
  'Syncing with upstream',
  'Reticulating dependencies',
];

function _ocLoadingId(tabId) {
  return 'oc-loading-' + tabId;
}

function _ocShowLoadingState(tabId) {
  const state = _ocEnsureTermsContainer(tabId);
  if (!state) return;
  // Hide any live terminal so the loading state is the only thing visible -
  // relevant when starting a SECOND session ("+") while another is showing.
  Object.values(state.live).forEach((sess) => {
    if (sess.container) sess.container.style.display = 'none';
  });
  let el = document.getElementById(_ocLoadingId(tabId));
  if (!el) {
    el = document.createElement('div');
    el.id = _ocLoadingId(tabId);
    el.className = 'gtp-term oc-loading-term';
    state.termsEl.appendChild(el);
  }
  el.style.display = '';
  el.innerHTML = typeof _gatorLoading === 'function' ? _gatorLoading(_OC_LOADING_TIPS) : '';
}

function _ocHideLoadingState(tabId) {
  document.getElementById(_ocLoadingId(tabId))?.remove();
}

// One window-resize handler for all tabs (was previously added once per tab
// inside the container factory, leaking a listener per tab created). Refits
// whichever tab is currently mounted.
window.addEventListener('resize', () => {
  Object.values(_ocTerminals).forEach((st) => {
    if (st && st.termsEl && st.termsEl.parentElement) {
      const sess = st.live[st.activeSessionId];
      if (sess) _ocFit(sess);
    }
  });
});

// Ensure ONLY the given tab's terminals container is mounted in the shared
// #tp-detail-col, and no other tab's is. Safe to call unconditionally: it's
// a no-op unless the Code tab is the active third-pane skill (otherwise the
// column belongs to Teams/Email/etc. and we must not touch it). Handles both
// skill switches (another skill innerHTML='' the column, detaching ours) and
// Gator chat-tab switches (a different chat tab's terminal may be mounted).
function _ocMountActiveTab(tabId) {
  if (typeof tpState === 'undefined' || tpState.type !== 'code_agent') return;
  const detailCol = document.getElementById('tp-detail-col');
  if (!detailCol) return;
  Object.keys(_ocTerminals).forEach((tid) => {
    if (tid !== String(tabId)) {
      const other = _ocTerminals[tid];
      if (other && other.termsEl && other.termsEl.parentElement === detailCol) {
        other.termsEl.remove();
      }
    }
  });
  const state = _ocTerminals[tabId];
  if (state && state.termsEl && state.termsEl.parentElement !== detailCol) {
    detailCol.appendChild(state.termsEl);
    state.termsEl.style.display = '';
    const sess = state.live[state.activeSessionId];
    if (sess) setTimeout(() => _ocFit(sess), 20);
  }
}

// Attach (or reattach) one session's terminal within a tab's shell.
// Idempotent for the same ptySessionId - calling this again on tab
// re-entry just leaves the existing live terminal alone.
function _ocAttachTerminal(tabId, sessionId, ptySessionId) {
  const state = _ocTerminals[tabId];
  if (!state) return;
  const existing = state.live[sessionId];
  if (existing && existing.ptySessionId === ptySessionId && existing.term) return;
  if (existing) _ocDetachSession(tabId, sessionId);

  const container = document.createElement('div');
  container.className = 'gtp-term';
  container.id = _ocTermHostId(tabId, sessionId);
  container.style.display = 'none'; // _ocActivateSession makes the right one visible
  state.termsEl.appendChild(container);

  const sess = { tabId, sessionId, ptySessionId, container, _retryDelay: 0 };
  state.live[sessionId] = sess;
  _ocSpawnTerm(sess);
  _ocConnect(sess);
  _ocGuardSize(sess);
}

// Full teardown of one session's terminal - WS close, xterm dispose,
// container removed. Its underlying `opencode` session keeps running
// server-side (disk-backed, per instance_manager.py's idle-reap) regardless
// of whether anything here is looking at it.
function _ocDetachSession(tabId, sessionId) {
  const state = _ocTerminals[tabId];
  const sess = state && state.live[sessionId];
  if (!sess) return;
  sess._closing = true;
  clearTimeout(sess._resizeDebounce);
  try { sess._sizeObserver && sess._sizeObserver.disconnect(); } catch (_) {}
  try { sess.ws && sess.ws.close(); } catch (_) {}
  try { sess.term && sess.term.dispose(); } catch (_) {}
  try { sess.container && sess.container.remove(); } catch (_) {}
  delete state.live[sessionId];
}

// Full teardown of every live session for a tab, plus its terminals
// container and header tab strip - used on project switch (the old
// project's sessions are hidden, not forgotten: their bindings stay in
// _ocTabSessions so switching back can still reattach) and would also apply
// to a Gator-tab close if one is ever wired up.
function _ocDetachAllForTab(tabId) {
  const state = _ocTerminals[tabId];
  if (!state) return;
  state._closing = true;
  Object.keys(state.live).forEach((sessionId) => _ocDetachSession(tabId, sessionId));
  try { state.termsEl && state.termsEl.remove(); } catch (_) {}
  _ocRemoveHeaderTabStrip();
  delete _ocTerminals[tabId];
}

function _ocHideTerminal(tabId) {
  const state = _ocTerminals[tabId];
  if (state && state.termsEl) state.termsEl.style.display = 'none';
}

function _ocShowTerminal(tabId) {
  const state = _ocTerminals[tabId];
  if (state && state.termsEl) {
    state.termsEl.style.display = '';
    const sess = state.live[state.activeSessionId];
    if (sess) setTimeout(() => _ocFit(sess), 20);
  }
}

function _ocHasTerminal(tabId) {
  const state = _ocTerminals[tabId];
  return !!(state && Object.keys(state.live).length > 0);
}

// Show one session's terminal, hide the rest - same "hide, don't destroy"
// principle already used for the diff-toggle. Assumes the session is
// already live; use _ocActivateOrReattach when it might not be (e.g. a tab
// strip entry that was only ever restored from localStorage, never attached
// this page-load).
function _ocActivateSession(tabId, sessionId) {
  const state = _ocTerminals[tabId];
  if (!state) return;
  state.activeSessionId = sessionId;
  // Hide every OTHER session's container. The active one is handled below -
  // it stays hidden behind the loading animation until it has actually
  // painted, so we don't flash a blank terminal.
  Object.keys(state.live).forEach((sid) => {
    if (sid !== sessionId && state.live[sid].container) state.live[sid].container.style.display = 'none';
  });
  _ocRenderTabs(tabId);
  const sess = state.live[sessionId];
  if (!sess) { _ocHideLoadingState(tabId); return; }
  // Fire-and-forget: record this as the most recently activated session so a
  // purely backend-triggered event (Teams remote control) has something to
  // target even with no browser tab connected to ask. Best-effort - a failed
  // write here just means that feature falls back to "no known session".
  if (sess.ptySessionId && typeof _caHeadersAsync === 'function') {
    _caHeadersAsync().then(hdrs => {
      fetch('/api/opencode/active-pty-session', {
        method: 'PUT', headers: hdrs,
        body: JSON.stringify({ pty_session_id: sess.ptySessionId }),
      }).catch(() => {});
    });
  }
  if (sess._hasOutput) {
    // Already painted - reconnect/replay, or switching back to a populated
    // terminal. Safe to show immediately.
    _ocRevealSession(sess);
  } else {
    // Fresh cold attach: opencode's 173MB binary is still booting and hasn't
    // drawn its TUI yet. Keep the loading animation up and the (still-blank)
    // terminal hidden until the first output arrives (see _ocConnect's
    // onmessage) - revealing now would show a blank black pane for the whole
    // 2-15s boot, then the prompt would suddenly pop in. Real UX gap reported
    // by the user: "terminal loads blank, then the opencode prompt shows".
    _ocShowLoadingState(tabId);
    if (sess.container) sess.container.style.display = 'none';
  }
}

// Reveal a session's terminal once it's ready to be seen: drop the loading
// animation, show its container, fit + focus. Guarded to the tab's ACTIVE
// session so first output on a background ("+") session doesn't yank the view
// away from whatever the user is currently looking at.
function _ocRevealSession(sess) {
  if (!sess) return;
  const state = _ocTerminals[sess.tabId];
  if (!state || state.activeSessionId !== sess.sessionId) return;
  _ocHideLoadingState(sess.tabId);
  if (sess.container) sess.container.style.display = '';
  setTimeout(() => { _ocFit(sess); sess.term && sess.term.focus(); }, 20);
}

// Click handler for an existing tab entry - lazily spins up a real terminal
// on first click if this session was only ever a label (restored from
// localStorage, or created in another browser tab) rather than eagerly
// reattaching every known session up front (each reattach is a real PTY
// spawn on the backend - not free).
async function _ocActivateOrReattach(tabId, projectId, repoPath, sessionId) {
  const state = _ocTerminals[tabId];
  if (state && state.live[sessionId]) {
    _ocActivateSession(tabId, sessionId);
    _ocSetActiveSessionId(tabId, projectId, sessionId);
    return;
  }
  // Not live yet - a real backend round trip is coming (ensure_instance +
  // PTY attach), so show engagement immediately rather than a dead tab click.
  _ocShowLoadingState(tabId);
  const headers = typeof _caHeadersAsync === 'function' ? await _caHeadersAsync() : { 'Content-Type': 'application/json' };
  try {
    const resp = await _ocFetch('/api/opencode/terminal', {
      method: 'POST',
      headers,
      body: JSON.stringify({ project_id: projectId, repo_path: repoPath, session_id: sessionId }),
    });
    if (!resp.ok) {
      _ocShowDispatchError(await _ocErrorDetail(resp), tabId);
      return;
    }
    const data = await resp.json();
    // Same project-switch race as _ocDispatch/_ocReattachIfKnown: re-derive
    // fresh rather than trusting a pre-await reference, and check before
    // attaching - _ocAttachTerminal writes into whatever _ocTerminals[tabId]
    // CURRENTLY is, so a stale call would inject this session into a
    // different project's live-session map and tab strip.
    const current = _ocTerminals[tabId];
    if (!current || current.projectId !== projectId) return;
    _ocAttachTerminal(tabId, sessionId, data.pty_session_id);
    _ocActivateSession(tabId, sessionId);
    _ocSetActiveSessionId(tabId, projectId, sessionId);
  } catch (err) {
    // Tab stays as a label, clickable again to retry.
    _ocShowDispatchError(err.message, tabId);
  }
}

// ── Tab strip (mounted in the persistent #tp-detail-header toolbar) ────────
// Lives in the same row as the "Collapse panel" button rather than as its
// own row inside the content area - #tp-detail-header is shared/global
// (one per browser window, reflecting whichever Gator chat tab is active),
// so the strip is rebuilt on demand rather than kept per-tabId in the DOM.
function _ocHeaderTabStripId() {
  return 'oc-header-tabstrip';
}

function _ocEnsureHeaderTabStrip() {
  if (typeof tpState === 'undefined' || tpState.type !== 'code_agent') return null;
  const hdr = document.getElementById('tp-detail-header');
  if (!hdr) return null;
  let strip = document.getElementById(_ocHeaderTabStripId());
  if (!strip) {
    strip = document.createElement('div');
    strip.id = _ocHeaderTabStripId();
    strip.className = 'gtp-tabs oc-header-tabs';
    const scroll = document.createElement('div');
    scroll.className = 'gtp-tabs-scroll';
    const newBtn = document.createElement('button');
    newBtn.type = 'button';
    newBtn.className = 'gtp-tab-new';
    newBtn.title = 'New OpenCode session';
    // SVG plus, not a text "+" - a text glyph doesn't share the neighbouring
    // toolbar buttons' optical centre, so it read as vertically misaligned
    // next to them. 14px/viewBox-24/stroke-2/round spec. (User-reported
    // alignment nit.)
    newBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>';
    scroll.appendChild(newBtn);
    strip.appendChild(scroll);
    strip._scroll = scroll;
    strip._newBtn = newBtn;
    // Insert as the toolbar's first child - _resetDetailHeader (third-pane.js)
    // already built [spacer][divider][collapse button]; this pushes those
    // over, keeping the collapse button pinned far-right exactly as before.
    hdr.insertBefore(strip, hdr.firstChild);
  }
  return strip;
}

function _ocRemoveHeaderTabStrip() {
  document.getElementById(_ocHeaderTabStripId())?.remove();
}

// The maximize/restore toggle (formerly Code-tab-only _oc* functions) is now
// generic and lives in third-pane.js (_tpEnsureExpandButton etc.) - every app
// gets it via tpBuildDetailToolbar(), not just this one.

function _ocRenderTabs(tabId) {
  const state = _ocTerminals[tabId];
  if (!state || !state.projectId) { _ocRemoveHeaderTabStrip(); return; }
  const strip = _ocEnsureHeaderTabStrip();
  if (!strip) return;

  strip._newBtn.onclick = () => _ocNewSessionTab(tabId, state.projectId, state.repoPath);

  const entry = _ocGetProjEntry(tabId, state.projectId);
  const scroll = strip._scroll;
  const newBtn = strip._newBtn;
  [...scroll.querySelectorAll('.gtp-tab')].forEach((el) => el.remove());

  entry.list.forEach((item) => {
    const tab = document.createElement('div');
    tab.className = 'gtp-tab' + (item.sessionId === state.activeSessionId ? ' active' : '');
    const label = document.createElement('span');
    label.className = 'gtp-tab-label';
    label.textContent = item.label;
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'gtp-tab-close';
    x.title = 'Close';
    x.textContent = '✕';
    tab.appendChild(label);
    tab.appendChild(x);

    tab.addEventListener('click', (e) => {
      if (e.target === x || label.isContentEditable) return;
      _ocActivateOrReattach(tabId, state.projectId, state.repoPath, item.sessionId);
    });
    x.addEventListener('click', (e) => {
      e.stopPropagation();
      _ocCloseSessionTab(tabId, state.projectId, item.sessionId);
    });
    tab.addEventListener('dblclick', (e) => {
      if (e.target === x) return;
      e.preventDefault();
      e.stopPropagation();
      _ocBeginRename(item, label);
    });

    scroll.insertBefore(tab, newBtn);
  });
}

// Real bug found via smoke-testing, not assumed: #tp-detail-header is a
// single global element (sibling of #tp-detail-col, not per-tab DOM) -
// exactly the same issue the breadcrumb below already had to work around.
// Without this, switching to a different Gator chat tab wouldn't refresh
// the strip, leaving it showing whichever tab's sessions were rendered last.
function _ocSyncHeaderTabStripOnTabSwitch(tabId) {
  const state = _ocTerminals[tabId];
  if (state && state.projectId) {
    _ocRenderTabs(tabId);
  } else {
    _ocRemoveHeaderTabStrip();
  }
}

// Rename a session tab's display label - purely cosmetic, no backend or
// dispatch implication, matching terminal.js's own double-click rename UX
// exactly (same interaction, same code shape).
function _ocBeginRename(item, labelEl) {
  labelEl.contentEditable = 'true';
  labelEl.spellcheck = false;
  labelEl.classList.add('editing');
  labelEl.focus();
  const range = document.createRange();
  range.selectNodeContents(labelEl);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);

  const finish = (commit) => {
    labelEl.removeEventListener('keydown', onKey);
    labelEl.removeEventListener('blur', onBlur);
    labelEl.contentEditable = 'false';
    labelEl.classList.remove('editing');
    const next = labelEl.textContent.trim();
    if (commit && next) {
      item.label = next;
      _ocSaveTabSessions();
    }
    labelEl.textContent = item.label;
    window.getSelection().removeAllRanges();
  };
  const onKey = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  };
  const onBlur = () => finish(true);
  labelEl.addEventListener('keydown', onKey);
  labelEl.addEventListener('blur', onBlur);
}

// ── Tab -> OpenCode session registry ──────────────────────────────────────────
// tabId -> projectId -> { active: sessionId|null, nextNum, list: [{sessionId, label}] }
// A tab can touch multiple projects over its lifetime, and EACH retains its
// own session list, not just the most recent one (real bug found via manual
// testing in the single-session design this replaced: a project switch used
// to DELETE the old project's binding outright, so A -> B -> back-to-A had
// nothing left to reattach to). Multiple sessions per project are now a
// first-class list, not just a single slot.
const _OC_SESSIONS_KEY = 'gator-oc-sessions';
function _ocLoadTabSessions() {
  try { return JSON.parse(localStorage.getItem(_OC_SESSIONS_KEY) || '{}'); }
  catch { return {}; }
}
function _ocSaveTabSessions() {
  try { localStorage.setItem(_OC_SESSIONS_KEY, JSON.stringify(_ocTabSessions)); }
  catch (_) {}
}
const _ocTabSessions = _ocLoadTabSessions();

function _ocGetProjEntry(tabId, projectId) {
  _ocTabSessions[tabId] = _ocTabSessions[tabId] || {};
  _ocTabSessions[tabId][projectId] = _ocTabSessions[tabId][projectId] || { active: null, nextNum: 1, list: [] };
  return _ocTabSessions[tabId][projectId];
}

function _ocRegisterSession(tabId, projectId, sessionId, label) {
  const entry = _ocGetProjEntry(tabId, projectId);
  let item = entry.list.find((s) => s.sessionId === sessionId);
  if (!item) {
    item = { sessionId, label: label || ('Session ' + entry.nextNum) };
    entry.nextNum += 1;
    entry.list.push(item);
  }
  entry.active = sessionId;
  _ocSaveTabSessions();
  return item;
}

function _ocSetActiveSessionId(tabId, projectId, sessionId) {
  const entry = _ocGetProjEntry(tabId, projectId);
  entry.active = sessionId;
  _ocSaveTabSessions();
}

// Removes one session from the persisted list and returns whichever session
// should become active next (mirrors terminal.js's closeSession: the
// neighbor at the same index, clamped), or null if none remain. Never
// deletes the underlying OpenCode session server-side - just stops tracking
// it as a tab.
function _ocRemoveSessionFromList(tabId, projectId, sessionId) {
  const entry = _ocGetProjEntry(tabId, projectId);
  const idx = entry.list.findIndex((s) => s.sessionId === sessionId);
  if (idx < 0) return entry.active;
  entry.list.splice(idx, 1);
  if (entry.active === sessionId) {
    entry.active = entry.list.length ? entry.list[Math.min(idx, entry.list.length - 1)].sessionId : null;
  }
  _ocSaveTabSessions();
  return entry.active;
}

// Called from _caSetActiveProject (tp-code-agent.js) on every project switch.
// Tears down every live session for the OLD project - never deletes any
// project's session bindings, since _ocReattachIfKnown (called separately,
// right after this) needs that data intact to reattach the NEW project's
// active session if one exists.
function _ocOnProjectSwitch(tabId) {
  _ocDetachAllForTab(tabId);
  _ocHideSessionToggle();
}

// The "+" button handler and the actual entry point for "start another
// session on the same project" - always forces a brand-new backend session
// (never reuses the current active one), matching the confirmed feature
// request: multiple sessions on the same project, side by side.
async function _ocNewSessionTab(tabId, projectId, repoPath) {
  try {
    await _ocDispatch(tabId, projectId, repoPath, null, { forceNew: true });
  } catch (err) {
    _ocShowDispatchError(err.message, tabId);
  }
}

// The "x" button handler - detaches the terminal and drops it from the tab
// strip. Never terminates the underlying OpenCode session server-side
// (consistent with project-switch: hide, don't destroy - the session is
// disk-backed and cheap to leave alone). If this was the last session for
// the project, falls back to an idle strip (just the "+" button) rather
// than auto-spawning a replacement - closing is a deliberate user action,
// matching terminal.js's own behavior of not fighting an explicit close.
function _ocCloseSessionTab(tabId, projectId, sessionId) {
  _ocDetachSession(tabId, sessionId);
  const nextActive = _ocRemoveSessionFromList(tabId, projectId, sessionId);
  const state = _ocTerminals[tabId];
  if (!state) return;
  state.activeSessionId = nextActive;
  _ocRenderTabs(tabId);
  if (!nextActive) {
    _ocHideSessionToggle();
    return;
  }
  if (state.live[nextActive]) {
    _ocActivateSession(tabId, nextActive);
  } else {
    _ocActivateOrReattach(tabId, projectId, state.repoPath, nextActive);
  }
}

// Real bug found via manual testing, not assumed: every failure path below
// used to swallow its error silently (`catch (_) {}`), which was fine for
// truly transient network hiccups but meant a real, actionable failure -
// e.g. no bundled OpenCode binary at all - looked identical to "nothing
// happened," with no way to tell why. Extracts the backend's actual
// HTTPException detail (e.g. "OpenCode binary not found. Run WakeGator to
// install it, or reinstall the app.") instead of a bare status code.
async function _ocErrorDetail(resp) {
  try {
    const data = await resp.json();
    if (data && data.detail) return data.detail;
  } catch (_) {}
  return 'OpenCode request failed (' + resp.status + ')';
}

function _ocShowDispatchError(message, tabId) {
  if (tabId) _ocHideLoadingState(tabId);
  if (typeof addMessage === 'function') {
    addMessage('assistant', '⚠️ Could not start OpenCode: ' + message);
  }
}

// The actual dispatcher entry point - "fix this GitHub issue", a Jira ticket
// handoff, or a pinned-item drop onto the Code tab all funnel through this,
// as does the "+" new-session-tab button (opts.forceNew). contextText is
// optional: omit it to just start a bare session (e.g. selecting a project
// with nothing specific yet, or opening a fresh tab - the user then types
// directly into the attached terminal).
async function _ocDispatch(tabId, projectId, repoPath, contextText, opts) {
  opts = opts || {};
  const entry = _ocGetProjEntry(tabId, projectId);
  const sessionId = opts.forceNew ? null : (opts.sessionId || entry.active || null);

  // Real latency measured up to ~16s cold (server spawn) and still several
  // hundred ms to a few seconds warm (session create + PTY attach happen on
  // every call) - show engagement BEFORE the network round trip, not after,
  // so the wait is never a blank pane. Pane focus moved up here too (used to
  // happen only after the fetch resolved).
  _ocFocusMiddlePane();
  const _state = _ocEnsureTermsContainer(tabId);
  if (_state) { _state.projectId = projectId; _state.repoPath = repoPath; }
  _ocShowLoadingState(tabId);

  const headers = typeof _caHeadersAsync === 'function' ? await _caHeadersAsync() : { 'Content-Type': 'application/json' };
  const body = { project_id: projectId, repo_path: repoPath, session_id: sessionId };
  if (contextText) body.context_text = contextText;
  const resp = await _ocFetch('/api/opencode/dispatch', {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(await _ocErrorDetail(resp));
  }
  const data = await resp.json();

  _ocRegisterSession(tabId, projectId, data.session_id);

  const state = _ocEnsureTermsContainer(tabId);
  // Has the user switched to a different project in this tab while this
  // dispatch was in flight? Project switch tears down and replaces the whole
  // per-tab state object (_ocDetachAllForTab), so `state` here already
  // reflects whichever project is now current. Check BEFORE attaching:
  // _ocAttachTerminal writes into this same object, so calling it for a
  // stale project would inject the session into the new project's
  // live-session map and tab strip.
  if (!state || state.projectId !== projectId) return data;
  _ocAttachTerminal(tabId, data.session_id, data.pty_session_id);
  // Hide OpenCode's TUI sidebar (Context/LSP panel + the redundant
  // "path:branch • OpenCode <version>" footer) by default, but ONLY on a
  // freshly-created session - see _ocConnect's first-output handler, which
  // sends the toggle keystroke once the TUI has painted. Gated on
  // data.created because the toggle is stateful: firing it on a reattach or
  // reconnect would flip an already-hidden sidebar back on. No OpenCode
  // config option exists to default this (schema confirms), so the keystroke
  // is the only lever.
  if (data.created) {
    const _s = _ocTerminals[tabId] && _ocTerminals[tabId].live[data.session_id];
    if (_s) _s._collapseSidebarOnFirstOutput = true;
  }
  state.repoPath = repoPath;
  _ocActivateSession(tabId, data.session_id);
  // A bare auto-start (no specific task) isn't really a "handoff" - only
  // show the confirmation when there was actual context being seeded.
  if (contextText) _ocShowHandoffConfirmation();
  _ocShowSessionToggle(projectId);
  return data;
}

// Return-landing flow (OpenCodeIntegrationPlan.md §5.5, flow 2): if this tab
// already has a known active session for the given project, reattach it (and
// render the full tab strip, including other known-but-not-yet-live
// sessions) - covers both "instance still running" and "instance was
// idle-reaped, spin up fresh and reattach to the same session id"
// identically, since ensure_instance() on the backend converges both cases
// already. No dispatch call here - nothing new is being seeded, just
// reconnecting to what exists.
async function _ocReattachIfKnown(tabId, projectId, repoPath) {
  const entry = _ocGetProjEntry(tabId, projectId);
  const sessionId = entry.active;
  if (!sessionId) return false;

  const state = _ocEnsureTermsContainer(tabId);
  if (!state) return false;
  state.projectId = projectId;
  state.repoPath = repoPath;
  _ocRenderTabs(tabId);

  // Already have a live terminal for this session in memory. _ocEnsureTerms-
  // Container above re-mounted its (possibly skill-switch-detached) container
  // back into the column; re-activate to re-show + refit it. No backend call
  // needed - the xterm/WebSocket never died, they just weren't in the DOM.
  if (state.live[sessionId]) {
    _ocActivateSession(tabId, sessionId);
    _ocShowSessionToggle(projectId);
    return true;
  }

  // Not live yet - reattaching means a real ensure_instance + PTY-attach
  // round trip on the backend. _ocStartOrResume falls through to _ocDispatch
  // (which shows its own loading state) if this returns false, so no separate
  // hide-on-failure needed here - it carries straight into the next attempt's
  // loading state with no visible gap.
  _ocShowLoadingState(tabId);
  const headers = typeof _caHeadersAsync === 'function' ? await _caHeadersAsync() : { 'Content-Type': 'application/json' };
  try {
    const resp = await _ocFetch('/api/opencode/terminal', {
      method: 'POST',
      headers,
      body: JSON.stringify({ project_id: projectId, repo_path: repoPath, session_id: sessionId }),
    });
    if (!resp.ok) return false;
    const data = await resp.json();
    // The user may have switched to a different project in this tab while
    // this round trip was in flight - project switch tears down and replaces
    // the whole per-tab state object (_ocDetachAllForTab), so the `state`
    // captured above is now a stale, orphaned object nobody else mutates.
    // Re-derive it fresh rather than trusting that reference, and skip
    // attaching entirely if stale: _ocAttachTerminal writes into whatever
    // _ocTerminals[tabId] CURRENTLY is, so calling it here would inject this
    // session into the new project's live-session map and tab strip.
    const current = _ocEnsureTermsContainer(tabId);
    if (!current || current.projectId !== projectId) return true;
    _ocAttachTerminal(tabId, sessionId, data.pty_session_id);
    _ocActivateSession(tabId, sessionId);
    _ocShowSessionToggle(projectId);
    return true;
  } catch (_) {
    return false;
  }
}

// ── Guided (user-driven) start ─────────────────────────────────────────────
// OpenCode is NOT auto-spawned on pane-load/project-select anymore: a cold
// `opencode serve` is a ~15-30s heavy spawn, and auto-firing it before it's
// ready raced the attach → blank terminal on first visit + churn. Instead the
// pane shows an explicit "Start/Resume coding agent" prompt and nothing hits
// the backend until the user clicks. The click resolves the cheapest correct
// path (re-mount live / reattach / fresh dispatch), always with progress.

function _ocPromptId(tabId) { return 'oc-startprompt-' + tabId; }

function _ocHideStartPrompt(tabId) {
  document.getElementById(_ocPromptId(tabId))?.remove();
}

// True only when this tab's terminal is CURRENTLY mounted on screen with a live
// session — i.e. the user is already looking at it (don't yank them to a
// prompt). A skill switch detaches termsEl (parentElement !== the column) even
// though live sessions survive in JS memory, so both checks are required.
function _ocIsTerminalMounted(tabId) {
  const state = _ocTerminals[tabId];
  const detailCol = document.getElementById('tp-detail-col');
  return !!(state && state.termsEl && detailCol
            && state.termsEl.parentElement === detailCol
            && state.activeSessionId && state.live[state.activeSessionId]);
}

// Entry point for pane-load / project-select / return-to-code-pane. Shows the
// live terminal if it's already on screen; otherwise the Start/Resume prompt.
// NEVER auto-spawns, NEVER leaves the pane blank.
function _ocShowStartOrTerminal(tabId, projectId, repoPath) {
  if (_ocIsTerminalMounted(tabId)) return;   // already showing it — leave it
  _ocShowStartPrompt(tabId, projectId, repoPath);
}

function _ocShowStartPrompt(tabId, projectId, repoPath, errMsg) {
  const state = _ocEnsureTermsContainer(tabId);
  if (!state) return;
  state.projectId = projectId; state.repoPath = repoPath;
  // Hide any live terminal + loading node so the prompt is the only thing shown.
  Object.values(state.live).forEach((s) => { if (s.container) s.container.style.display = 'none'; });
  _ocHideLoadingState(tabId);
  const entry = _ocGetProjEntry(tabId, projectId);
  const isResume = !!entry.active;   // a known session id → "Resume", else "Start"
  let el = document.getElementById(_ocPromptId(tabId));
  if (!el) {
    el = document.createElement('div');
    el.id = _ocPromptId(tabId);
    el.className = 'gtp-term oc-start-prompt';
    state.termsEl.appendChild(el);
  }
  el.style.display = '';
  const title = isResume ? 'Resume coding agent' : 'Start coding agent';
  const sub = isResume
    ? 'Reconnect the OpenCode session for ' + escapeHtml(projectId) + '. Your work is preserved.'
    : 'Launch OpenCode for ' + escapeHtml(projectId) + '. The first start can take ~30s while it loads.';
  // A start/resume for this exact project may already be in flight (e.g. the
  // user switched skills mid-start and returned to the Code tab before it
  // resolved - _ocIsTerminalMounted is still false with nothing live yet, so
  // this prompt re-renders). Render it already busy rather than a fresh
  // clickable button: a click on that "fresh" button would hit
  // _ocStartOrResume's in-flight guard and silently no-op, leaving the
  // button enabled with no sign anything was happening.
  const busy = state._ocStartingProject === projectId;
  const busyLabel = isResume ? 'Resuming…' : 'Starting…';
  const idleLabel = isResume ? 'Resume' : 'Start';
  el.innerHTML =
    '<div class="oc-start-card">' +
      '<div class="oc-start-icon">&lt;/&gt;</div>' +
      '<div class="oc-start-title">' + escapeHtml(title) + '</div>' +
      '<div class="oc-start-sub">' + sub + '</div>' +
      (errMsg ? '<div class="oc-start-err">' + escapeHtml(String(errMsg)) + '</div>' : '') +
      '<button type="button" class="oc-start-btn' + (busy ? ' oc-start-btn--busy' : '') + '"' + (busy ? ' disabled' : '') + '>' +
        '<span class="oc-start-btn-spinner"></span>' +
        '<span class="oc-start-btn-label">' + escapeHtml(busy ? busyLabel : idleLabel) + '</span>' +
      '</button>' +
    '</div>';
  const btn = el.querySelector('.oc-start-btn');
  btn.addEventListener('click', () => {
    if (btn.disabled) return;
    // Instant feedback on the click itself, before _ocStartOrResume's own
    // async work even begins - real bug found via user report: the button
    // used to stay fully enabled and unchanged while work happened silently
    // behind it, indistinguishable from the click not registering at all.
    btn.disabled = true;
    btn.classList.add('oc-start-btn--busy');
    btn.querySelector('.oc-start-btn-label').textContent = busyLabel;
    // Defer to the next tick: _ocStartOrResume synchronously removes this
    // very button (_ocHideStartPrompt) before its first await, so calling it
    // in the SAME tick as the mutations above means the browser never gets a
    // chance to actually paint the busy state - both changes would land in
    // the same frame and the button would just vanish, which was the whole
    // bug being fixed here.
    setTimeout(() => _ocStartOrResume(tabId, projectId, repoPath), 0);
  });
}

// The explicit action behind the Start/Resume button (and the handoff auto-
// start). Resolves the cheapest correct path; shows progress; on failure
// re-renders the prompt with an error so retry is one click. In-flight guard
// (per tab) so rapid clicks don't stack starts.
async function _ocStartOrResume(tabId, projectId, repoPath) {
  const state = _ocEnsureTermsContainer(tabId);
  if (!state) return;
  // Guard is per-project, not per-tab: state is shared across every project
  // opened in this tab, and a slow start for project A (measured up to ~9s)
  // must not block a Resume click for project B once the user has switched -
  // that silently no-op'd with zero backend call and zero feedback, which is
  // exactly what looked like "the terminal isn't loading."
  if (state._ocStartingProject === projectId) return;
  state.projectId = projectId; state.repoPath = repoPath;
  _ocHideStartPrompt(tabId);
  state._ocStartingProject = projectId;
  try {
    // _ocReattachIfKnown handles BOTH the in-memory re-mount (instant, no
    // backend) and the backend reattach-with-progress; returns false if there's
    // no known session or the reattach failed → fall through to a fresh dispatch.
    const reattached = await _ocReattachIfKnown(tabId, projectId, repoPath);
    if (reattached) return;
    await _ocDispatch(tabId, projectId, repoPath);
  } catch (err) {
    // Re-derive rather than trusting the captured `state`: a project switch
    // mid-flight replaces the per-tab state object (_ocDetachAllForTab), so
    // the captured reference's .projectId is frozen and would always match
    // (tautology) - it must be re-read fresh to detect a switch-away.
    const current = _ocEnsureTermsContainer(tabId);
    if (current && current.projectId === projectId) {
      // Clear the in-flight flag BEFORE re-rendering the error prompt.
      // _ocShowStartPrompt reads _ocStartingProject to decide whether the
      // button renders busy (disabled + spinning). The finally below runs
      // AFTER this render, so without clearing it here the error prompt shows
      // a permanently-disabled, still-spinning "Starting…" button that
      // nothing ever re-renders - the exact "server did not start correctly,
      // but stuck on the spinner" bug reported on cold start.
      current._ocStartingProject = null;
      _ocHideLoadingState(tabId);
      _ocShowStartPrompt(tabId, projectId, repoPath, (err && err.message) || 'Could not start OpenCode');
    }
  } finally {
    if (state._ocStartingProject === projectId) state._ocStartingProject = null;
  }
}

// ── UX polish (OpenCodeIntegrationPlan.md §6) ──────────────────────────────────
// The context switch to a terminal pane is an accepted cost, not something to
// eliminate - these two pieces just soften the seam so it's never a silent,
// confusing jump.

// Drop a brief confirmation into Gator chat on handoff, same delivery
// mechanism as the native engine's existing "On it - watch the trace below"
// pattern (code_agent/tools.py's instructions_for_assistant fallback).
function _ocShowHandoffConfirmation() {
  if (typeof addMessage === 'function') {
    addMessage('assistant', 'Handed off to OpenCode — continue in the terminal.');
  }
}

// Session toggle pill - a static button in the chat input's guide row
// (index.html, next to #terminal-toggle), shown/hidden here rather than
// created/destroyed. Replaces an earlier floating text pill above
// #chat-form that had no click action at all (just information, no way
// back to the terminal); this one jumps straight back to the Code tab -
// see its onclick in index.html. Icon-only (no project name label) since
// that toolbar row is tight on horizontal space already - the name still
// shows on hover via the title attribute.
function _ocShowSessionToggle(projectName) {
  const btn = document.getElementById('oc-session-toggle');
  if (!btn) return;
  btn.title = 'OpenCode session active — ' + projectName;
  btn.style.display = '';
}
function _ocHideSessionToggle() {
  const btn = document.getElementById('oc-session-toggle');
  if (btn) btn.style.display = 'none';
}

// Real bug found via smoke-testing, not assumed: this toggle is a single
// global DOM element (not per Gator-chat-tab), so it needs an explicit
// check on every tab switch or it incorrectly keeps showing whichever tab
// last set it.
function _ocSyncSessionToggleOnTabSwitch(tabId) {
  const state = _ocTerminals[tabId];
  if (state && state.activeSessionId && state.live[state.activeSessionId]) {
    _ocShowSessionToggle(state.projectId);
  } else {
    _ocHideSessionToggle();
  }
}

// Auto-focus the middle pane on handoff rather than leaving the user to find
// it themselves - opens the Code tab pane if it isn't already the active one.
function _ocFocusMiddlePane() {
  if (typeof openThirdPane === 'function') openThirdPane('code_agent');
}
