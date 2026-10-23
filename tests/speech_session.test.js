const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'speech.js'), 'utf8');

function makeHarness() {
  const listeners = { document: {}, window: {} };
  let now = 0;
  let nextId = 1;
  const timers = new Map();
  const notices = [];
  const stops = [];
  let onUtterance = null;
  const doc = {
    readyState: 'complete',
    hidden: false,
    focused: true,
    activeElement: null,
    getElementById: () => null,
    hasFocus() {
      return this.focused;
    },
    addEventListener(type, fn) {
      (listeners.document[type] = listeners.document[type] || []).push(fn);
    },
  };
  const win = {
    GatorSpeechCapture: {
      isSupported: () => true,
      start(cb) {
        onUtterance = cb;
        return Promise.resolve({ stop: (flush) => stops.push(flush) });
      },
    },
    _showConnectivityToast: (msg) => notices.push(msg),
    addEventListener(type, fn) {
      (listeners.window[type] = listeners.window[type] || []).push(fn);
    },
  };
  const ctx = {
    window: win,
    document: doc,
    console,
    setTimeout(fn, ms) {
      const id = nextId++;
      timers.set(id, { at: now + (ms || 0), fn });
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    fetch: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ text: '' }) }),
  };
  vm.createContext(ctx);
  vm.runInContext(source, ctx);

  const classes = new Set();
  const button = {
    style: {},
    classList: {
      toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
    },
    setAttribute() {},
    addEventListener() {},
  };
  const control = win.GatorSpeech.wire(button, () => {});

  return {
    control,
    stops,
    notices,
    classes,
    doc,
    emitUtterance: () => onUtterance(new Int16Array(16000)),
    fire(target, type) {
      (listeners[target][type] || []).forEach((fn) => fn({}));
    },
    advance(ms) {
      now += ms;
      for (const [id, t] of [...timers]) {
        if (t.at <= now) {
          timers.delete(id);
          t.fn();
        }
      }
    },
    async settle() {
      for (let i = 0; i < 5; i++) await Promise.resolve();
    },
  };
}

test('stops after 30 s without speech and says so', async () => {
  const h = makeHarness();
  h.control.start();
  await h.settle();
  h.advance(29900);
  assert.strictEqual(h.control.isListening(), true);
  h.advance(200);
  assert.strictEqual(h.control.isListening(), false);
  assert.deepStrictEqual(h.stops, [true]);
  assert.strictEqual(h.notices.length, 1);
  assert.match(h.notices[0], /30 seconds without speech/);
  assert.strictEqual(h.classes.has('listening'), false);
});

test('a spoken phrase restarts the idle clock', async () => {
  const h = makeHarness();
  h.control.start();
  await h.settle();
  h.advance(20000);
  h.emitUtterance();
  h.advance(29000);
  assert.strictEqual(h.control.isListening(), true);
  h.advance(2000);
  assert.strictEqual(h.control.isListening(), false);
});

test('stopping by hand cancels the idle timer', async () => {
  const h = makeHarness();
  h.control.start();
  await h.settle();
  h.control.stop();
  h.advance(60000);
  assert.deepStrictEqual(h.stops, [true]);
  assert.strictEqual(h.notices.length, 0);
});

test('window blur with the document unfocused stops dictation', async () => {
  const h = makeHarness();
  h.control.start();
  await h.settle();
  h.doc.focused = false;
  h.fire('window', 'blur');
  h.advance(1);
  assert.strictEqual(h.control.isListening(), false);
  assert.match(h.notices[0], /lost focus/);
});

test('window blur caused by focus moving into an iframe keeps dictating', async () => {
  const h = makeHarness();
  h.control.start();
  await h.settle();
  h.doc.focused = true;
  h.fire('window', 'blur');
  h.advance(1);
  assert.strictEqual(h.control.isListening(), true);
});

test('hiding the window stops dictation', async () => {
  const h = makeHarness();
  h.control.start();
  await h.settle();
  h.doc.hidden = true;
  h.fire('document', 'visibilitychange');
  assert.strictEqual(h.control.isListening(), false);
});

test('focus loss with nothing listening shows no notice', () => {
  const h = makeHarness();
  h.doc.focused = false;
  h.fire('window', 'blur');
  h.advance(1);
  assert.strictEqual(h.notices.length, 0);
});
