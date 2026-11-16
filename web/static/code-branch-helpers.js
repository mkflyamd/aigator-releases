// Pure helpers for the Code branch/worktree popover and terminal worktree badge.
(function (root) {
  'use strict';

  function norm(p) {
    return (p || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
  }

  function sameFolder(a, b) {
    return !!a && !!b && norm(a) === norm(b);
  }

  function isWorktreeFolder(cwd, mainPath) {
    return !!cwd && !!mainPath && !sameFolder(cwd, mainPath);
  }

  function folderKey(project, worktree) {
    return worktree ? project + '|' + norm(worktree) : project;
  }

  function tabTooltip(label, branch, inWorktree) {
    if (!branch) return label;
    return label + ' - ' + (inWorktree ? 'worktree on ' : '') + branch;
  }

  function validNewName(name) {
    return (
      /^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(name) &&
      !name.includes('..') &&
      !name.endsWith('/') &&
      !name.endsWith('.') &&
      !name.endsWith('.lock')
    );
  }

  function buildBranchMenu({ branches, worktrees, selected, query }) {
    const q = (query || '').trim();
    const match = (s) => !q || s.toLowerCase().includes(q.toLowerCase());
    const main = (worktrees.find((w) => w.is_main) || {}).path || '';
    const target = selected || main;
    const locals = (branches && branches.local) || [];

    const wtItems = worktrees
      .map((w) => ({
        kind: 'worktree',
        path: w.path,
        label: w.branch || 'detached ' + w.head,
        isMain: !!w.is_main,
        selected: sameFolder(w.path, target),
        removable: !w.is_main,
      }))
      .filter((r) => match(r.label));
    const localItems = locals
      .map((b) => ({
        kind: 'branch',
        name: b.name,
        current: !!b.current,
        inWorktree: !!b.worktree,
        deletable: !b.current && !b.worktree && b.name !== branches.default,
      }))
      .filter((r) => match(r.name));
    const localNames = new Set(locals.map((b) => b.name));
    const remoteItems = ((branches && branches.remote) || [])
      .filter((r) => !localNames.has(r.split('/').slice(1).join('/')))
      .map((name) => ({ kind: 'remote', name }))
      .filter((r) => match(r.name));

    const out = [];
    if (wtItems.length) out.push({ title: 'Worktrees', items: wtItems });
    if (localItems.length) out.push({ title: 'Local branches', items: localItems });
    if (remoteItems.length) out.push({ title: 'Remote branches', items: remoteItems });
    const taken = locals.some((b) => b.name.toLowerCase() === q.toLowerCase());
    if (q && !taken && validNewName(q))
      out.push({ title: 'Create', items: [{ kind: 'create', name: q }] });
    return out;
  }

  const api = { sameFolder, isWorktreeFolder, folderKey, tabTooltip, buildBranchMenu };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.codeBranchHelpers = api;
})(typeof window !== 'undefined' ? window : globalThis);
