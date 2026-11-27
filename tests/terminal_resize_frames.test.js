// A resize frame to the PTY makes the agent repaint its whole screen and leave a ghost copy, so a
// frame goes out only when the size really changed. The real functions are cut out of the shipped
// scripts and run against fake terminals.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const staticDir = path.join(__dirname, '..', 'web', 'static');
const read = (name) => fs.readFileSync(path.join(staticDir, name), 'utf8');

function cut(source, pattern, label) {
  const match = source.match(pattern);
  assert(match, `${label} not found`);
  return match[0];
}

function fakeSession({ cols = 100, rows = 30, fitTo, height = 600, width = 900 } = {}) {
  const sent = [];
  const sess = {
    term: { cols, rows },
    fitAddon: {
      fits: 0,
      fit() {
        this.fits += 1;
        if (fitTo) Object.assign(sess.term, fitTo());
      },
    },
    ws: { readyState: 1, send: (m) => sent.push(JSON.parse(m)) },
    container: { offsetParent: {}, clientWidth: width, clientHeight: height },
    _hasOutput: true,
  };
  return { sess, sent };
}

const helperCtx = {
  WebSocket: { OPEN: 1 },
  Date,
  AbortSignal: {},
  _ocNoteEchoCalls: 0,
};
vm.createContext(helperCtx);
vm.runInContext(read('tp-term-helpers.js'), helperCtx);

// the same size is never sent twice; a changed size is
{
  const { sess, sent } = fakeSession();
  assert.strictEqual(helperCtx._ocSendSize(sess), true);
  assert.strictEqual(helperCtx._ocSendSize(sess), false, 'same size, no frame');
  sess.term.cols = 90;
  assert.strictEqual(helperCtx._ocSendSize(sess), true);
  assert.deepStrictEqual(sent, [
    { type: 'resize', cols: 100, rows: 30 },
    { type: 'resize', cols: 90, rows: 30 },
  ]);
}

// a pane squeezed to a few pixels, or hidden, or too narrow is not fitted and sends nothing
{
  for (const squeeze of [{ height: 30 }, { height: 0 }, { width: 20 }]) {
    const { sess, sent } = fakeSession({ fitTo: () => ({ cols: 100, rows: 1 }), ...squeeze });
    helperCtx._ocFit(sess);
    assert.strictEqual(sess.fitAddon.fits, 0, 'a squeezed pane is not fitted');
    assert.deepStrictEqual(sent, []);
  }
  const hidden = fakeSession({ fitTo: () => ({ cols: 100, rows: 1 }) });
  hidden.sess.container.offsetParent = null;
  helperCtx._ocFit(hidden.sess);
  assert.deepStrictEqual(hidden.sent, [], 'a hidden pane sends nothing');
}

// a fit that lands on the size the terminal already has sends nothing
{
  const { sess, sent } = fakeSession({ fitTo: () => ({ cols: 100, rows: 30 }) });
  helperCtx._ocFit(sess);
  assert.deepStrictEqual(sent, []);
}

// a real change sends exactly one frame, and fitting back and forth to a size already sent is quiet
{
  let target = { cols: 80, rows: 30 };
  const { sess, sent } = fakeSession({ fitTo: () => target });
  helperCtx._ocFit(sess);
  helperCtx._ocFit(sess);
  assert.deepStrictEqual(sent, [{ type: 'resize', cols: 80, rows: 30 }]);
  target = { cols: 100, rows: 30 };
  helperCtx._ocFit(sess);
  assert.strictEqual(sent.length, 2);
}

// a reconnect at the size the PTY already has sends nothing; at a new size it sends one frame
{
  const gen = read('tp-generic-agent-terminal.js');
  const block = cut(
    gen,
    /if \(wasRetrying && sess\._retryAttempt\) \{[\s\S]*?\n    \}\n    _ocFit/,
    'reconnect block',
  ).replace(/_ocFit$/, '');
  const run = (sess) => {
    const ctx = { sess, wasRetrying: true, _ocSendSize: helperCtx._ocSendSize };
    vm.createContext(ctx);
    vm.runInContext(block, ctx);
  };
  const { sess, sent } = fakeSession();
  sess._retryAttempt = 1;
  sess._sentSize = { cols: 100, rows: 30 };
  run(sess);
  assert.deepStrictEqual(sent, [], 'reconnect at the same size sends no frame');
  sess.term.cols = 90;
  run(sess);
  assert.deepStrictEqual(sent, [{ type: 'resize', cols: 90, rows: 30 }]);
}

// the dock shell terminal sends only a changed size
{
  const src = cut(read('terminal.js'), /function _fit\(sess\) \{[\s\S]*?\n  \}/, 'dock _fit');
  const { sess, sent } = fakeSession();
  const ctx = { WebSocket: { OPEN: 1 } };
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  ctx._fit(sess);
  ctx._fit(sess);
  ctx._fit(sess);
  assert.deepStrictEqual(sent, [{ type: 'resize', cols: 100, rows: 30 }], 'first frame only');
  sess.term.rows = 20;
  ctx._fit(sess);
  assert.strictEqual(sent.length, 2);
}

// the pop-out window sends only a changed size, and still sends the first one
{
  const src = cut(
    read('terminal-popout.js'),
    /function refit\(\) \{[\s\S]*?\n  \}/,
    'popout refit',
  );
  const sent = [];
  const term = { cols: 100, rows: 30 };
  const ctx = {
    term,
    fit: { fit: () => {} },
    send: (m) => sent.push(JSON.parse(JSON.stringify(m))),
  };
  vm.createContext(ctx);
  vm.runInContext(`let sentSize = null; ${src}`, ctx);
  ctx.refit();
  ctx.refit();
  assert.deepStrictEqual(sent, [{ type: 'resize', cols: 100, rows: 30 }]);
  term.cols = 120;
  ctx.refit();
  assert.strictEqual(sent.length, 2);
}

// the repaint nudges stay: truncated replays and returns from a pop-out still send cols-1, cols
{
  const gen = read('tp-generic-agent-terminal.js');
  assert(/resize\(Math\.max\(cols - 1, 2\)\);\s*resize\(cols\);/.test(gen));
  assert(
    /send\(\{ type: 'resize', cols: Math\.max\(cols - 1, 2\), rows \}\);/.test(
      read('terminal-popout.js'),
    ),
  );
}

console.log('terminal resize frames: ok');
