const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function fn(name) {
  const m = source.match(new RegExp('(?:async )?function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  if (!m) throw new Error(name + ' not found in app.js');
  return m[0];
}
function block(re) {
  const m = source.match(re);
  if (!m) throw new Error(String(re) + ' not found in app.js');
  return m[0];
}
const plain = (x) => JSON.parse(JSON.stringify(x));

// Wiring: the render seeds the frame from the parent store, tags the frame, and routes the message.
assert.ok(/data-store="\$\{_storeKey\}"/.test(source), 'the frame carries its store key');
assert.ok(/gatorWidgetStorageScript\(gatorWidgetStoreLoad\(_storeKey\)\)/.test(source), 'the frame is seeded from the parent store');
assert.ok(/case 'gator:storage':\s*gatorWidgetStoreOnMessage\(d, e\);/.test(source), 'gator:storage is routed');

// ── Parent side ──────────────────────────────────────────────────────────────
const store = {};
const frame = { dataset: { store: 'gator.widgetstore.abc.10' } };
const frameWin = { name: 'widget' };
const ctx = {
  localStorage: {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
  },
  document: { querySelectorAll: () => [Object.assign(frame, { contentWindow: frameWin })] },
};
const api = vm.runInNewContext(
  [
    block(/const GATOR_WIDGET_STORE_PREFIX = [^\n]+;/),
    block(/const GATOR_WIDGET_STORE_LIMITS = [^\n]+;/),
    fn('gatorWidgetStoreKey'),
    fn('gatorWidgetStoreLoad'),
    fn('gatorWidgetFrameForSource'),
    fn('gatorWidgetStoreOnMessage'),
    '({ gatorWidgetStoreKey, gatorWidgetStoreLoad, gatorWidgetStoreOnMessage, GATOR_WIDGET_STORE_LIMITS })',
  ].join('\n'),
  ctx
);
const KEY = frame.dataset.store;
const saved = () => plain(JSON.parse(store[KEY] || '{}'));
const send = (d, source = frameWin) => api.gatorWidgetStoreOnMessage(d, { source });

assert.strictEqual(api.gatorWidgetStoreKey('<b>x</b>'), api.gatorWidgetStoreKey('<b>x</b>'), 'the key is stable');
assert.notStrictEqual(api.gatorWidgetStoreKey('<b>x</b>'), api.gatorWidgetStoreKey('<b>y</b>'), 'different widgets do not share a store');
assert.ok(api.gatorWidgetStoreKey('a').startsWith('gator.widgetstore.'));

send({ op: 'set', key: 'count', value: '3' });
assert.deepStrictEqual(saved(), { count: '3' });
send({ op: 'set', key: 'other', value: 'x' });
send({ op: 'remove', key: 'other' });
assert.deepStrictEqual(saved(), { count: '3' });
assert.strictEqual(api.gatorWidgetStoreLoad(KEY).count, '3');

// Only a widget frame is served, and only to its own store.
send({ op: 'set', key: 'evil', value: '1' }, { name: 'other' });
send({ op: 'set', key: 'evil', value: '1' }, null);
assert.deepStrictEqual(saved(), { count: '3' });
frame.dataset.store = 'app.settings';
send({ op: 'set', key: 'evil', value: '1' });
assert.ok(!('app.settings' in store), 'a frame cannot be pointed at a store outside the widget prefix');
frame.dataset.store = KEY;

// Bad input is refused.
for (const d of [
  { op: 'set', key: 5, value: '1' },
  { op: 'set', key: 'k', value: 5 },
  { op: 'set', key: 'k'.repeat(201), value: '1' },
  { op: 'set', key: 'k', value: 'v'.repeat(50001) },
  { op: 'remove', key: {} },
  { op: 'nope', key: 'k', value: '1' },
  {},
]) send(d);
assert.deepStrictEqual(saved(), { count: '3' });

// Limits: key count and total size.
for (let i = 0; i < 120; i++) send({ op: 'set', key: 'k' + i, value: '1' });
assert.ok(Object.keys(saved()).length <= api.GATOR_WIDGET_STORE_LIMITS.keys);
send({ op: 'clear' });
assert.deepStrictEqual(saved(), {});
for (let i = 0; i < 20; i++) send({ op: 'set', key: 'big' + i, value: 'v'.repeat(40000) });
assert.ok(Object.values(saved()).reduce((n, v) => n + v.length, 0) <= api.GATOR_WIDGET_STORE_LIMITS.total);
send({ op: 'clear' });

// A prototype-ish key is stored as data, not as a prototype change.
send({ op: 'set', key: '__proto__', value: 'p' });
assert.strictEqual(({}).p, undefined);
send({ op: 'clear' });

// ── Frame side ───────────────────────────────────────────────────────────────
const gen = vm.runInNewContext(
  [block(/const GATOR_WIDGET_STORE_PREFIX = [^\n]+;/), fn('gatorWidgetStorageScript'), '({ gatorWidgetStorageScript })'].join('\n'),
  {}
).gatorWidgetStorageScript;

function frameEnv(seedObj) {
  const posted = [];
  const win = {
    parent: { postMessage: (m, o) => posted.push(plain({ m, o })) },
  };
  win.window = win;
  // An opaque-origin frame throws on first access to the real storage.
  for (const n of ['localStorage', 'sessionStorage']) {
    Object.defineProperty(win, n, { configurable: true, get() { throw new Error('SecurityError'); } });
  }
  vm.createContext(win);
  vm.runInContext(gen(seedObj), win);
  return { win, posted };
}

{
  const { win, posted } = frameEnv({ count: '7' });
  const ls = win.localStorage;
  assert.strictEqual(ls.getItem('count'), '7', 'seeded from the parent store');
  assert.strictEqual(ls.getItem('nope'), null);
  ls.setItem('count', 8);
  assert.strictEqual(ls.getItem('count'), '8', 'values are strings');
  assert.deepStrictEqual(posted, [{ m: { type: 'gator:storage', op: 'set', key: 'count', value: '8' }, o: '*' }]);
  ls.removeItem('count');
  assert.strictEqual(ls.getItem('count'), null);
  assert.strictEqual(posted[1].m.op, 'remove');
  ls.setItem('a', '1'); ls.setItem('b', '2');
  assert.strictEqual(ls.length, 2);
  assert.strictEqual(ls.key(0), 'a');
  assert.strictEqual(ls.key(5), null);
  ls.c = 3;
  assert.strictEqual(ls.c, '3', 'property access works like Storage');
  assert.strictEqual(ls.getItem('c'), '3');
  assert.deepStrictEqual(Object.keys(ls), ['a', 'b', 'c']);
  delete ls.c;
  assert.strictEqual(ls.getItem('c'), null);
  ls.clear();
  assert.strictEqual(ls.length, 0);
  assert.strictEqual(posted[posted.length - 1].m.op, 'clear');

  // sessionStorage works but stays inside the frame.
  const n = posted.length;
  win.sessionStorage.setItem('s', '1');
  assert.strictEqual(win.sessionStorage.getItem('s'), '1');
  assert.strictEqual(posted.length, n, 'sessionStorage is not persisted');
  assert.strictEqual(win.sessionStorage.getItem('count'), null, 'sessionStorage is not seeded');
}

// A stale copy of the script (saved widgets keep the injected script) does not replace the live store.
{
  const { win } = frameEnv({ a: '1' });
  win.localStorage.setItem('a', '2');
  vm.runInContext(gen({ a: 'stale' }), win);
  assert.strictEqual(win.localStorage.getItem('a'), '2');
}

// Seed data cannot close the script element.
assert.ok(!gen({ x: '</script><script>alert(1)</script>' }).includes('</script>'));
{
  const { win } = frameEnv({ x: '</script>"\'\\\n ' });
  assert.strictEqual(win.localStorage.getItem('x'), '</script>"\'\\\n ');
}

console.log('widget_storage: PASS');
