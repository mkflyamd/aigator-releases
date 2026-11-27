const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

// A fresh xterm is fitted before its websocket opens, so _ocFit later sees "no change" and never
// tells the PTY. The PTY then keeps whatever size it was spawned/left with (a reattached shell
// reported 20x100 under a 43x84 xterm). The websocket open handler must sync the PTY size itself.

const read = (f) => fs.readFileSync(path.join(__dirname, '..', 'web', 'static', f), 'utf8');

function makeContext() {
  const sockets = [];
  const timers = [];
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
    }
    loadAddon(addon) {
      addon.term = this;
    }
    open() {}
    onData() {}
    attachCustomKeyEventHandler() {}
    onTitleChange() {}
    focus() {}
    reset() {}
    write() {}
  }
  const laidOut = { cols: 84, rows: 43 };
  class FakeFitAddon {
    fit() {
      this.term.cols = laidOut.cols;
      this.term.rows = laidOut.rows;
    }
  }

  const makeEl = () => ({
    offsetParent: {},
    clientWidth: 800,
    style: {},
    className: '',
    classList: { add() {}, remove() {} },
    addEventListener() {},
    setAttribute() {},
    removeAttribute() {},
    remove() {},
    appendChild() {},
    querySelector: () => null,
    getClientRects: () => [{}],
  });

  const ctx = {
    WebSocket: FakeWebSocket,
    Terminal: FakeTerminal,
    FitAddon: { FitAddon: FakeFitAddon },
    ResizeObserver: class {
      observe() {}
    },
    location: { protocol: 'http:', host: 'localhost' },
    window: {},
    document: { createElement: makeEl, getElementById: () => null, addEventListener() {} },
    requestAnimationFrame: (cb) => cb(),
    setTimeout: (cb) => timers.push(cb),
    setInterval() {},
    clearTimeout: () => {},
    console,
  };
  vm.createContext(ctx);
  for (const f of ['tp-term-helpers.js', 'tp-code-agent.js', 'tp-generic-agent-terminal.js']) {
    // tp-code-agent.js only contributes _caSessionKey; its own load-time wiring is not needed.
    const src =
      f === 'tp-code-agent.js'
        ? "const SHARED_CODE_SESSION = true; function _caSessionKey(t){ return SHARED_CODE_SESSION ? '_shared' : String(t); }"
        : read(f);
    vm.runInContext(src, ctx, { filename: f });
  }
  vm.runInContext(
    '_genAgentRenderTabs = function () {}; _genAgentArmNoOutputWatchdog = function () {};',
    ctx,
  );
  return { ctx, sockets, timers, makeEl, laidOut };
}

const resizes = (ws) => ws.sent.filter((m) => m.type === 'resize');

// 1. Websocket open syncs the PTY even though xterm's own size did not change.
{
  const { ctx, sockets, makeEl } = makeContext();
  const sess = { tabId: 't', ptySessionId: 'pty-1', agent: 'terminal', container: makeEl() };
  ctx.sess = sess;
  vm.runInContext('_ocSpawnTerm(sess); _ocFit(sess); _genAgentConnect(sess);', ctx);
  assert.strictEqual(`${sess.term.rows}x${sess.term.cols}`, '43x84');
  sockets[0].open();
  assert.deepStrictEqual(
    resizes(sockets[0]),
    [{ type: 'resize', cols: 84, rows: 43 }],
    'onopen must send the current xterm size to the PTY',
  );
}

// 2. Reattaching to a live PTY id (new xterm, fitted before connect) syncs the PTY too.
{
  const { ctx, sockets, makeEl } = makeContext();
  ctx.state = { termsEl: makeEl(), sessions: {}, order: [], seq: 0 };
  vm.runInContext("_genAgentTerminals['_shared'] = state;", ctx);
  vm.runInContext("_genAgentAttachTerminal('t', 'pty-live', 'terminal');", ctx);
  assert.strictEqual(sockets.length, 1, 'attach opens one websocket');
  sockets[0].open();
  assert.deepStrictEqual(
    resizes(sockets[0]),
    [{ type: 'resize', cols: 84, rows: 43 }],
    'reattach must send the current xterm size to the PTY',
  );
}

// 3a. A container that was never laid out (hidden pane, xterm still at its 80x24 default)
// must not push a bogus size.
{
  const { ctx, sockets, makeEl } = makeContext();
  const container = makeEl();
  container.offsetParent = null;
  const sess = { tabId: 't', ptySessionId: 'pty-2', agent: 'terminal', container };
  ctx.sess = sess;
  vm.runInContext('_ocSpawnTerm(sess); _genAgentConnect(sess);', ctx);
  sockets[0].open();
  assert.deepStrictEqual(resizes(sockets[0]), [], 'no resize for a never-fitted hidden container');
}

// 3b. A reconnect while the pane is hidden still sends the last fitted size, so the TUI redraws
// (the old reconnect-only resize from e3d224e) even though _ocFit cannot measure a hidden panel.
{
  const { ctx, sockets, makeEl } = makeContext();
  const container = makeEl();
  const sess = { tabId: 't', ptySessionId: 'pty-3', agent: 'terminal', container };
  ctx.sess = sess;
  vm.runInContext('_ocSpawnTerm(sess); _ocFit(sess); _genAgentConnect(sess);', ctx);
  sockets[0].open();
  container.offsetParent = null; // pane hidden before the socket drops and reconnects
  vm.runInContext('_genAgentConnect(sess);', ctx);
  assert.strictEqual(sockets.length, 2);
  sockets[1].open();
  assert.deepStrictEqual(
    resizes(sockets[1]),
    [{ type: 'resize', cols: 84, rows: 43 }],
    'reconnect while hidden must send the current size to force a redraw',
  );
}

// 3c. Real retry path: the socket drops, the backoff timer fires, and the second socket opens
// while the pane is hidden. The PTY gets exactly one resize carrying the last fitted size.
{
  const { ctx, sockets, timers, makeEl } = makeContext();
  const container = makeEl();
  const sess = { tabId: 't', ptySessionId: 'pty-4', agent: 'terminal', container };
  ctx.sess = sess;
  vm.runInContext('_ocSpawnTerm(sess); _ocFit(sess); _genAgentConnect(sess);', ctx);
  sockets[0].open();
  container.offsetParent = null;
  sockets[0].drop();
  assert.strictEqual(timers.length, 1, 'onclose schedules exactly one reconnect');
  timers[0]();
  assert.strictEqual(sockets.length, 2);
  sockets[1].open();
  assert.deepStrictEqual(
    resizes(sockets[1]),
    [{ type: 'resize', cols: 84, rows: 43 }],
    'scheduled reconnect while hidden sends exactly one resize with the last fitted size',
  );
}

// 4. Reconnect cases. A reconnect always sends exactly one frame on the new socket, at the same
// size (the PTY behind it may hold a stale size) or at a size that changed while it was down; a
// refit at an unchanged size on an already-synced socket sends nothing more.
{
  const connectAndDrop = () => {
    const w = makeContext();
    const sess = { tabId: 't', ptySessionId: 'pty-5', agent: 'terminal', container: w.makeEl() };
    w.ctx.sess = sess;
    vm.runInContext('_ocSpawnTerm(sess); _ocFit(sess); _genAgentConnect(sess);', w.ctx);
    w.sockets[0].open();
    return { ...w, sess };
  };
  const reconnect = (w) => {
    w.sockets[w.sockets.length - 1].readyState = 3;
    vm.runInContext('_genAgentConnect(sess);', w.ctx);
    w.sockets[w.sockets.length - 1].open();
    return w.sockets[w.sockets.length - 1];
  };

  // same size: one frame on the new socket, none from refits afterwards
  {
    const w = connectAndDrop();
    const second = reconnect(w);
    assert.deepStrictEqual(resizes(second), [{ type: 'resize', cols: 84, rows: 43 }]);
    vm.runInContext('_ocFit(sess); _ocFit(sess);', w.ctx);
    assert.strictEqual(resizes(second).length, 1, 'same-size refits on a synced socket are quiet');
  }

  // size changed while down: the reconnect carries the new size, once
  {
    const w = connectAndDrop();
    w.laidOut.cols = 100;
    w.laidOut.rows = 30;
    const second = reconnect(w);
    assert.deepStrictEqual(resizes(second), [{ type: 'resize', cols: 100, rows: 30 }]);
  }

  // stale PTY size behind a reattach: the first frame on every new socket still goes out
  {
    const w = connectAndDrop();
    for (let i = 0; i < 3; i += 1) {
      const next = reconnect(w);
      assert.deepStrictEqual(resizes(next), [{ type: 'resize', cols: 84, rows: 43 }]);
    }
  }
}

console.log('terminal_pty_resize_sync: ok');
