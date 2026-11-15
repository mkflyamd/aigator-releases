// Agent session history: pure helpers (grouping, live state, search) and, in the
// browser, the History panel. The helpers are exported for node tests.
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
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.agentHistory = api;
})(typeof window !== 'undefined' ? window : globalThis);
