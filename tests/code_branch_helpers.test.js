const assert = require('assert');
const h = require('../web/static/code-branch-helpers.js');

const worktrees = [
  { path: 'C:\\r\\proj', branch: 'main', head: 'abc1234', is_main: true },
  { path: 'C:\\r\\proj-worktrees\\feat', branch: 'feat', head: 'def5678', is_main: false },
  { path: 'C:\\r\\proj-worktrees\\det', branch: null, head: '9999999', is_main: false },
];
const branches = {
  current: 'main',
  default: 'main',
  local: [
    { name: 'feat', current: false, worktree: 'C:\\r\\proj-worktrees\\feat' },
    { name: 'main', current: true, worktree: 'C:\\r\\proj' },
    { name: 'old', current: false, worktree: null },
  ],
  remote: ['origin/main', 'origin/old', 'origin/topic'],
};

// folders compare regardless of slash style, case and trailing slash
assert.strictEqual(h.sameFolder('C:\\R\\Proj\\', 'c:/r/proj'), true);
assert.strictEqual(h.sameFolder('C:\\r\\proj', 'C:\\r\\proj2'), false);
assert.strictEqual(h.sameFolder('', 'C:\\r\\proj'), false);

// a terminal is "in a worktree" only when its folder differs from the main one
assert.strictEqual(h.isWorktreeFolder('C:\\r\\proj-worktrees\\feat', 'C:\\r\\proj'), true);
assert.strictEqual(h.isWorktreeFolder('c:/r/proj', 'C:\\r\\proj'), false);
assert.strictEqual(h.isWorktreeFolder('', 'C:\\r\\proj'), false);

// cache key is project plus folder
assert.strictEqual(h.folderKey('demo', ''), 'demo');
assert.notStrictEqual(h.folderKey('demo', 'C:\\r\\x'), h.folderKey('demo', ''));

// tooltip names the branch and flags a worktree
assert.strictEqual(h.tabTooltip('Claude', 'feat', true), 'Claude - worktree on feat');
assert.strictEqual(h.tabTooltip('Claude', 'main', false), 'Claude - main');
assert.strictEqual(h.tabTooltip('Claude', '', false), 'Claude');

// menu sections, in order, with the selected worktree marked
{
  const m = h.buildBranchMenu({ branches, worktrees, selected: '', query: '' });
  assert.deepStrictEqual(
    m.map((s) => s.title),
    ['Worktrees', 'Local branches', 'Remote branches'],
  );
  const wt = m[0].items;
  assert.deepStrictEqual(
    wt.map((r) => [r.label, r.selected, r.removable]),
    [
      ['main', true, false],
      ['feat', false, true],
      ['detached 9999999', false, true],
    ],
  );
  const loc = m[1].items;
  assert.deepStrictEqual(
    loc.map((r) => [r.name, r.current, r.deletable, r.inWorktree]),
    [
      ['feat', false, false, true],
      ['main', true, false, true],
      ['old', false, true, false],
    ],
  );
  // remote branches that already have a local twin are hidden
  assert.deepStrictEqual(
    m[2].items.map((r) => r.name),
    ['origin/topic'],
  );
}

// selecting a worktree marks it instead of main
{
  const m = h.buildBranchMenu({ branches, worktrees, selected: 'c:/r/proj-worktrees/feat', query: '' });
  assert.deepStrictEqual(
    m[0].items.map((r) => r.selected),
    [false, true, false],
  );
}

// the default branch is never deletable even when not current
{
  const b = { ...branches, current: 'feat', local: branches.local.map((x) => ({ ...x, current: x.name === 'feat' })) };
  const loc = h.buildBranchMenu({ branches: b, worktrees, selected: '', query: '' })[1].items;
  assert.strictEqual(loc.find((r) => r.name === 'main').deletable, false);
}

// query filters rows and drops empty sections; unknown valid name offers create
{
  const m = h.buildBranchMenu({ branches, worktrees, selected: '', query: 'OLD' });
  assert.deepStrictEqual(
    m.map((s) => s.title),
    ['Local branches'],
  );
  const c = h.buildBranchMenu({ branches, worktrees, selected: '', query: 'brand-new' });
  assert.deepStrictEqual(c, [{ title: 'Create', items: [{ kind: 'create', name: 'brand-new' }] }]);
  // an exact existing name does not offer create
  const e = h.buildBranchMenu({ branches, worktrees, selected: '', query: 'old' });
  assert.ok(!e.some((s) => s.title === 'Create'));
  // names git would reject are not offered
  const bad = h.buildBranchMenu({ branches, worktrees, selected: '', query: 'a b' });
  assert.ok(!bad.some((s) => s.title === 'Create'));
}

console.log('code_branch_helpers ok');
