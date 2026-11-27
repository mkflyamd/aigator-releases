const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

// A real resize makes the agent repaint and leaves a screenful of ghost in scrollback. Once the
// repaint has been quiet for a moment the terminal drops its scrollback, in xterm only.

const staticDir = path.join(__dirname, '..', 'web', 'static');
const read = (f) => fs.readFileSync(path.join(staticDir, f), 'utf8');

function loadXterm() {
  const ctx = { console, setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask };
  ctx.window = ctx;
  ctx.self = ctx;
  ctx.navigator = { userAgent: 'node', platform: 'node', language: 'en' };
  ctx.document = {
    createElement: () => ({
      style: {},
      classList: { add() {}, remove() {} },
      addEventListener() {},
      appendChild() {},
    }),
    addEventListener() {},
  };
  ctx.requestAnimationFrame = (cb) => setTimeout(cb, 0);
  vm.createContext(ctx);
  vm.runInContext(read('vendor/xterm/xterm.js'), ctx);
  return ctx.Terminal;
}
const Terminal = loadXterm();

let timers = [];
let now = 0;
const fakeSetTimeout = (fn, ms) => {
  const t = { at: now + ms, fn, live: true };
  timers.push(t);
  return t;
};
const fakeClearTimeout = (t) => {
  if (t) t.live = false;
};
async function advance(ms) {
  const end = now + ms;
  for (;;) {
    const next = timers.filter((t) => t.live && t.at <= end).sort((a, b) => a.at - b.at)[0];
    if (!next) break;
    next.live = false;
    now = next.at;
    next.fn();
    await flushMicro();
  }
  now = end;
}
const flushMicro = () => new Promise((resolve) => setImmediate(resolve));

const helperCtx = {
  WebSocket: { OPEN: 1 },
  console,
  Date: { now: () => now },
  setTimeout: fakeSetTimeout,
  clearTimeout: fakeClearTimeout,
};
vm.createContext(helperCtx);
vm.runInContext(read('tp-term-helpers.js'), helperCtx);
const { _ocFit } = vm.runInContext('({ _ocFit })', helperCtx);

const flush = (term) => new Promise((resolve) => term.write('', resolve));

function makeSession({ hasOutput = true } = {}) {
  const term = new Terminal({ cols: 100, rows: 30, scrollback: 5000, allowProposedApi: true });
  const trims = [];
  const realWrite = term.write.bind(term);
  term.write = (data, cb) => {
    if (data === '\x1b[3J') trims.push(1);
    return realWrite(data, cb);
  };
  const next = { cols: 100, rows: 30 };
  const sess = {
    term,
    ws: { readyState: 1, send() {} },
    _hasOutput: hasOutput,
    fitAddon: { fit: () => term.resize(next.cols, next.rows) },
    container: { offsetParent: {}, clientWidth: 800, clientHeight: 600 },
  };
  const paint = async (lines) => {
    for (let i = 0; i < lines; i++) term.write(`line ${i}\r\n`);
    await flush(term);
  };
  const resizeTo = (cols, rows) => {
    next.cols = cols;
    next.rows = rows;
    _ocFit(sess);
  };
  return { sess, term, trims, paint, resizeTo };
}

const scrollback = (term) => term.buffer.active.length - term.rows;

(async () => {
  // one trim per settled resize, once the output has been quiet for 300ms
  {
    const { term, trims, paint, resizeTo } = makeSession();
    await paint(200);
    assert(scrollback(term) > 100, 'there is scrollback to drop');
    resizeTo(90, 30);
    await advance(299);
    assert.strictEqual(trims.length, 0, 'not before the quiet period');
    await advance(2);
    await flush(term);
    assert.strictEqual(trims.length, 1);
    assert.strictEqual(scrollback(term), 0, 'scrollback dropped');
    await advance(5000);
    assert.strictEqual(trims.length, 1, 'no second trim for the same resize');
    await paint(200);
    resizeTo(110, 30);
    await advance(400);
    await flush(term);
    assert.strictEqual(trims.length, 2, 'the next real resize trims again');
  }

  // the screen the user is looking at is untouched, and so is the cursor
  {
    const { term, paint, resizeTo } = makeSession();
    await paint(200);
    resizeTo(90, 30);
    const screen = () => {
      const b = term.buffer.active;
      const rows = [];
      for (let i = 0; i < term.rows; i++) rows.push(b.getLine(b.baseY + i).translateToString(true));
      return rows.join('\n') + `|${b.cursorX},${b.cursorY}`;
    };
    const before = screen();
    await advance(1000);
    await flush(term);
    assert.strictEqual(scrollback(term), 0);
    assert.strictEqual(screen(), before);
  }

  // output after the resize pushes the trim back: it waits for the repaint to go quiet
  {
    const { sess, term, trims, paint, resizeTo } = makeSession();
    const { _ocTrimSoon } = vm.runInContext('({ _ocTrimSoon })', helperCtx);
    await paint(200);
    resizeTo(90, 30);
    await advance(200);
    _ocTrimSoon(sess);
    await advance(200);
    assert.strictEqual(trims.length, 0, 'still repainting');
    await advance(150);
    await flush(term);
    assert.strictEqual(trims.length, 1);
  }

  // no trim while the user has scrolled up
  {
    const { term, trims, paint, resizeTo } = makeSession();
    await paint(200);
    // xterm's own scroll step, which its viewport calls when the user scrolls; the viewport needs a DOM
    term._core._bufferService.scrollLines(-10);
    assert(term.buffer.active.viewportY < term.buffer.active.baseY);
    const before = term.buffer.active.length;
    resizeTo(90, 30);
    await advance(1000);
    await flush(term);
    assert.strictEqual(trims.length, 0);
    assert(term.buffer.active.length >= before - 1, 'scrollback kept');
    await advance(5000);
    assert.strictEqual(trims.length, 0, 'not retried later either');
  }

  // no trim on the alternate buffer
  {
    const { term, trims, paint, resizeTo } = makeSession();
    await paint(200);
    term.write('\x1b[?1049h');
    await flush(term);
    assert.strictEqual(term.buffer.active.type, 'alternate');
    resizeTo(90, 30);
    await advance(1000);
    await flush(term);
    assert.strictEqual(trims.length, 0);
    term.write('\x1b[?1049l');
    await flush(term);
    assert(scrollback(term) > 100, 'the normal buffer keeps its scrollback');
  }

  // no trim without a real resize, and none before the session has produced output
  {
    const { trims, paint, resizeTo, term } = makeSession();
    await paint(200);
    resizeTo(100, 30);
    await advance(1000);
    await flush(term);
    assert.strictEqual(trims.length, 0, 'same size is not a resize');
  }
  {
    const { trims, resizeTo, term } = makeSession({ hasOutput: false });
    resizeTo(90, 30);
    await advance(1000);
    await flush(term);
    assert.strictEqual(trims.length, 0, 'nothing to trim before output');
  }

  // nothing is sent to the PTY by the trim
  {
    const sent = [];
    const { sess, term, paint, resizeTo } = makeSession();
    sess.ws.send = (s) => sent.push(JSON.parse(s));
    await paint(200);
    resizeTo(90, 30);
    const afterResize = sent.length;
    await advance(1000);
    await flush(term);
    assert.strictEqual(sent.length, afterResize);
  }

  // a closed session is left alone
  {
    const { sess, term, trims, paint, resizeTo } = makeSession();
    await paint(200);
    resizeTo(90, 30);
    sess._closing = true;
    await advance(1000);
    await flush(term);
    assert.strictEqual(trims.length, 0);
  }

  // output arriving while a trim is armed pushes it back (the websocket handler's hook)
  const generic = read('tp-generic-agent-terminal.js');
  assert(/if \(sess\._trimArmed\) _ocTrimSoon\(sess\);/.test(generic));

  console.log('terminal_scrollback_trim: ok');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
