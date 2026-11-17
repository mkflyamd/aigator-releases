const assert = require('assert');
const h = require('../web/static/code-picker-helpers.js');

const P = (name, last_opened, repo_path) => ({
  name,
  last_opened,
  repo_path: repo_path || `/r/${name}`,
});

// recency order: opened projects newest first, never-opened keep saved order after them
{
  const out = h.sortProjects([P('a'), P('b', 5), P('c'), P('d', 9)]);
  assert.deepStrictEqual(
    out.map((p) => p.name),
    ['d', 'b', 'a', 'c'],
  );
}

// equal last_opened keeps saved order (stable)
{
  const out = h.sortProjects([P('a', 5), P('b', 5)]);
  assert.deepStrictEqual(
    out.map((p) => p.name),
    ['a', 'b'],
  );
}

// search matches the name, case-insensitive; empty query keeps everything
{
  const list = [P('Alpha', 1, 'C:\\work\\one'), P('beta', 2, 'C:\\work\\Gamma')];
  assert.strictEqual(h.filterProjects(list, '').length, 2);
  assert.deepStrictEqual(
    h.filterProjects(list, 'ALP').map((p) => p.name),
    ['Alpha'],
  );
  assert.strictEqual(h.filterProjects(list, 'zzz').length, 0);
}

// a folder shared by many projects must not make every name search match;
// the path is searched only when the query contains a path separator
{
  const list = [
    P('alpha', 1, 'C:\\AppData\\repos\\alpha'),
    P('gamma', 2, 'C:\\AppData\\repos\\gamma'),
  ];
  assert.deepStrictEqual(
    h.filterProjects(list, 'ta').map((p) => p.name),
    [],
  );
  assert.deepStrictEqual(
    h.filterProjects(list, 'repos\\ga').map((p) => p.name),
    ['gamma'],
  );
  assert.deepStrictEqual(
    h.filterProjects(list, 'repos/ga').map((p) => p.name),
    ['gamma'],
  );
}

// moveTab: forward, back, before/after, no-ops
{
  const order = ['a', 'b', 'c', 'd'];
  assert.deepStrictEqual(h.moveTab(order, 'a', 'c', 'after'), ['b', 'c', 'a', 'd']);
  assert.deepStrictEqual(h.moveTab(order, 'a', 'c', 'before'), ['b', 'a', 'c', 'd']);
  assert.deepStrictEqual(h.moveTab(order, 'd', 'a', 'before'), ['d', 'a', 'b', 'c']);
  assert.deepStrictEqual(h.moveTab(order, 'c', 'b', 'after'), ['a', 'b', 'c', 'd']);
  assert.deepStrictEqual(h.moveTab(order, 'b', 'b', 'after'), order, 'onto self');
  assert.deepStrictEqual(h.moveTab(order, 'x', 'a', 'before'), order, 'unknown from');
  assert.deepStrictEqual(h.moveTab(order, 'a', 'x', 'before'), order, 'unknown to');
  assert.deepStrictEqual(order, ['a', 'b', 'c', 'd'], 'input is not mutated');
}

// stepTab: one position left/right, clamped at the ends
{
  const order = ['a', 'b', 'c'];
  assert.deepStrictEqual(h.stepTab(order, 'b', -1), ['b', 'a', 'c']);
  assert.deepStrictEqual(h.stepTab(order, 'b', 1), ['a', 'c', 'b']);
  assert.deepStrictEqual(h.stepTab(order, 'a', -1), order);
  assert.deepStrictEqual(h.stepTab(order, 'c', 1), order);
}

// resolveActiveProject: keep a project that still exists, else follow the server's pointer
{
  const list = [P('a'), P('b')];
  assert.strictEqual(h.resolveActiveProject(list, 'a', 'b'), 'a');
  assert.strictEqual(h.resolveActiveProject(list, 'gone', 'b'), 'b');
  assert.strictEqual(h.resolveActiveProject(list, 'gone', 'also-gone'), null);
  assert.strictEqual(h.resolveActiveProject(list, 'gone', null), null);
  assert.strictEqual(h.resolveActiveProject(list, null, 'b'), null);
  assert.strictEqual(h.resolveActiveProject([], 'a', 'a'), null);
}

console.log('code_picker_helpers ok');
