// Pure helpers for the Code project menu and terminal tab ordering.
(function (root) {
  'use strict';

  function sortProjects(projects) {
    return projects
      .map((p, i) => ({ p, i }))
      .sort((a, b) => (b.p.last_opened || 0) - (a.p.last_opened || 0) || a.i - b.i)
      .map((x) => x.p);
  }

  function filterProjects(projects, query) {
    const q = (query || '').trim().toLowerCase();
    if (!q) return projects.slice();
    const byPath = /[\\/]/.test(q);
    const norm = (s) => (s || '').toLowerCase().replace(/\\/g, '/');
    const needle = norm(q);
    return projects.filter((p) => norm(byPath ? p.repo_path : p.name).includes(needle));
  }

  function moveTab(order, fromId, toId, side) {
    if (fromId === toId || !order.includes(fromId) || !order.includes(toId)) return order.slice();
    const rest = order.filter((id) => id !== fromId);
    const at = rest.indexOf(toId) + (side === 'after' ? 1 : 0);
    rest.splice(at, 0, fromId);
    return rest;
  }

  function stepTab(order, id, delta) {
    const i = order.indexOf(id);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= order.length) return order.slice();
    const out = order.slice();
    out.splice(i, 1);
    out.splice(j, 0, id);
    return out;
  }

  const api = { sortProjects, filterProjects, moveTab, stepTab };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.codePickerHelpers = api;
})(typeof window !== 'undefined' ? window : globalThis);
