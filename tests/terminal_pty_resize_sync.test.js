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
    appendChild() {},
    querySelector: () => null,
  });

  const ctx = {
    WebSocket: FakeWebSocket,
    Terminal: FakeTerminal,
    FitAddon: { FitAddon: FakeFitAddon },
    ResizeObserver: class {
      observe() {}
    },
    location: { protocol: 'http:', host: 'localhost' },
    document: { createElement: makeEl, getElementById: () => null },
    requestAnimationFrame: (cb) => cb(),
    setTimeout: () => 0,
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
  return { ctx, sockets, makeEl, laidOut };
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

// 3. An unlaid-out container (hidden pane) must not push a bogus size.
{
  const { ctx, sockets, makeEl } = makeContext();
  const container = makeEl();
  container.offsetParent = null;
  const sess = { tabId: 't', ptySessionId: 'pty-2', agent: 'terminal', container };
  ctx.sess = sess;
  vm.runInContext('_ocSpawnTerm(sess); _genAgentConnect(sess);', ctx);
  sockets[0].open();
  assert.deepStrictEqual(resizes(sockets[0]), [], 'no resize while the container is not laid out');
}

console.log('terminal_pty_resize_sync: ok');
