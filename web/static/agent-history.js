// Agent session history: pure helpers (grouping, live state, search), exported
// for node tests, followed by the browser-only History panel controller.
(function (root) {
  'use strict';

  const WORKING_MS = 12000;
  const GROUPS = [
    { key: 'needs_you', title: 'Needs you' },
    { key: 'working', title: 'Working' },
    { key: 'today', title: 'Today' },
    { key: 'yesterday', title: 'Yesterday' },
    { key: 'earlier', title: 'Earlier' },
  ];

  // ts is epoch seconds (server clock); nowMs is epoch milliseconds.
  function dayGroup(ts, nowMs) {
    const now = new Date(nowMs);
    const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const startYesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1).getTime();
    const t = ts * 1000;
    if (t >= startToday) return 'today';
    if (t >= startYesterday) return 'yesterday';
    return 'earlier';
  }

  function relTime(ts, nowMs) {
    const sec = Math.max(0, Math.floor(nowMs / 1000 - ts));
    if (sec < 45) return 'just now';
    const min = Math.floor(sec / 60);
    if (min < 60) return Math.max(1, min) + ' min ago';
    const hr = Math.floor(min / 60);
    if (hr < 24) return hr + ' h ago';
    const day = Math.floor(hr / 24);
    if (day < 7) return day + ' d ago';
    return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  // term._lastOutputAt and term._viewedAt are epoch milliseconds.
  function liveState(term, nowMs) {
    const out = term._lastOutputAt || 0;
    if (out && nowMs - out < WORKING_MS) return 'working';
    if (out && out > (term._viewedAt || 0)) return 'needs_you';
    return 'done';
  }

  function needsYou(terminals, nowMs) {
    return (terminals || []).some((t) => liveState(t, nowMs) === 'needs_you');
  }

  function groupOf(state, lastActive, nowMs) {
    return state === 'needs_you' || state === 'working' ? state : dayGroup(lastActive, nowMs);
  }

  function buildRows(sessions, terminals, nowMs, agentLabel) {
    const label = agentLabel || ((a) => a);
    const live = new Map();
    (terminals || []).forEach((t) => {
      if (t.ptySessionId) live.set(t.ptySessionId, t);
    });
    const claimed = new Set();
    const rows = (sessions || []).map((s) => {
      const term = s.pty_session_id ? live.get(s.pty_session_id) : null;
      if (term) claimed.add(term.ptySessionId);
      const state = term ? liveState(term, nowMs) : 'done';
      const lastActive =
        term && term._lastOutputAt
          ? Math.max(s.last_active_at, term._lastOutputAt / 1000)
          : s.last_active_at;
      return {
        key: s.agent + ':' + s.id,
        id: s.id,
        agent: s.agent,
        title: (term && term.userLabel) || s.title,
        branch: s.branch || '',
        source: s.source,
        lastActive,
        state,
        group: groupOf(state, lastActive, nowMs),
        ptySessionId: term ? term.ptySessionId : null,
        liveElsewhere: !term && !!s.live_elsewhere,
        elsewhereIn: !term && s.live_elsewhere ? s.live_elsewhere_in || null : null,
      };
    });
    live.forEach((term, pty) => {
      if (claimed.has(pty) || term.agent === 'terminal') return;
      const state = liveState(term, nowMs);
      const lastActive = (term._lastOutputAt || nowMs) / 1000;
      rows.push({
        key: 'live:' + pty,
        id: null,
        agent: term.agent,
        title: term.userLabel || 'New ' + label(term.agent) + ' session',
        branch: '',
        source: 'windows',
        lastActive,
        state,
        group: groupOf(state, lastActive, nowMs),
        ptySessionId: pty,
        liveElsewhere: false,
        elsewhereIn: null,
      });
    });
    return rows;
  }

  function syncTabLabels(rows, terminals) {
    const byPty = new Map();
    (terminals || []).forEach((t) => {
      if (t.ptySessionId) byPty.set(t.ptySessionId, t);
    });
    let changed = false;
    (rows || []).forEach((r) => {
      const term = r.id && r.ptySessionId ? byPty.get(r.ptySessionId) : null;
      if (!term || term.userLabel || !r.title || term.label === r.title) return;
      term.label = r.title;
      changed = true;
    });
    return changed;
  }

  function shortAge(ts, nowMs) {
    const sec = Math.max(0, Math.floor(nowMs / 1000 - ts));
    if (sec < 60) return '<1m';
    if (sec < 3600) return Math.floor(sec / 60) + 'm';
    if (sec < 86400) return Math.floor(sec / 3600) + 'h';
    return Math.floor(sec / 86400) + 'd';
  }

  function metaLine(row, nowMs, agentLabel) {
    const label = agentLabel || ((a) => a);
    let when;
    if (row.state === 'needs_you') when = 'waiting ' + shortAge(row.lastActive, nowMs);
    else if (row.state === 'working') when = shortAge(row.lastActive, nowMs);
    else when = relTime(row.lastActive, nowMs);
    const parts = [label(row.agent)];
    if (row.branch) parts.push(row.branch);
    if (row.source && row.source !== 'windows') parts.push('WSL');
    parts.push(when);
    return parts.join(' · ');
  }

  const TRANSCRIPT_AGENTS = ['claude', 'codex'];

  function rowActions(row) {
    if (row.ptySessionId) return ['go', 'handoff'];
    return TRANSCRIPT_AGENTS.includes(row.agent) ? ['resume', 'handoff'] : ['resume'];
  }

  // What clicking the row itself does: the same as its first action chip. A live row whose
  // terminal is already on screen has nothing to do (its Go to terminal chip is disabled).
  function primaryAction(row, viewing) {
    const first = rowActions(row)[0];
    return first === 'go' && viewing ? null : first;
  }

  // The row is the terminal whose tab is the active one in the strip.
  function isActiveTerminal(row, activeId) {
    return !!row.ptySessionId && !!activeId && row.ptySessionId === activeId;
  }

  function filterGroups(rows, query) {
    const words = String(query || '')
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean);
    const hit = (r) => {
      const hay = (r.title + ' ' + r.branch + ' ' + r.agent).toLowerCase();
      return words.every((w) => hay.includes(w));
    };
    return GROUPS.map((g) => ({
      key: g.key,
      title: g.title,
      rows: rows
        .filter((r) => r.group === g.key && hit(r))
        .sort((a, b) => b.lastActive - a.lastActive),
    })).filter((g) => g.rows.length);
  }

  // Where the preview card goes: just right of the panel, level with the row, never off
  // screen. Falls back to the panel's left, then to overlapping it. Rects are in viewport px.
  function flyoutPlacement(anchor, panel, card, view) {
    const GAP = 8;
    const EDGE = 8;
    let left = panel.right + GAP;
    if (left + card.width > view.width - EDGE) {
      const before = panel.left - GAP - card.width;
      left = before >= EDGE ? before : Math.max(EDGE, view.width - EDGE - card.width);
    }
    const top = Math.max(EDGE, Math.min(anchor.top, view.height - EDGE - card.height));
    return { left, top };
  }

  // ── Browser panel ────────────────────────────────────────────────────────
  const FETCH_MS = 15000;
  const TICK_MS = 2000;
  const WSL_POLL_MS = 2000;
  const WSL_POLL_MAX = 5;
  const HOVER_MS = 300;
  const GRACE_MS = 150;
  const PREVIEW_DEBOUNCE_MS = 200;

  const ui = {
    sessions: [],
    project: null,
    wslPending: false,
    wslPolls: 0,
    wslTimer: null,
    error: false,
    loaded: false,
    busy: false,
    fetchedAt: 0,
    query: '',
    previews: {},
    notice: {},
    rows: new Map(),
    sig: '',
  };

  // The hover/focus preview card. key is the row it shows; hover is the row under the
  // pointer; dismissed is a row closed with Escape, kept shut until the pointer or focus leaves.
  const fly = {
    key: null,
    row: null,
    hover: null,
    dismissed: null,
    closedAt: 0,
    showTimer: null,
    hideTimer: null,
    fetchTimer: null,
    rendering: false,
    scrollTop: 0,
  };

  function agentName(agent) {
    return typeof _genAgentLabel === 'function' ? _genAgentLabel(agent) : agent;
  }

  function context() {
    const tabId = typeof _activeTabId !== 'undefined' ? _activeTabId : null;
    const project =
      typeof _caProjects !== 'undefined' && typeof _caActiveProject !== 'undefined'
        ? _caProjects.find((p) => p.name === _caActiveProject) || null
        : null;
    return { tabId, project };
  }

  function terminalState(tabId) {
    if (tabId === null || typeof _genAgentTerminals === 'undefined') return null;
    return _genAgentTerminals[_caSessionKey(tabId)] || null;
  }

  function liveSessions() {
    const { tabId, project } = context();
    const st = terminalState(tabId);
    if (!st || !project || st.projectId !== project.name) return [];
    return st.order.map((id) => st.sessions[id]).filter(Boolean);
  }

  function panelVisible() {
    const pane = document.getElementById('ca-hist-view');
    return !!pane && pane.getClientRects().length > 0;
  }

  // True while the session's terminal is on screen (its container and every
  // ancestor displayed) in a visible window, so its new output counts as seen.
  function isViewing(sess) {
    if (typeof document === 'undefined') return false;
    return (
      !!sess && !!sess.container && sess.container.getClientRects().length > 0 && !document.hidden
    );
  }

  function updateDot() {
    const btn = document.getElementById('ca-viewtab-history');
    if (!btn) return;
    const agents = liveSessions().filter((t) => t.agent !== 'terminal');
    const attention = needsYou(agents, Date.now());
    btn.classList.toggle('has-attention', attention);
    const text = attention ? 'History (a session needs you)' : 'History';
    btn.title = text;
    btn.setAttribute('aria-label', text);
  }

  function applyTabState(tabEl, term, nowMs) {
    const icon = tabEl && tabEl.querySelector('.gtp-tab-icon');
    if (!icon) return;
    const state = term && term.agent !== 'terminal' ? liveState(term, nowMs) : 'done';
    const want = state === 'needs_you' || state === 'working' ? 'ah-dot ah-dot-' + state : '';
    const dot = icon.querySelector('.ah-dot');
    if (!want) {
      if (dot) dot.remove();
    } else if (dot) {
      if (dot.className !== want) dot.className = want;
    } else {
      const created = document.createElement('span');
      created.className = want;
      created.setAttribute('aria-hidden', 'true');
      icon.appendChild(created);
    }
  }

  function updateTabDots() {
    if (typeof _genAgentHeaderTabStripId !== 'function') return;
    const st = terminalState(context().tabId);
    const scroll = document.querySelector('#' + _genAgentHeaderTabStripId() + ' .gtp-tabs-scroll');
    if (!st || !scroll) return;
    const now = Date.now();
    scroll.querySelectorAll('.gtp-tab').forEach((tabEl) => {
      applyTabState(tabEl, st.sessions[tabEl.dataset.sid], now);
    });
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function fetcher() {
    return typeof _ocFetch === 'function' ? _ocFetch : fetch;
  }

  async function load() {
    const { project } = context();
    if (!project) {
      hideFlyout();
      ui.project = null;
      ui.sessions = [];
      ui.loaded = true;
      render();
      return;
    }
    if (ui.busy) return;
    if (ui.project !== project.name) {
      hideFlyout();
      ui.project = project.name;
      ui.sessions = [];
      ui.loaded = false;
      ui.previews = {};
      ui.notice = {};
      ui.wslPolls = 0;
      render();
    }
    ui.busy = true;
    ui.fetchedAt = Date.now();
    const params = new URLSearchParams({ project_name: project.name });
    liveSessions().forEach((t) => {
      if (t.ptySessionId && t.agent !== 'terminal')
        params.append('pty', t.agent + ':' + t.ptySessionId);
    });
    try {
      const resp = await fetcher()('/api/agent-sessions?' + params.toString());
      if (!resp.ok) throw new Error('status ' + resp.status);
      const data = await resp.json();
      const now = context().project;
      if (!now || now.name !== project.name) return;
      ui.sessions = data.sessions || [];
      ui.wslPending = !!data.wsl_pending;
      ui.error = false;
    } catch (_) {
      ui.error = true;
    } finally {
      ui.busy = false;
    }
    ui.loaded = true;
    render();
    scheduleWslPoll();
  }

  function scheduleWslPoll() {
    if (ui.wslTimer || !ui.wslPending || ui.wslPolls >= WSL_POLL_MAX) return;
    ui.wslPolls += 1;
    ui.wslTimer = setTimeout(() => {
      ui.wslTimer = null;
      if (panelVisible()) load();
    }, WSL_POLL_MS);
  }

  function closeFileView() {
    if (document.getElementById('ca-file-diff-view') && typeof _caCloseFileDiff === 'function') {
      _caCloseFileDiff('ca-file-diff-view');
    }
  }

  function goToTerminal(row) {
    const { tabId } = context();
    if (tabId === null || typeof _genAgentActivateSession !== 'function') return;
    closeFileView();
    _genAgentActivateSession(tabId, row.ptySessionId);
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (c) => '&#' + c.charCodeAt(0) + ';');
  }

  function elsewhereText(where) {
    if (!where) return 'another window';
    return (where.app || 'another program') + ' (process ' + where.pid + ')';
  }

  function takeoverBody(where) {
    return escapeHtml(
      'This session is open in ' +
        elsewhereText(where) +
        '. Gator will close it there and open it here. Anything unsaved in that window is lost.',
    );
  }

  function confirmTakeover(row, where) {
    if (typeof _showConfirmModal !== 'function') return;
    _showConfirmModal(
      'Session open elsewhere',
      takeoverBody(where || row.elsewhereIn),
      'Close and open here',
      () => takeover(row),
    );
  }

  async function takeover(row) {
    const { project } = context();
    if (!project) return;
    const headers =
      typeof _caHeadersAsync === 'function'
        ? await _caHeadersAsync()
        : { 'Content-Type': 'application/json' };
    let message = 'Could not close the session where it is open.';
    try {
      const resp = await fetcher()('/api/generic-agent/takeover', {
        method: 'POST',
        headers,
        body: JSON.stringify({ agent: row.agent, repo_path: project.repo_path, resume_id: row.id }),
      });
      if (resp.ok) {
        resume(row, true);
        return;
      }
      const d = await resp.json();
      if (d && d.detail)
        message = typeof d.detail === 'object' ? d.detail.message || message : d.detail;
    } catch (_) {}
    ui.notice[row.key] = message;
    render();
  }

  async function resume(row, tookOver) {
    const { tabId, project } = context();
    if (!project || typeof _genAgentStart !== 'function') return;
    if (typeof _genAgentStartInFlight === 'function' && _genAgentStartInFlight(tabId)) return;
    if (row.liveElsewhere && !tookOver) {
      confirmTakeover(row);
      return;
    }
    let asked = false;
    const before = terminalState(tabId);
    const count = before ? before.order.length : 0;
    closeFileView();
    await _genAgentStart(tabId, row.agent, project.name, project.repo_path, {
      forceNew: true,
      resumeId: row.id,
      onSessionLive: (err) => {
        asked = true;
        confirmTakeover(row, err && err.where);
      },
      keepStateAgent: !!(before && before.agent),
    });
    if (asked) return;
    const after = terminalState(tabId);
    if (after && after.order.length > count) {
      delete ui.notice[row.key];
      load();
      return;
    }
    ui.notice[row.key] = 'Could not resume this session.';
    render();
    load();
  }

  function handoff(row) {
    const { tabId, project } = context();
    if (!project || !window.agentHandoff) return;
    if (row.ptySessionId) {
      const sess = liveSessions().find((t) => t.ptySessionId === row.ptySessionId);
      if (sess) window.agentHandoff.openDialog({ tabId, sess });
      return;
    }
    window.agentHandoff.openDialog({
      tabId,
      sess: { agent: row.agent },
      stored: { agent: row.agent, id: row.id },
      project: { id: project.name, repoPath: project.repo_path },
    });
  }

  async function loadPreview(row) {
    const { project } = context();
    if (!project) return;
    const prev = ui.previews[row.key];
    if (!prev || prev.status !== 'ok') {
      ui.previews[row.key] = { status: 'loading' };
      paintFlyout(row.key);
    }
    let result;
    try {
      const url =
        '/api/agent-sessions/' +
        encodeURIComponent(row.agent) +
        '/' +
        encodeURIComponent(row.id) +
        '/preview?project_name=' +
        encodeURIComponent(project.name);
      const resp = await fetcher()(url);
      if (resp.status === 404) {
        result = { status: 'error', message: 'This session is no longer on disk.' };
        load();
      } else if (!resp.ok) {
        result = { status: 'error', message: 'Could not load the preview.' };
      } else {
        const data = await resp.json();
        result = { status: 'ok', messages: data.messages || [] };
      }
    } catch (_) {
      result = { status: 'error', message: 'Could not load the preview.' };
    }
    if (ui.project !== project.name) return;
    result.at = Date.now();
    ui.previews[row.key] = result;
    paintFlyout(row.key);
  }

  // A stroked line icon built with createElementNS (no markup strings).
  function lineIcon(cls, paths) {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    if (cls) svg.setAttribute('class', cls);
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    paths.forEach((d) => {
      const path = document.createElementNS(NS, 'path');
      path.setAttribute('d', d);
      svg.appendChild(path);
    });
    return svg;
  }

  // The terminal prompt icon from the terminal tab icon set.
  function terminalIcon() {
    return lineIcon('', ['m5 8 5 4-5 4', 'M13 17h6']);
  }

  function searchIcon() {
    return lineIcon('ah-search-icon', [
      'M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13z',
      'm20 20-4.7-4.7',
    ]);
  }

  // ── Preview card ─────────────────────────────────────────────────────────
  function flyoutEl() {
    let card = document.getElementById('ah-flyout');
    if (!card) {
      card = el('div', 'ah-flyout');
      card.id = 'ah-flyout';
      card.setAttribute('role', 'tooltip');
      document.body.appendChild(card);
    }
    return card;
  }

  function itemFor(key) {
    const list = document.getElementById('ca-hist-list');
    if (!list || !key) return null;
    return Array.from(list.querySelectorAll('.ah-item')).find((i) => i.dataset.key === key) || null;
  }

  function markRow(key, on) {
    const item = itemFor(key);
    if (!item) return;
    item.classList.toggle('is-previewed', on);
    const head = item.querySelector('.ah-row');
    if (on) head.setAttribute('aria-describedby', 'ah-flyout');
    else head.removeAttribute('aria-describedby');
  }

  function hideFlyout() {
    clearTimeout(fly.showTimer);
    clearTimeout(fly.hideTimer);
    clearTimeout(fly.fetchTimer);
    fly.showTimer = fly.hideTimer = fly.fetchTimer = null;
    if (!fly.key) return;
    markRow(fly.key, false);
    fly.key = null;
    fly.row = null;
    fly.closedAt = Date.now();
    const card = document.getElementById('ah-flyout');
    if (card) card.classList.remove('is-open');
  }

  function previewFresh(key) {
    const pv = ui.previews[key];
    if (!pv) return false;
    return pv.status === 'loading' || (pv.status === 'ok' && Date.now() - pv.at < FETCH_MS);
  }

  function showFlyout(row) {
    if (!panelVisible()) {
      hideFlyout();
      return;
    }
    clearTimeout(fly.showTimer);
    clearTimeout(fly.hideTimer);
    fly.showTimer = fly.hideTimer = null;
    if (fly.key !== row.key) {
      if (fly.key) markRow(fly.key, false);
      clearTimeout(fly.fetchTimer);
      fly.fetchTimer = null;
    }
    fly.key = row.key;
    fly.row = row;
    markRow(row.key, true);
    paintFlyout(row.key);
    // Debounced so sweeping the pointer down the list only fetches where it settles.
    if (row.id && !previewFresh(row.key) && !fly.fetchTimer) {
      fly.fetchTimer = setTimeout(() => {
        fly.fetchTimer = null;
        if (fly.key === row.key) loadPreview(row);
      }, PREVIEW_DEBOUNCE_MS);
    }
  }

  function statePill(row) {
    if (row.liveElsewhere) {
      const pill = el('span', 'ah-pill ah-pill-elsewhere', 'Open elsewhere');
      pill.title = 'Open in ' + elsewhereText(row.elsewhereIn);
      return pill;
    }
    if (row.state !== 'needs_you' && row.state !== 'working') return null;
    const text = row.state === 'needs_you' ? 'Needs you' : 'Working';
    return el('span', 'ah-pill ah-pill-' + row.state, text);
  }

  function previewBody(row) {
    const body = el('div', 'ah-fly-body');
    const pv = ui.previews[row.key];
    if (!row.id) {
      body.appendChild(el('div', 'ah-note', 'Live session. Its preview appears once it is saved.'));
    } else if (!pv || pv.status === 'loading') {
      body.appendChild(el('div', 'ah-note', 'Loading preview…'));
    } else if (pv.status === 'error') {
      body.appendChild(el('div', 'ah-note', pv.message));
    } else if (!pv.messages.length) {
      body.appendChild(el('div', 'ah-note', 'Nothing to preview yet.'));
    } else {
      pv.messages.forEach((m) => {
        const user = m.role === 'user';
        const msg = el('div', 'ah-msg ' + (user ? 'ah-msg-user' : 'ah-msg-assistant'));
        msg.appendChild(el('span', 'ah-role', user ? 'You' : 'Agent'));
        msg.appendChild(el('span', 'ah-text', m.text));
        body.appendChild(msg);
      });
    }
    return body;
  }

  function paintFlyout(key) {
    if (!fly.key || fly.key !== key) return;
    if (!panelVisible()) {
      hideFlyout();
      return;
    }
    const row = fly.row;
    const item = itemFor(key);
    const panel = document.getElementById('ca-hist-view');
    if (!item || !panel) {
      hideFlyout();
      return;
    }
    const card = flyoutEl();
    card.textContent = '';
    const head = el('div', 'ah-fly-head');
    const top = el('div', 'ah-fly-top');
    top.appendChild(el('div', 'ah-fly-title', row.title));
    const pill = statePill(row);
    if (pill) top.appendChild(pill);
    head.appendChild(top);
    head.appendChild(el('div', 'ah-fly-meta', metaLine(row, Date.now(), agentName)));
    card.appendChild(head);
    const body = previewBody(row);
    card.appendChild(body);
    body.classList.toggle('is-clipped', body.scrollHeight > body.clientHeight + 1);
    const pos = flyoutPlacement(
      item.getBoundingClientRect(),
      panel.getBoundingClientRect(),
      { width: card.offsetWidth, height: card.offsetHeight },
      { width: window.innerWidth, height: window.innerHeight },
    );
    card.style.left = pos.left + 'px';
    card.style.top = pos.top + 'px';
    card.classList.add('is-open');
  }

  // The pointer moved onto a row (key) or off the rows (null). The first card waits
  // HOVER_MS; once one is showing, or was just closed, moving to the next row swaps at once.
  function pointAt(key) {
    if (key === fly.hover) return;
    fly.hover = key;
    clearTimeout(fly.showTimer);
    fly.showTimer = null;
    if (fly.dismissed && fly.dismissed !== key) fly.dismissed = null;
    if (!key) {
      if (fly.key && !fly.hideTimer) fly.hideTimer = setTimeout(hideFlyout, GRACE_MS);
      return;
    }
    if (key === fly.dismissed) return;
    const open = () => {
      const row = ui.rows.get(key);
      if (row) showFlyout(row);
    };
    if (fly.key || Date.now() - fly.closedAt < GRACE_MS) open();
    else fly.showTimer = setTimeout(open, HOVER_MS);
  }

  function focusRow(key) {
    const row = ui.rows.get(key);
    if (row && key !== fly.dismissed) showFlyout(row);
  }

  function blurRow(key) {
    if (fly.dismissed === key) fly.dismissed = null;
    if (fly.key === key && fly.hover !== key) hideFlyout();
  }

  function rowKey(node) {
    const item = node && node.closest ? node.closest('.ah-item') : null;
    return item ? item.dataset.key : null;
  }

  // Listeners live on the list (and document), not on rows, so tick re-renders keep them.
  function bindList() {
    const list = document.getElementById('ca-hist-list');
    if (!list || list.dataset.bound) return;
    list.dataset.bound = '1';
    // The whole row is the primary action. Chips are buttons that stop their own clicks;
    // the guard here also keeps any other control inside the item from triggering it.
    list.addEventListener('click', (e) => {
      if (e.target.closest('button, a, input')) return;
      const key = rowKey(e.target);
      if (key) activateRow(ui.rows.get(key));
    });
    list.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      if (!e.target.classList || !e.target.classList.contains('ah-row')) return;
      e.preventDefault();
      activateRow(ui.rows.get(rowKey(e.target)));
    });
    list.addEventListener('mouseover', (e) => pointAt(rowKey(e.target)));
    list.addEventListener('mouseleave', () => pointAt(null));
    list.addEventListener('focusin', (e) => {
      if (!fly.rendering) focusRow(rowKey(e.target));
    });
    list.addEventListener('focusout', (e) => {
      if (fly.rendering || rowKey(e.relatedTarget) === rowKey(e.target)) return;
      blurRow(rowKey(e.target));
    });
    list.addEventListener('scroll', () => {
      if (list.scrollTop === fly.scrollTop) return;
      fly.scrollTop = list.scrollTop;
      hideFlyout();
    });
    if (!document.documentElement.dataset.ahEscape) {
      document.documentElement.dataset.ahEscape = '1';
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && fly.key) {
          fly.dismissed = fly.key;
          hideFlyout();
        }
      });
    }
  }

  // After a rebuild, point the card at the new row element, or close it if the row is gone.
  function syncFlyout() {
    if (!fly.key) return;
    const row = ui.rows.get(fly.key);
    if (!row || !itemFor(fly.key)) {
      hideFlyout();
      return;
    }
    fly.row = row;
    markRow(fly.key, true);
    paintFlyout(fly.key);
  }

  // A live row's terminal is the one on screen, so Go to terminal has nothing to do.
  function rowViewing(row) {
    if (!row.ptySessionId) return false;
    return isViewing(liveSessions().find((t) => t.ptySessionId === row.ptySessionId));
  }

  function rowActive(row) {
    const st = terminalState(context().tabId);
    if (!st || !isActiveTerminal(row, st.activeId)) return false;
    return liveSessions().some((t) => t.ptySessionId === row.ptySessionId);
  }

  function setRowActive(item, active) {
    item.classList.toggle('ah-active', active);
    const head = item.querySelector('.ah-row');
    if (!head) return;
    if (active) head.setAttribute('aria-current', 'true');
    else head.removeAttribute('aria-current');
  }

  // Mirror the tab strip's active tab onto the rows without rebuilding the list.
  function syncActive() {
    const list = document.getElementById('ca-hist-list');
    if (!list) return;
    list.querySelectorAll('.ah-item').forEach((item) => {
      const row = ui.rows.get(item.dataset.key);
      setRowActive(item, !!row && rowActive(row));
    });
  }

  function activateRow(row) {
    if (!row) return;
    const action = primaryAction(row, rowViewing(row));
    if (action === 'go') goToTerminal(row);
    else if (action === 'resume') resume(row);
  }

  function actionButton(row, action) {
    const spec = {
      go: [terminalIcon, 'Go to terminal', goToTerminal],
      resume: ['▶', 'Resume', resume],
      handoff: ['↪', 'Hand off to another agent', handoff],
    }[action];
    const btn = el('button', 'ah-icon-btn ah-chip-' + action);
    btn.type = 'button';
    btn.dataset.action = action;
    if (typeof spec[0] === 'function') btn.appendChild(spec[0]());
    else btn.textContent = spec[0];
    btn.title = spec[1];
    btn.setAttribute('aria-label', spec[1]);
    if (action === 'go' && rowViewing(row)) {
      btn.disabled = true;
      btn.title = 'Already open';
      btn.setAttribute('aria-label', 'Go to terminal (already open)');
    }
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      spec[2](row);
    });
    return btn;
  }

  // A row is a card: agent tile, title with a state pill, meta line, and (after a failed
  // resume) an amber note. Its action chips sit over the right end, shown on hover or focus.
  function buildRow(row, now) {
    const item = el('div', 'ah-item ah-state-' + row.state);
    item.dataset.key = row.key;
    item.setAttribute('role', 'listitem');
    const head = el('div', 'ah-row');
    head.tabIndex = 0;
    const pill = statePill(row);
    const text = metaLine(row, now, agentName);
    const primary = primaryAction(row, rowViewing(row));
    head.setAttribute('role', 'button');
    head.setAttribute(
      'aria-label',
      [row.title, pill && pill.textContent, text, rowActive(row) ? 'current terminal' : '']
        .filter(Boolean)
        .join(', '),
    );
    if (primary) head.classList.add('ah-row-clickable');
    if (rowActive(row)) {
      item.classList.add('ah-active');
      head.setAttribute('aria-current', 'true');
    }
    const lead = el('span', 'ah-lead');
    if (typeof _genAgentTabIcon === 'function') lead.appendChild(_genAgentTabIcon(row.agent));
    if (row.state === 'needs_you' || row.state === 'working') {
      const dot = el('span', 'ah-dot ah-dot-' + row.state);
      dot.setAttribute('aria-hidden', 'true');
      lead.appendChild(dot);
    }
    const main = el('span', 'ah-main');
    const top = el('span', 'ah-top');
    top.appendChild(el('span', 'ah-title', row.title));
    if (pill) top.appendChild(pill);
    main.appendChild(top);
    // The time is the last part of the meta line; keep it whole and let the branch truncate.
    const cut = text.lastIndexOf(' · ');
    const meta = el('span', 'ah-meta');
    meta.appendChild(el('span', 'ah-meta-lead', text.slice(0, cut)));
    meta.appendChild(el('span', 'ah-meta-when', text.slice(cut)));
    main.appendChild(meta);
    if (ui.notice[row.key]) main.appendChild(el('span', 'ah-row-note', ui.notice[row.key]));
    head.appendChild(lead);
    head.appendChild(main);
    item.appendChild(head);
    const bar = el('div', 'ah-actions');
    rowActions(row).forEach((a) => bar.appendChild(actionButton(row, a)));
    item.appendChild(bar);
    return item;
  }

  function emptyText(rows, groups) {
    const { project } = context();
    if (!project) return 'Open a project to see its sessions.';
    if (!ui.loaded) return 'Loading sessions…';
    if (groups.length) return '';
    if (ui.query.trim()) return 'No sessions match “' + ui.query.trim() + '”.';
    if (ui.error && !rows.length) return '';
    return 'No agent sessions in this project yet.';
  }

  // render() rebuilds the list, which drops focus; remember the row or button that had it.
  function focusedTarget(list) {
    const a = document.activeElement;
    const item = a && list.contains(a) ? a.closest('.ah-item') : null;
    if (!item) return null;
    const at = Array.from(item.querySelectorAll('button')).indexOf(a);
    return { key: item.dataset.key, button: at };
  }

  function restoreFocus(list, target) {
    if (!target) return;
    const item = Array.from(list.querySelectorAll('.ah-item')).find(
      (i) => i.dataset.key === target.key,
    );
    if (!item) return;
    const next =
      target.button >= 0
        ? item.querySelectorAll('button')[target.button]
        : item.querySelector('.ah-row');
    if (next && !next.disabled) {
      // Rebuilt chips are hidden until :focus-within applies, and a hidden button cannot
      // take focus, so reveal them for the focus call.
      item.classList.add('ah-restoring');
      next.focus();
      item.classList.remove('ah-restoring');
    } else {
      const row = item.querySelector('.ah-row');
      if (row) row.focus();
    }
  }

  function render() {
    const list = document.getElementById('ca-hist-list');
    if (!list) return;
    const now = Date.now();
    const live = liveSessions();
    const rows = buildRows(ui.sessions, live, now, agentName);
    if (
      syncTabLabels(rows, live) &&
      typeof _genAgentEditing !== 'undefined' &&
      !_genAgentEditing &&
      typeof _genAgentRenderTabs === 'function'
    ) {
      _genAgentRenderTabs(context().tabId);
    }
    const groups = filterGroups(rows, ui.query);
    ui.rows = new Map(rows.map((r) => [r.key, r]));
    const sig = JSON.stringify([
      ui.error,
      ui.loaded,
      ui.wslPending && ui.wslPolls < WSL_POLL_MAX,
      ui.query,
      context().project && context().project.name,
      groups.map((g) => [
        g.key,
        g.rows.map((r) => [
          r.key,
          r.state,
          r.title,
          r.ptySessionId,
          metaLine(r, now, agentName),
          rowViewing(r),
          rowActive(r),
          ui.notice[r.key] || '',
        ]),
      ]),
    ]);
    if (sig === ui.sig && list.childNodes.length) return;
    ui.sig = sig;
    const top = list.scrollTop;
    const focused = focusedTarget(list);
    fly.rendering = true;
    list.textContent = '';
    groups.forEach((g) => {
      const section = el('div', 'ah-group ah-group-' + g.key);
      const label = el('div', 'ah-group-label');
      label.id = 'ah-group-label-' + g.key;
      section.setAttribute('role', 'list');
      section.setAttribute('aria-labelledby', label.id);
      label.appendChild(el('span', 'ah-group-name', g.title));
      label.appendChild(el('span', 'ah-group-count', String(g.rows.length)));
      section.appendChild(label);
      g.rows.forEach((r) => section.appendChild(buildRow(r, now)));
      list.appendChild(section);
    });
    const message = emptyText(rows, groups);
    if (message) list.appendChild(el('div', 'ah-empty', message));
    if (ui.error) {
      const box = el('div', 'ah-empty', 'Could not load sessions. ');
      const retry = el('button', 'ah-btn', 'Retry');
      retry.type = 'button';
      retry.addEventListener('click', () => refresh());
      box.appendChild(retry);
      list.appendChild(box);
    }
    if (ui.wslPending && ui.wslPolls < WSL_POLL_MAX)
      list.appendChild(el('div', 'ah-foot', 'Checking WSL…'));
    list.scrollTop = top;
    fly.scrollTop = list.scrollTop;
    restoreFocus(list, focused);
    fly.rendering = false;
    syncFlyout();
  }

  function bindSearch() {
    const input = document.getElementById('ca-hist-search');
    if (!input || input.dataset.bound) return;
    input.dataset.bound = '1';
    if (input.parentElement) input.parentElement.insertBefore(searchIcon(), input);
    input.value = ui.query;
    input.addEventListener('input', () => {
      ui.query = input.value;
      render();
    });
  }

  function show() {
    bindSearch();
    bindList();
    ui.notice = {};
    ui.wslPolls = 0;
    render();
    load();
  }

  function refresh() {
    ui.notice = {};
    ui.wslPolls = 0;
    load();
  }

  function tick() {
    updateDot();
    updateTabDots();
    if (!panelVisible()) {
      hideFlyout();
      return;
    }
    const { project } = context();
    if (!project || ui.project !== project.name || Date.now() - ui.fetchedAt > FETCH_MS) load();
    else render();
  }

  if (typeof document !== 'undefined') setInterval(tick, TICK_MS);

  const api = {
    WORKING_MS,
    dayGroup,
    relTime,
    liveState,
    needsYou,
    buildRows,
    elsewhereText,
    takeoverBody,
    syncTabLabels,
    shortAge,
    metaLine,
    rowActions,
    primaryAction,
    isActiveTerminal,
    syncActive,
    filterGroups,
    flyoutPlacement,
    show,
    refresh,
    updateDot,
    applyTabState,
    isViewing,
    liveSessions,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.agentHistory = api;
})(typeof window !== 'undefined' ? window : globalThis);
