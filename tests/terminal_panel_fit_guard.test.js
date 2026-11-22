const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

// The bottom-dock terminal (terminal.js) forwarded whatever FitAddon computed to the PTY, even when
// the panel could not be measured (hidden panel -> the inline 100% size of a display:none element was
// read as 100px, i.e. ~12x6; squeezed window -> a few columns), and it never refitted when the panel
// changed size without a window resize event (the stale, taller xterm was clipped, hiding the prompt
// bar). A streaming TUI that is resized to a bogus size and back leaves its prompt misplaced until a
// keypress forces a full redraw.

const src = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'terminal.js'), 'utf8');

function makeContext() {
  const sockets = [];
  const timers = [];
  const observers = [];
  const windowListeners = {};
  const layout = { visible: true, w: 810, h: 340 };

  const makeEl = (tag) => {
    const classes = new Set();
    const el = {
      tag,
      children: [],
      style: {},
      dataset: {},
      parentNode: null,
      className: '',
      classList: {
        add: (...c) => c.forEach((x) => classes.add(x)),
        remove: (...c) => c.forEach((x) => classes.delete(x)),
        toggle: (c, on) =>
          (on === undefined ? !classes.has(c) : on) ? classes.add(c) : classes.delete(c),
        contains: (c) => classes.has(c),
      },
      appendChild(c) {
        c.parentNode = el;
        el.children.push(c);
        return c;
      },
      removeChild() {},
      addEventListener() {},
      querySelector: () => ({ textContent: '' }),
      getBoundingClientRect: () => ({ width: layout.w, height: layout.h }),
      scrollIntoView() {},
      focus() {},
      get offsetParent() {
        return layout.visible ? {} : null;
      },
      get clientWidth() {
        return layout.visible ? layout.w : 0;
      },
      get clientHeight() {
        return layout.visible ? layout.h : 0;
      },
    };
    return el;
  };

  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.sent = [];
      this.readyState = 0;
      sockets.push(this);
    }
    send(data) {
      this.sent.push(JSON.parse(data));
    }
    open() {
      this.readyState = FakeWebSocket.OPEN;
      this.onopen();
    }
    drop() {
      this.readyState = 3;
      this.onclose();
    }
  }
  FakeWebSocket.OPEN = 1;

  class FakeTerminal {
    constructor() {
      this.cols = 80;
      this.rows = 24;
      this.options = {};
    }
    loadAddon(addon) {
      addon.term = this;
    }
    open() {}
    onData() {}
    attachCustomKeyEventHandler() {}
    focus() {}
    write() {}
    dispose() {}
  }
  // Mirrors the real addon: a display:none parent reports its inline "100%" size, which parseInt
  // turns into 100px, so fit() "succeeds" with a tiny bogus grid instead of throwing.
  class FakeFitAddon {
    fit() {
      this.term.cols = layout.visible ? Math.floor(layout.w / 9) : 12;
      this.term.rows = layout.visible ? Math.floor(layout.h / 17) : 6;
    }
  }

  const body = makeEl('body');
  const win = {
    innerHeight: 900,
    innerWidth: 1200,
    addEventListener: (type, fn) => (windowListeners[type] = windowListeners[type] || []).push(fn),
  };
  const ctx = {
    window: win,
    WebSocket: FakeWebSocket,
    Terminal: FakeTerminal,
    FitAddon: { FitAddon: FakeFitAddon },
    ResizeObserver: class {
      constructor(cb) {
        this.cb = cb;
      }
      observe(el) {
        observers.push({ cb: this.cb, el });
      }
    },
    MutationObserver: class {
      observe() {}
    },
    localStorage: { getItem: () => null, setItem() {} },
    location: { protocol: 'http:', host: 'localhost' },
    document: {
      createElement: makeEl,
      body,
      documentElement: {
        style: { setProperty() {}, removeProperty() {} },
        getAttribute: () => 'dark',
      },
      getElementById: () => null,
      querySelector: () => null,
      addEventListener() {},
    },
    setTimeout: (cb) => timers.push(cb),
    clearTimeout: (id) => {
      if (id && timers[id - 1]) timers[id - 1] = null;
    },
    console,
  };
  vm.createContext(ctx);
  vm.runInContext(src, ctx, { filename: 'terminal.js' });

  const runTimers = () => {
    while (timers.length) {
      const cb = timers.shift();
      if (cb) cb();
    }
  };
  const fireWindowResize = () => (windowListeners.resize || []).forEach((fn) => fn());
  const fireObservers = () => observers.forEach((o) => o.cb([]));
  return { ctx, win, sockets, layout, runTimers, fireWindowResize, fireObservers, observers };
}

const resizes = (ws) => ws.sent.filter((m) => m.type === 'resize');
const last = (arr) => arr[arr.length - 1];

function openTerminal() {
  const t = makeContext();
  t.win.GatorTerminal.open();
  t.runTimers();
  t.sockets[0].open();
  t.runTimers();
  return t;
}

// 1. Baseline: a visible panel syncs its real grid to the PTY.
{
  const t = openTerminal();
  assert.deepStrictEqual(last(resizes(t.sockets[0])), { type: 'resize', cols: 90, rows: 20 });
}

// 2. A closed (display:none) panel must not shrink the xterm or the PTY on a window resize.
{
  const t = openTerminal();
  const before = resizes(t.sockets[0]).length;
  t.layout.visible = false;
  t.win.GatorTerminal.close();
  t.fireWindowResize();
  t.fireObservers();
  t.runTimers();
  assert.strictEqual(
    resizes(t.sockets[0]).length,
    before,
    'no resize may be sent while the panel is hidden',
  );
}

// 3. A squeezed panel (a few columns wide) must not be pushed to the PTY.
{
  const t = openTerminal();
  const before = resizes(t.sockets[0]).length;
  t.layout.w = 6;
  t.fireWindowResize();
  t.fireObservers();
  t.runTimers();
  assert.strictEqual(
    resizes(t.sockets[0]).length,
    before,
    'no resize may be sent while the panel is squeezed',
  );
}

// 4. The panel changing size with no window resize event (reparent, banner, dock) must refit.
{
  const t = openTerminal();
  t.layout.h = 170;
  t.fireObservers();
  t.runTimers();
  assert.deepStrictEqual(
    last(resizes(t.sockets[0])),
    { type: 'resize', cols: 90, rows: 10 },
    'a container size change must refit xterm and resync the PTY',
  );
}

// 5. Repeated observer ticks at the same size must not make the TUI redraw again.
{
  const t = openTerminal();
  t.layout.h = 170;
  t.fireObservers();
  t.runTimers();
  const n = resizes(t.sockets[0]).length;
  t.fireObservers();
  t.runTimers();
  assert.strictEqual(resizes(t.sockets[0]).length, n, 'unchanged size must not be re-sent');
}

// 6. A reconnect that happens while the panel is hidden still syncs the new PTY once it is visible,
//    even though the grid is the same as before the drop.
{
  const t = openTerminal();
  t.layout.visible = false;
  t.sockets[0].drop();
  t.runTimers();
  const ws2 = t.sockets[1];
  ws2.open();
  t.runTimers();
  assert.deepStrictEqual(resizes(ws2), [], 'nothing measurable yet, so nothing is sent');
  t.layout.visible = true;
  t.fireObservers();
  t.runTimers();
  assert.deepStrictEqual(resizes(ws2), [{ type: 'resize', cols: 90, rows: 20 }]);
}

console.log('terminal_panel_fit_guard: ok');
