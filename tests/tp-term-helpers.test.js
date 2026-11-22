const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const src = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'tp-term-helpers.js'),
  'utf8',
);
const ctx = vm.createContext({ setTimeout, clearTimeout, ResizeObserver: class {}, console });
vm.runInContext(src + '\nthis._ocFit = _ocFit;', ctx);

function session({ cols = 80, rows = 46, visible = true, syncScrollArea } = {}) {
  const term = {
    cols,
    rows,
    _core: { viewport: { syncScrollArea } },
    reset() {},
  };
  return {
    term,
    fitAddon: { fit() {} },
    container: { offsetParent: visible ? {} : null, clientWidth: 400 },
    ws: null,
  };
}

test('re-showing a terminal at the same size resyncs the scroll area so the bottom rows stay reachable', () => {
  const calls = [];
  ctx._ocFit(session({ syncScrollArea: (force) => calls.push(force) }));
  assert.deepStrictEqual(calls, [true]);
});

test('a hidden terminal is left alone', () => {
  const calls = [];
  ctx._ocFit(session({ visible: false, syncScrollArea: (force) => calls.push(force) }));
  assert.deepStrictEqual(calls, []);
});

test('fit still works when xterm internals are missing or throw', () => {
  const missing = session();
  delete missing.term._core;
  assert.doesNotThrow(() => ctx._ocFit(missing));
  const throwing = session({
    syncScrollArea: () => {
      throw new Error('internals changed');
    },
  });
  assert.doesNotThrow(() => ctx._ocFit(throwing));
});

test('a resize still reaches the PTY when the scroll resync throws', () => {
  const sent = [];
  const sess = session({
    syncScrollArea: () => {
      throw new Error('internals changed');
    },
  });
  sess.ws = { readyState: 1, send: (m) => sent.push(JSON.parse(m)) };
  ctx.WebSocket = { OPEN: 1 };
  sess.fitAddon = {
    fit() {
      sess.term.cols = 100;
    },
  };
  ctx._ocFit(sess);
  assert.strictEqual(sent.length, 1);
  assert.strictEqual(sent[0].type, 'resize');
});

test('the vendored xterm still builds a viewport whose syncScrollArea takes a force flag', () => {
  const xterm = fs.readFileSync(
    path.join(__dirname, '..', 'web', 'static', 'vendor', 'xterm', 'xterm.js'),
    'utf8',
  );
  assert.match(xterm, /\.viewport=this\._instantiationService\.createInstance\(\w+\.Viewport,/);
  assert.match(xterm, /syncScrollArea\(\w+=!1\)\{/);
});
