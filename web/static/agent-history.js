// Agent session history: pure helpers (grouping, live state, search), exported
// for node tests, followed by the browser-only History panel controller.
(function (root) {
  'use strict';

  const WORKING_MS = 3000;
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
        title: s.title,
        branch: s.branch || '',
        source: s.source,
        lastActive,
        state,
        group: groupOf(state, lastActive, nowMs),
        ptySessionId: term ? term.ptySessionId : null,
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
        title: 'New ' + label(term.agent) + ' session',
        branch: '',
        source: 'windows',
        lastActive,
        state,
        group: groupOf(state, lastActive, nowMs),
        ptySessionId: pty,
      });
    });
    return rows;
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

  function rowActions(row) {
    return row.ptySessionId ? ['go'] : ['resume', 'handoff'];
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

  // ── Browser panel ────────────────────────────────────────────────────────
  const FETCH_MS = 15000;
  const TICK_MS = 2000;
  const WSL_POLL_MS = 2000;
  const WSL_POLL_MAX = 5;

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
    openKey: null,
    previews: {},
    notice: {},
    sig: '',
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
      ui.project = null;
      ui.sessions = [];
      ui.loaded = true;
      render();
      return;
    }
    if (ui.busy) return;
    if (ui.project !== project.name) {
      ui.project = project.name;
      ui.sessions = [];
      ui.loaded = false;
      ui.openKey = null;
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

  async function resume(row) {
    const { tabId, project } = context();
    if (!project || typeof _genAgentStart !== 'function') return;
    if (typeof _genAgentStartInFlight === 'function' && _genAgentStartInFlight(tabId)) return;
    const before = terminalState(tabId);
    const count = before ? before.order.length : 0;
    closeFileView();
    await _genAgentStart(tabId, row.agent, project.name, project.repo_path, {
      forceNew: true,
      resumeId: row.id,
      keepStateAgent: !!(before && before.agent),
    });
    const after = terminalState(tabId);
    if (after && after.order.length > count) {
      delete ui.notice[row.key];
      load();
      return;
    }
    ui.notice[row.key] = 'Could not resume this session. It may have been deleted.';
    render();
    load();
  }

  function handoff(row) {
    const { tabId, project } = context();
    if (!project || !window.agentHandoff) return;
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
      render();
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
    ui.previews[row.key] = result;
    render();
  }

  function toggleOpen(row) {
    if (ui.openKey === row.key) {
      ui.openKey = null;
      render();
      return;
    }
    ui.openKey = row.key;
    delete ui.notice[row.key];
    render();
    if (row.id) loadPreview(row);
  }

  function actionButton(row, action) {
    const spec = {
      go: ['Go to terminal', true, goToTerminal],
      resume: ['Resume', true, resume],
      handoff: ['Continue in another agent…', false, handoff],
    }[action];
    const btn = el('button', 'ah-btn' + (spec[1] ? ' ah-btn-primary' : ''), spec[0]);
    btn.type = 'button';
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      spec[2](row);
    });
    return btn;
  }

  function buildDetail(row) {
    const box = el('div', 'ah-detail');
    if (row.id) {
      const pv = ui.previews[row.key];
      const body = el('div', 'ah-preview');
      if (!pv || pv.status === 'loading') {
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
      box.appendChild(body);
    }
    if (ui.notice[row.key]) box.appendChild(el('div', 'ah-note ah-note-warn', ui.notice[row.key]));
    const bar = el('div', 'ah-actions');
    rowActions(row).forEach((a) => bar.appendChild(actionButton(row, a)));
    box.appendChild(bar);
    return box;
  }

  function buildRow(row, now) {
    const open = ui.openKey === row.key;
    const item = el('div', 'ah-item' + (open ? ' open' : ''));
    item.dataset.key = row.key;
    item.setAttribute('role', 'listitem');
    const head = el('div', 'ah-row ah-state-' + row.state);
    head.tabIndex = 0;
    head.setAttribute('role', 'button');
    head.setAttribute('aria-expanded', open ? 'true' : 'false');
    head.title = row.title;
    const lead = el('span', 'ah-lead');
    if (row.state === 'needs_you' || row.state === 'working') {
      const dot = el('span', 'ah-dot ah-dot-' + row.state);
      dot.setAttribute('role', 'img');
      dot.setAttribute('aria-label', row.state === 'needs_you' ? 'Needs you' : 'Working');
      lead.appendChild(dot);
    } else if (typeof _genAgentTabIcon === 'function') {
      lead.appendChild(_genAgentTabIcon(row.agent));
    }
    const main = el('span', 'ah-main');
    main.appendChild(el('span', 'ah-title', row.title));
    main.appendChild(el('span', 'ah-meta', metaLine(row, now, agentName)));
    head.appendChild(lead);
    head.appendChild(main);
    head.addEventListener('click', () => toggleOpen(row));
    head.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggleOpen(row);
      }
    });
    item.appendChild(head);
    if (open) item.appendChild(buildDetail(row));
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
    if (next) next.focus();
  }

  function render() {
    const list = document.getElementById('ca-hist-list');
    if (!list) return;
    const now = Date.now();
    const rows = buildRows(ui.sessions, liveSessions(), now, agentName);
    const groups = filterGroups(rows, ui.query);
    const sig = JSON.stringify([
      ui.error,
      ui.loaded,
      ui.wslPending && ui.wslPolls < WSL_POLL_MAX,
      ui.query,
      ui.openKey,
      ui.openKey && ui.previews[ui.openKey],
      ui.openKey && ui.notice[ui.openKey],
      context().project && context().project.name,
      groups.map((g) => [
        g.key,
        g.rows.map((r) => [r.key, r.state, r.title, r.ptySessionId, metaLine(r, now, agentName)]),
      ]),
    ]);
    if (sig === ui.sig && list.childNodes.length) return;
    ui.sig = sig;
    const top = list.scrollTop;
    const focused = focusedTarget(list);
    list.textContent = '';
    groups.forEach((g) => {
      const section = el('div', 'ah-group ah-group-' + g.key);
      section.appendChild(el('div', 'ah-group-label', g.title));
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
    restoreFocus(list, focused);
  }

  function bindSearch() {
    const input = document.getElementById('ca-hist-search');
    if (!input || input.dataset.bound) return;
    input.dataset.bound = '1';
    input.value = ui.query;
    input.addEventListener('input', () => {
      ui.query = input.value;
      render();
    });
  }

  function show() {
    bindSearch();
    ui.wslPolls = 0;
    render();
    load();
  }

  function refresh() {
    ui.wslPolls = 0;
    load();
  }

  function tick() {
    updateDot();
    if (!panelVisible()) return;
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
    shortAge,
    metaLine,
    rowActions,
    filterGroups,
    show,
    refresh,
    updateDot,
    isViewing,
    liveSessions,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.agentHistory = api;
})(typeof window !== 'undefined' ? window : globalThis);
