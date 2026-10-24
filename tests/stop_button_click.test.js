const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function loadPredicate() {
  const m = source.match(/function _shouldStopFromClick\([^)]*\)\s*\{[\s\S]*?\n\}/);
  assert(m, '_shouldStopFromClick found in app.js');
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(m[0], ctx);
  return ctx._shouldStopFromClick;
}

const child = {};
const other = {};
const btn = { contains: (t) => t === btn || t === child };
const rect = { left: 100, right: 140, top: 200, bottom: 240 };
const ev = (o) => Object.assign({ button: 0, target: btn, clientX: 0, clientY: 0 }, o);

test('_shouldStopFromClick decides from target, position, button and streaming state', () => {
  const f = loadPredicate();
  assert.strictEqual(f(ev({}), btn, rect, true), true, 'target is the button');
  assert.strictEqual(f(ev({ target: child }), btn, rect, true), true, 'target is a child');
  assert.strictEqual(
    f(ev({ target: other, clientX: 120, clientY: 220 }), btn, rect, true),
    true,
    'press/release moved the click to an ancestor, but the point is on the button',
  );
  assert.strictEqual(
    f(ev({ target: other, clientX: 10, clientY: 10 }), btn, rect, true),
    false,
    'outside the button',
  );
  assert.strictEqual(f(ev({}), btn, rect, false), false, 'not streaming');
  assert.strictEqual(f(ev({ button: 2 }), btn, rect, true), false, 'non-primary button');
});

test('stop is dispatched through one delegated listener, not a per-turn button listener', () => {
  assert(!source.includes("sendBtn.addEventListener('click', _onStop)"));
  assert(source.includes('_activeStops.add(_onStop)'));
  assert(source.includes('_activeStops.delete(_onStop)'));
});

test('stop pressed while /api/chat is still pending releases the UI and cancels the late task', () => {
  const post = source.indexOf("const _postPromise = fetch('/api/chat'");
  assert(post > 0, 'POST is kept as a promise so stop can race it');
  const after = source.slice(post, post + 1500);
  assert(after.includes('Promise.race([_postPromise, _stoppedDuringPost])'));
  assert(after.includes('/cancel'), 'a task that arrives after stop is cancelled');
  assert(after.includes("name: 'AbortError'"), 'the normal stopped cleanup path runs');
  const stop = source.slice(
    source.indexOf('const _onStop = () => {'),
    source.indexOf('_activeStops.add(_onStop)'),
  );
  assert(stop.includes('_abortCtrl._stopPost'), '_onStop releases the pending POST wait');
});
