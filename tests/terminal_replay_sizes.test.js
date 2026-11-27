const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

// A reconnect replays the buffered output together with the sizes the agent drew it at
// ({type:'replay_size'} ... {type:'replay_end'}), so the terminal lays it out as drawn instead of
// at the pane's width. These tests run a real Claude Code transcript through the vendored xterm.

const staticDir = path.join(__dirname, '..', 'web', 'static');
const read = (f) => fs.readFileSync(path.join(staticDir, f), 'utf8');
const transcript = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'fixtures', 'claude_transcript.json'), 'utf8'),
);
const DRAWN = { cols: transcript.cols, rows: transcript.rows };
const PANE = { cols: 100, rows: 30 };

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

const helperCtx = { WebSocket: { OPEN: 1 }, console };
vm.createContext(helperCtx);
vm.runInContext(read('tp-term-helpers.js'), helperCtx);
const { _ocReplaySize, _ocReplayEnd, _ocFit } = vm.runInContext(
  '({ _ocReplaySize, _ocReplayEnd, _ocFit })',
  helperCtx,
);

const flush = (term) => new Promise((resolve) => term.write('', resolve));
const newTerm = (size) =>
  new Terminal({ cols: size.cols, rows: size.rows, scrollback: 5000, allowProposedApi: true });

function screenText(term) {
  const buf = term.buffer.active;
  const lines = [];
  for (let i = 0; i < buf.length; i++) lines.push(buf.getLine(i).translateToString(true));
  return lines.join('\n');
}

function fakeSession(term, proposed = PANE) {
  const sent = [];
  const ws = { readyState: 1, send: (s) => sent.push(JSON.parse(s)) };
  const fitCalls = [];
  const sess = {
    term,
    ws,
    fitAddon: {
      proposeDimensions: () => {
        if (proposed instanceof Error) throw proposed;
        return proposed;
      },
      fit: () => fitCalls.push(1),
    },
    container: { offsetParent: {}, clientWidth: 800, clientHeight: 600 },
  };
  return { sess, sent, fitCalls };
}

// What the reconnect sends: the drawn size first, then the buffered output, then the end marker.
async function replayWithSizes(term, sess) {
  _ocReplaySize(sess, DRAWN.cols, DRAWN.rows);
  for (const chunk of transcript.chunks) term.write(chunk);
  _ocReplayEnd(sess);
  await flush(term);
}

(async () => {
  // reference: the transcript drawn at its own size, then the pane resizing around it
  const reference = newTerm(DRAWN);
  for (const chunk of transcript.chunks) reference.write(chunk);
  await flush(reference);
  reference.resize(PANE.cols, PANE.rows);
  await flush(reference);
  const expected = screenText(reference);
  assert(
    expected.includes('Claude Code') && expected.includes('Cerebrating'),
    'the transcript drew',
  );

  // without the sizes, the same bytes laid out at the pane's width come out different
  {
    const term = newTerm(PANE);
    for (const chunk of transcript.chunks) term.write(chunk);
    await flush(term);
    assert.notStrictEqual(screenText(term), expected, 'a pane-width replay is not what was drawn');
  }

  // with the sizes, the replay is what was drawn, and the pane's size comes back without telling the PTY twice
  {
    const term = newTerm(PANE);
    const { sess, sent } = fakeSession(term);
    await replayWithSizes(term, sess);
    assert.strictEqual(screenText(term), expected);
    assert.deepStrictEqual([term.cols, term.rows], [PANE.cols, PANE.rows]);
    assert.strictEqual(sess._replayingSizes, false);
    assert.deepStrictEqual(sent, [{ type: 'resize', cols: PANE.cols, rows: PANE.rows }]);
  }

  // the replay itself never tells the PTY a size: only the end does
  {
    const term = newTerm(PANE);
    const { sess, sent } = fakeSession(term);
    _ocReplaySize(sess, DRAWN.cols, DRAWN.rows);
    await flush(term);
    assert.deepStrictEqual([term.cols, term.rows], [DRAWN.cols, DRAWN.rows]);
    assert.deepStrictEqual(sent, []);
  }

  // a pane resize during the replay is not fitted over the replayed size
  {
    const term = newTerm(PANE);
    const { sess, fitCalls } = fakeSession(term);
    _ocReplaySize(sess, DRAWN.cols, DRAWN.rows);
    _ocFit(sess);
    _ocFit(sess, true);
    assert.strictEqual(fitCalls.length, 0);
    _ocReplayEnd(sess);
    await flush(term);
    _ocFit(sess);
    assert.strictEqual(fitCalls.length, 1, 'fitting works again once the replay ended');
  }

  // a socket that replaced the replaying one is not held back by the old replay
  {
    const term = newTerm(PANE);
    const { sess, fitCalls } = fakeSession(term);
    _ocReplaySize(sess, DRAWN.cols, DRAWN.rows);
    sess.ws = { readyState: 1, send() {} };
    _ocFit(sess);
    assert.strictEqual(fitCalls.length, 1);
  }

  // a pane that cannot be measured at the end gets the size it had before the replay
  {
    const term = newTerm(PANE);
    const { sess } = fakeSession(term, new Error('hidden'));
    await replayWithSizes(term, sess);
    assert.deepStrictEqual([term.cols, term.rows], [PANE.cols, PANE.rows]);
  }

  // sizes that are not sane are ignored
  {
    const term = newTerm(PANE);
    const { sess } = fakeSession(term);
    for (const [c, r] of [
      [1, 10],
      [80, 0],
      ['80', 24],
      [80.5, 24],
      [null, null],
      [undefined, 24],
    ]) {
      _ocReplaySize(sess, c, r);
    }
    await flush(term);
    assert.deepStrictEqual([term.cols, term.rows], [PANE.cols, PANE.rows]);
    assert(!sess._replayingSizes);
  }

  // a replay_end without any replay_size does nothing
  {
    const term = newTerm(PANE);
    const { sess, sent } = fakeSession(term);
    _ocReplayEnd(sess);
    await flush(term);
    assert.deepStrictEqual(sent, []);
  }

  // the pop-out window: same replay, driven through its real websocket handler
  const popoutSrc = read('terminal-popout.js');
  function popout() {
    const log = [];
    const sockets = [];
    const listeners = {};
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
    }
    FakeWebSocket.OPEN = 1;
    class FakeTerminal {
      constructor() {
        this.cols = PANE.cols;
        this.rows = PANE.rows;
        this.options = {};
        this.queue = [];
      }
      loadAddon(addon) {
        addon.term = this;
      }
      open() {}
      focus() {}
      onData() {}
      reset() {
        log.push(['reset']);
      }
      write(data, cb) {
        this.queue.push([data, cb]);
        if (this.queue.length === 1) queueMicrotask(() => this.drain());
      }
      drain() {
        while (this.queue.length) {
          const [data, cb] = this.queue.shift();
          if (data) log.push(['write', data]);
          if (cb) cb();
        }
      }
      resize(cols, rows) {
        this.cols = cols;
        this.rows = rows;
        log.push(['resize', cols, rows]);
      }
    }
    const fitCalls = [];
    class FakeFitAddon {
      fit() {
        fitCalls.push(1);
        this.term.cols = PANE.cols;
        this.term.rows = PANE.rows;
      }
      proposeDimensions() {
        return { cols: PANE.cols, rows: PANE.rows };
      }
    }
    const el = { textContent: '', style: {} };
    const ctx = {
      URLSearchParams,
      location: { search: '?session_id=s1', protocol: 'http:', host: 'x' },
      document: {
        title: '',
        getElementById: () => el,
        documentElement: { getAttribute: () => 'dark', setAttribute() {} },
        body: { style: {} },
      },
      Terminal: FakeTerminal,
      FitAddon: { FitAddon: FakeFitAddon },
      WebSocket: FakeWebSocket,
      window: { addEventListener: (type, fn) => (listeners[type] = fn) },
      setTimeout: () => 0,
      queueMicrotask,
      encodeURIComponent,
      JSON,
      Number,
      Math,
    };
    vm.createContext(ctx);
    vm.runInContext(popoutSrc, ctx);
    const ws = sockets[0];
    ws.readyState = 1;
    ws.onopen();
    const msg = (m) => ws.onmessage({ data: JSON.stringify(m) });
    return { log, ws, msg, listeners, fitCalls };
  }

  {
    const p = popout();
    p.msg({ type: 'replay_size', cols: 120, rows: 40 });
    p.msg({ type: 'output', data: 'AAA', seq: 3 });
    p.msg({ type: 'replay_size', cols: 90, rows: 20 });
    p.msg({ type: 'output', data: 'BBB', seq: 6 });
    p.msg({ type: 'replay_end' });
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepStrictEqual(p.log, [
      ['resize', 120, 40],
      ['write', 'AAA'],
      ['resize', 90, 20],
      ['write', 'BBB'],
      ['resize', 100, 30],
    ]);
    assert.deepStrictEqual(p.ws.sent, [{ type: 'resize', cols: 100, rows: 30 }]);
  }

  // the pop-out does not refit to the pane while it holds a replayed size
  {
    const p = popout();
    const before = p.fitCalls.length;
    p.msg({ type: 'replay_size', cols: 120, rows: 40 });
    p.listeners.resize();
    assert.strictEqual(p.fitCalls.length, before);
    p.msg({ type: 'replay_end' });
    await new Promise((resolve) => setImmediate(resolve));
    p.listeners.resize();
    assert(p.fitCalls.length > before);
  }

  // a client that predates replay_size and replay_end ignores both: the pop-out's dispatcher
  // has no default branch, so an unknown type falls through untouched
  {
    const p = popout();
    p.msg({ type: 'a_message_from_the_future', cols: 1, rows: 1 });
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepStrictEqual(p.log, []);
    assert.deepStrictEqual(p.ws.sent, [{ type: 'resize', cols: 100, rows: 30 }]);
  }
  const generic = read('tp-generic-agent-terminal.js');
  const chain = generic.slice(generic.indexOf("if (msg.type === 'output')"));
  const known = [...chain.matchAll(/msg\.type === '(\w+)'/g)].map((m) => m[1]);
  assert(known.includes('replay_size') && known.includes('replay_end'));
  const tail = chain.slice(chain.indexOf("msg.type === 'exit'"));
  assert(!/\}\s*else\s*\{/.test(tail.slice(0, 400)), 'no default branch after the last type');

  console.log('terminal_replay_sizes: ok');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
