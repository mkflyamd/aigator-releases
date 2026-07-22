// tp-generic-agent-terminal.js — terminal UI for generic, BYO-config coding
// agents (Claude Code CLI, Codex CLI, Crush, and a plain Terminal), as an
// alternative to the OpenCode integration in tp-opencode-terminal.js.
//
// Deliberately NOT sharing state or wiring with that file, to put zero
// regression risk on the (hard-won-stable) OpenCode path. It DOES call its
// pure, session-agnostic xterm helpers read-only (_ocSpawnTerm, _ocFit,
// _ocGuardSize) rather than re-implementing xterm setup/paste/keybindings —
// those only ever touch the `sess` object passed to them, never OpenCode's
// own _ocTerminals state.
//
// Multi-session per (tab, project): the tab strip is mounted in the SAME
// persistent #tp-detail-header toolbar row OpenCode uses (via its own
// ga-header-tabstrip element, mirroring _ocEnsureHeaderTabStrip) - not a
// second ribbon in the content area. Every tab is an independent process;
// all tabs use the project's currently selected agent (the per-project
// picker in tp-code-agent.js is unchanged).

// tabId -> {
//   termsEl,          // .gtp-terms container; session containers append here
//   agent, projectId, repoPath,
//   sessions: { ptyId: sess }, order: [ptyId...], activeId, seq, _starting
// }
let _genAgentTerminals = {};

function _genAgentPromptId(tabId) { return 'ga-startprompt-' + tabId; }
function _genAgentLoadingId(tabId) { return 'ga-loading-' + tabId; }

function _genAgentEnsureTermsContainer(tabId) {
  const detailCol = document.getElementById('tp-detail-col');
  if (!detailCol) return null;
  let state = _genAgentTerminals[tabId];
  if (state && state.termsEl) {
    if (state.termsEl.parentElement !== detailCol) {
      detailCol.appendChild(state.termsEl);
      state.termsEl.style.display = '';
    }
    return state;
  }
  const termsEl = document.createElement('div');
  termsEl.className = 'gtp-terms';
  detailCol.appendChild(termsEl);
  state = _genAgentTerminals[tabId] = state || {
    agent: null, projectId: null, repoPath: null,
    sessions: {}, order: [], activeId: null, seq: 0,
  };
  state.termsEl = termsEl;
  return state;
}

function _genAgentActiveSess(state) {
  return state && state.activeId ? state.sessions[state.activeId] : null;
}

// True only when THIS tab's active session is actually attached to the
// visible column right now (mirrors _ocIsTerminalMounted). agent is optional -
// omit it to ask "is anything mounted" (used by the picker's live-session
// check); pass it to ask "is THIS agent's session mounted", which
// _genAgentShowStartOrTerminal below needs - see its comment for why.
function _genAgentIsTerminalMounted(tabId, agent) {
  const state = _genAgentTerminals[tabId];
  const detailCol = document.getElementById('tp-detail-col');
  const sess = _genAgentActiveSess(state);
  return !!(state && state.termsEl && detailCol
            && state.termsEl.parentElement === detailCol
            && sess && sess.term
            && (agent === undefined || state.agent === agent));
}

function _genAgentShowStartOrTerminal(tabId, agent, projectId, repoPath) {
  // Must check that the MOUNTED session's agent matches the one being asked
  // for, not just "is anything mounted". Real bug found via user report:
  // switching a project from OpenCode to Claude showed a leftover PowerShell
  // terminal instead of Claude's own prompt - a "terminal" agent session had
  // been left mounted on this tabId from earlier (switching OpenCode <-> a
  // generic agent only detaches the OUTGOING agent's own state; it never
  // touches the OTHER agent's state, since a project switch away from that
  // one never went through it). Without the agent check here, this function
  // saw "something is mounted" and returned early, silently leaving the
  // stale terminal on screen instead of showing the Claude start prompt.
  if (_genAgentIsTerminalMounted(tabId, agent)) return;
  _genAgentShowStartPrompt(tabId, agent, projectId, repoPath);
}

// Re-attach still-alive sessions into the DOM on return to the Code tab (a
// skill switch tears down and rebuilds #tp-detail-col) - mirrors
// _ocMountActiveTab. Sessions survive in JS memory; their containers ride
// along inside the detached termsEl, so this just re-mounts, re-renders the
// header strip, and refits.
function _genAgentMountActiveTab(tabId) {
  if (typeof tpState === 'undefined' || tpState.type !== 'code_agent') return;
  const detailCol = document.getElementById('tp-detail-col');
  if (!detailCol) return;
  Object.keys(_genAgentTerminals).forEach((tid) => {
    if (tid !== String(tabId)) {
      const other = _genAgentTerminals[tid];
      if (other && other.termsEl && other.termsEl.parentElement === detailCol) other.termsEl.remove();
    }
  });
  const state = _genAgentTerminals[tabId];
  if (state && state.termsEl && state.termsEl.parentElement !== detailCol) {
    detailCol.appendChild(state.termsEl);
    state.termsEl.style.display = '';
  }
  _genAgentRenderTabs(tabId);
  const sess = _genAgentActiveSess(state);
  if (sess) setTimeout(() => _ocFit(sess), 20);
}

// ── Header tab strip (mounted in #tp-detail-header, same row/pattern as
// OpenCode's _ocEnsureHeaderTabStrip - reuses the oc-header-tabs styling) ──
function _genAgentHeaderTabStripId() { return 'ga-header-tabstrip'; }

function _genAgentEnsureHeaderTabStrip() {
  if (typeof tpState === 'undefined' || tpState.type !== 'code_agent') return null;
  const hdr = document.getElementById('tp-detail-header');
  if (!hdr) return null;
  // Exactly one header strip at a time - drop OpenCode's if it's up (this
  // project uses a generic agent, not OpenCode).
  if (typeof _ocRemoveHeaderTabStrip === 'function') _ocRemoveHeaderTabStrip();
  let strip = document.getElementById(_genAgentHeaderTabStripId());
  if (!strip) {
    strip = document.createElement('div');
    strip.id = _genAgentHeaderTabStripId();
    strip.className = 'gtp-tabs oc-header-tabs';
    const scroll = document.createElement('div');
    scroll.className = 'gtp-tabs-scroll';
    const newBtn = document.createElement('button');
    newBtn.type = 'button';
    newBtn.className = 'gtp-tab-new';
    newBtn.title = 'New terminal';
    newBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>';
    scroll.appendChild(newBtn);
    strip.appendChild(scroll);
    strip._scroll = scroll;
    strip._newBtn = newBtn;
    hdr.insertBefore(strip, hdr.firstChild);
  }
  return strip;
}

function _genAgentRemoveHeaderTabStrip() {
  document.getElementById(_genAgentHeaderTabStripId())?.remove();
}

function _genAgentSyncHeaderTabStripOnTabSwitch(tabId) {
  const state = _genAgentTerminals[tabId];
  if (state && state.order.length) _genAgentRenderTabs(tabId);
  else _genAgentRemoveHeaderTabStrip();
}

function _genAgentRenderTabs(tabId) {
  const state = _genAgentTerminals[tabId];
  if (!state || state.order.filter((id) => state.sessions[id]).length === 0) {
    _genAgentRemoveHeaderTabStrip();
    return;
  }
  const strip = _genAgentEnsureHeaderTabStrip();
  if (!strip) return;
  const scroll = strip._scroll;
  const newBtn = strip._newBtn;
  newBtn.onclick = () => _genAgentNewSession(tabId);
  [...scroll.querySelectorAll('.gtp-tab')].forEach((el) => el.remove());
  state.order.forEach((id) => {
    const sess = state.sessions[id];
    if (!sess) return;
    const tab = document.createElement('div');
    tab.className = 'gtp-tab' + (id === state.activeId ? ' active' : '');
    const label = document.createElement('span');
    label.className = 'gtp-tab-label';
    label.textContent = sess.label;
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'gtp-tab-close';
    x.title = 'Close';
    x.textContent = '✕';
    tab.appendChild(label);
    tab.appendChild(x);
    tab.addEventListener('click', (e) => { if (e.target === x) return; _genAgentActivateSession(tabId, id); });
    x.addEventListener('click', (e) => { e.stopPropagation(); _genAgentCloseSession(tabId, id); });
    scroll.insertBefore(tab, newBtn);
  });
}

// Show one session, hide the rest (hide, don't destroy - same as OpenCode).
function _genAgentActivateSession(tabId, ptyId) {
  const state = _genAgentTerminals[tabId];
  if (!state) return;
  state.activeId = ptyId;
  state.order.forEach((id) => {
    const s = state.sessions[id];
    if (s && s.container) s.container.style.display = (id === ptyId) ? '' : 'none';
  });
  _genAgentRenderTabs(tabId);
  const sess = state.sessions[ptyId];
  if (sess && sess.term) setTimeout(() => { _ocFit(sess); sess.term.focus(); }, 20);
}

// "+" - always spawns an independent new process of the project's agent.
function _genAgentNewSession(tabId) {
  const state = _genAgentTerminals[tabId];
  if (!state || !state.agent) return;
  _genAgentStart(tabId, state.agent, state.projectId, state.repoPath, { forceNew: true });
}

// "✕" - detach one session; activate a neighbor, or fall back to the start
// prompt if it was the last one. Never kills anything the user didn't click.
function _genAgentCloseSession(tabId, ptyId) {
  const state = _genAgentTerminals[tabId];
  if (!state) return;
  const idx = state.order.indexOf(ptyId);
  _genAgentDetachSession(tabId, ptyId);
  state.order = state.order.filter((id) => id !== ptyId);
  if (state.order.length === 0) {
    state.activeId = null;
    _genAgentRenderTabs(tabId);
    _genAgentShowStartPrompt(tabId, state.agent, state.projectId, state.repoPath);
    return;
  }
  const next = state.order[Math.min(idx, state.order.length - 1)];
  _genAgentActivateSession(tabId, next);
}

function _genAgentShowStartPrompt(tabId, agent, projectId, repoPath, errMsg) {
  const state = _genAgentEnsureTermsContainer(tabId);
  if (!state) return;
  state.agent = agent; state.projectId = projectId; state.repoPath = repoPath;
  const active = _genAgentActiveSess(state);
  if (active && active.container) active.container.style.display = 'none';
  _genAgentHideLoadingState(tabId);
  let el = document.getElementById(_genAgentPromptId(tabId));
  if (!el) {
    el = document.createElement('div');
    el.id = _genAgentPromptId(tabId);
    el.className = 'gtp-term oc-start-prompt';
    state.termsEl.appendChild(el);
  }
  el.style.display = '';
  const isBareTerminal = agent === 'terminal';
  const agentLabel = agent.charAt(0).toUpperCase() + agent.slice(1);
  const busy = state._starting === true;
  const busyLabel = isBareTerminal ? 'Opening…' : 'Starting…';
  const idleLabel = isBareTerminal ? 'Open' : 'Start';
  const title = isBareTerminal ? 'Open a terminal' : ('Start ' + agentLabel);
  const sub = isBareTerminal
    ? ('Open a plain shell in ' + projectId + '\'s directory - run any tool you like.')
    : ('Launch ' + agentLabel + ' for ' + projectId + ' using its own installed config.');
  el.innerHTML =
    '<div class="oc-start-card">' +
      '<div class="oc-start-icon">&lt;/&gt;</div>' +
      '<div class="oc-start-title">' + escapeHtml(title) + '</div>' +
      '<div class="oc-start-sub">' + escapeHtml(sub) + '</div>' +
      (errMsg ? '<div class="oc-start-err">' + escapeHtml(String(errMsg)) + '</div>' : '') +
      '<button type="button" class="oc-start-btn' + (busy ? ' oc-start-btn--busy' : '') + '"' + (busy ? ' disabled' : '') + '>' +
        '<span class="oc-start-btn-spinner"></span>' +
        '<span class="oc-start-btn-label">' + escapeHtml(busy ? busyLabel : idleLabel) + '</span>' +
      '</button>' +
    '</div>';
  const btn = el.querySelector('.oc-start-btn');
  btn.addEventListener('click', () => {
    if (btn.disabled) return;
    btn.disabled = true;
    btn.classList.add('oc-start-btn--busy');
    btn.querySelector('.oc-start-btn-label').textContent = busyLabel;
    // Same one-tick defer as the OpenCode prompt: _genAgentStart hides this
    // button synchronously before its first await, so calling it in the same
    // tick would never let the busy state paint.
    setTimeout(() => _genAgentStart(tabId, agent, projectId, repoPath), 0);
  });
}

function _genAgentHideStartPrompt(tabId) {
  document.getElementById(_genAgentPromptId(tabId))?.remove();
}

const _GENAGENT_LOADING_TIPS = [
  'Waking up the compiler',
  'Cloning into the swamp',
  'Untangling imports',
  'Warming up the REPL',
];

function _genAgentShowLoadingState(tabId) {
  const state = _genAgentEnsureTermsContainer(tabId);
  if (!state) return;
  const active = _genAgentActiveSess(state);
  if (active && active.container) active.container.style.display = 'none';
  let el = document.getElementById(_genAgentLoadingId(tabId));
  if (!el) {
    el = document.createElement('div');
    el.id = _genAgentLoadingId(tabId);
    el.className = 'gtp-term oc-loading-term';
    state.termsEl.appendChild(el);
  }
  el.style.display = '';
  el.innerHTML = typeof _gatorLoading === 'function' ? _gatorLoading(_GENAGENT_LOADING_TIPS) : '';
}

function _genAgentHideLoadingState(tabId) {
  document.getElementById(_genAgentLoadingId(tabId))?.remove();
}

// opts.forceNew: this is the "+" button - add a tab, never reattach an
// existing PTY (each tab is its own process).
async function _genAgentStart(tabId, agent, projectId, repoPath, opts) {
  opts = opts || {};
  const state = _genAgentEnsureTermsContainer(tabId);
  if (!state) return;
  if (state._starting) return;
  state.agent = agent; state.projectId = projectId; state.repoPath = repoPath;
  _genAgentHideStartPrompt(tabId);
  state._starting = true;
  _genAgentShowLoadingState(tabId);
  try {
    const headers = typeof _caHeadersAsync === 'function' ? await _caHeadersAsync() : { 'Content-Type': 'application/json' };
    const resp = await fetch('/api/generic-agent/terminal', {
      method: 'POST', headers,
      body: JSON.stringify({ agent, project_id: projectId, repo_path: repoPath, force_new: !!opts.forceNew }),
    });
    if (!resp.ok) {
      let detail = 'Could not start ' + agent;
      try { const d = await resp.json(); if (d && d.detail) detail = d.detail; } catch (_) {}
      throw new Error(detail);
    }
    const data = await resp.json();
    // Staleness guard: bail without attaching if the user has since switched
    // this tab to a different project OR a different agent while the request
    // was in flight (both replace/repoint this tab's state).
    const current = _genAgentTerminals[tabId];
    if (!current || current.projectId !== projectId || current.agent !== agent) return;
    _genAgentHideLoadingState(tabId);
    _genAgentAttachTerminal(tabId, data.pty_session_id, agent);
  } catch (err) {
    _genAgentHideLoadingState(tabId);
    const current = _genAgentTerminals[tabId];
    if (current && current.projectId === projectId && current.agent === agent) {
      // Clear the in-flight flag BEFORE re-rendering: _genAgentShowStartPrompt
      // reads _starting to decide whether the button renders busy (disabled +
      // spinning), and the finally below runs after this render. Without this,
      // a failed start (notably a not-installed Codex/Crush) would show the
      // error text inside a permanently stuck spinner instead of a clickable
      // retry. Same bug fixed in _ocStartOrResume.
      current._starting = false;
      // Only fall back to the full-pane prompt if there are no other live
      // sessions - if a "+" spawn failed, keep the existing tabs and surface
      // the error rather than blowing away the working terminals.
      if (current.order.length === 0) {
        _genAgentShowStartPrompt(tabId, agent, projectId, repoPath, (err && err.message) || 'Could not start ' + agent);
      } else {
        if (typeof addMessage === 'function') addMessage('assistant', '⚠️ ' + ((err && err.message) || ('Could not start ' + agent)));
        const active = _genAgentActiveSess(current);
        if (active) _genAgentActivateSession(tabId, active.ptySessionId);
      }
    }
  } finally {
    if (state._starting) state._starting = false;
  }
}

function _genAgentAttachTerminal(tabId, ptySessionId, agent) {
  const state = _genAgentTerminals[tabId];
  if (!state) return;
  // Already have this exact session live (reattach on cold reopen) - just show it.
  if (state.sessions[ptySessionId] && state.sessions[ptySessionId].term) {
    _genAgentActivateSession(tabId, ptySessionId);
    return;
  }
  const container = document.createElement('div');
  container.className = 'gtp-term';
  container.style.display = 'none';
  state.termsEl.appendChild(container);

  state.seq += 1;
  const isBareTerminal = agent === 'terminal';
  const base = isBareTerminal ? 'Terminal' : (agent.charAt(0).toUpperCase() + agent.slice(1));
  const sess = {
    tabId, ptySessionId, container, agent,
    label: base + ' ' + state.seq, _retryDelay: 0,
  };
  state.sessions[ptySessionId] = sess;
  state.order.push(ptySessionId);
  state.activeId = ptySessionId;
  _ocSpawnTerm(sess);   // shared, session-agnostic xterm setup (see file header)
  _genAgentConnect(sess);
  _ocGuardSize(sess);   // shared ResizeObserver wiring
  _genAgentRenderTabs(tabId);
}

function _genAgentRevealSession(sess) {
  if (!sess) return;
  const state = _genAgentTerminals[sess.tabId];
  // Only reveal if this is still the active session - first output on a
  // background ("+") tab shouldn't yank the view off whatever's focused.
  if (!state || state.activeId !== sess.ptySessionId) return;
  _genAgentHideLoadingState(sess.tabId);
  if (sess.container) sess.container.style.display = '';
  setTimeout(() => { _ocFit(sess); sess.term && sess.term.focus(); }, 20);
}

function _genAgentDetachSession(tabId, ptyId) {
  const state = _genAgentTerminals[tabId];
  const sess = state && state.sessions[ptyId];
  if (!sess) return;
  sess._closing = true;
  clearTimeout(sess._resizeDebounce);
  try { sess._sizeObserver && sess._sizeObserver.disconnect(); } catch (_) {}
  try { sess.ws && sess.ws.close(); } catch (_) {}
  try { sess.term && sess.term.dispose(); } catch (_) {}
  try { sess.container && sess.container.remove(); } catch (_) {}
  delete state.sessions[ptyId];
}

// Full teardown for this tab - detaches every session, removes the wrapper
// AND the header strip, mirroring _ocDetachAllForTab. Used when leaving this
// agent entirely (e.g. switching the project to a different agent).
function _genAgentDetachAllForTab(tabId) {
  const state = _genAgentTerminals[tabId];
  if (!state) return;
  (state.order || []).slice().forEach((id) => _genAgentDetachSession(tabId, id));
  try { state.termsEl && state.termsEl.remove(); } catch (_) {}
  _genAgentRemoveHeaderTabStrip();
  delete _genAgentTerminals[tabId];
}

// WebSocket connect/reconnect - same shape as _ocConnect: the exit vs.
// transient-drop distinction, backoff, and restart affordance are generically
// useful, not OpenCode-specific.
function _genAgentConnect(sess, retryDelay) {
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
        sess._hasOutput = true;
        _genAgentRevealSession(sess);
      }
    } else if (msg.type === 'exit') {
      sess._dead = true;
      sess.term && sess.term.write('\r\n\x1b[33m[' + (msg.data || 'Session ended') + ']\x1b[0m\r\n');
      _genAgentShowRestartOverlay(sess, msg.data || 'Session ended');
    }
  };
  sess.ws.onerror = () => { /* onclose handles retry */ };
  sess.ws.onclose = () => {
    if (!sess.term || sess._closing || sess._dead) return;
    const attempt = (sess._retryAttempt || 0) + 1;
    sess._retryAttempt = attempt;
    const next = Math.min(500 * attempt, 8000);
    sess.term.write('\r\n\x1b[33m[disconnected — reconnecting (attempt ' + attempt + ') in '
      + Math.round(next / 1000) + 's…]\x1b[0m\r\n');
    setTimeout(() => {
      if (!sess.term || sess._closing || sess._dead) return;
      _genAgentConnect(sess, next);
    }, next);
  };
}

function _genAgentShowRestartOverlay(sess, reason) {
  if (!sess.container) return;
  if (sess.container.querySelector('.oc-restart-overlay')) return;
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
    const state = _genAgentTerminals[sess.tabId];
    if (!state) return;
    const hadOthers = (state.order || []).filter((id) => id !== sess.ptySessionId).length > 0;
    // Drop the dead session, then spawn a fresh one in its place.
    _genAgentCloseSession(sess.tabId, sess.ptySessionId);
    _genAgentStart(sess.tabId, state.agent, state.projectId, state.repoPath, { forceNew: hadOthers });
  });
  overlay.appendChild(msg);
  overlay.appendChild(btn);
  sess.container.appendChild(overlay);
}
