// A chat POST the server answers with an error must not strand the queue: the tab's doSend is no longer live, so a
// later chat_done drains again. A queued send refused because the queue is paused takes its bubbles back, so Resume
// does not add a second user bubble. The real "POST not ok" branch of the submit handler and the real chat_done
// handler are cut out of app.js and run against stubs.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function braceBlock(start) {
  assert(start > 0, 'block found');
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error('block not closed');
}

const postErrorBlock = braceBlock(source.indexOf("if (!postRes.ok) {\n        let detail = '';"));
const chatDoneBlock = braceBlock(source.indexOf("if (msg.type === 'chat_done') {"));
const refusalSource = braceBlock(source.indexOf('function _queueRefusalMessage('));

function world() {
  const toasts = [];
  const bubbles = [];
  const errorHtml = [];
  const sendBtn = { classList: { remove() {} }, setAttribute() {} };
  const ctx = {
    _activeTabId: 'tab-1',
    _isStreaming: true,
    _streamOver: false,
    _chatTaskIds: new Map(),
    _inflightRequests: new Map(),
    _locallyFinishedTasks: new Set(),
    _tabs: [],
    _tabsWithUpdates: new Set(),
    _doSendLive: new Set(['tab-1']),
    requestTabId: 'tab-1',
    queuedSendId: 'q1',
    drained: [],
    idle: 0,
    toasts,
    bubbles,
    errorHtml,
    discards: 0,
    _queuedUnsent: false,
    _queueDrain: (id) => ctx.drained.push(id),
    _queueRearmStop: () => {},
    _queuePostSettled: (_tab, status, code) => status === 0 || (status === 409 && code === 'turn_in_progress'),
    _discardQueuedAttempt: () => {
      ctx.discards++;
      bubbles.length = 0;
    },
    _showConnectivityToast: (m, kind) => toasts.push([m, kind]),
    _setTabWorking: () => {},
    _flushSandboxFollowUp: () => {},
    setStatus: (s) => {
      if (s === 'idle') ctx.idle++;
    },
    setTimeout: () => {},
    document: { getElementById: () => sendBtn, querySelector: () => null },
    escapeHtml: (s) => s,
    doSend: () => {},
    _resetBtn: () => {},
    _detachStop: () => {},
    prose: {
      textContent: 'typing',
      insertAdjacentHTML: (_where, html) => errorHtml.push(html),
      querySelector: () => null,
    },
    msgDiv: { classList: { remove() {} } },
    sendBtn,
  };
  vm.createContext(ctx);
  vm.runInContext(refusalSource, ctx);
  ctx.postError = async (status, code) => {
    ctx.postRes = { ok: false, status, json: async () => ({ error: code }), text: async () => '' };
    await vm.runInContext(`(async function () { ${postErrorBlock} })()`, ctx);
  };
  ctx.chatDone = (msg) => {
    ctx.msg = msg;
    vm.runInContext(`(function () { ${chatDoneBlock} })()`, ctx);
  };
  return ctx;
}

(async () => {
  // Every way the POST can fail ends the tab's doSend, so the next chat_done drains the queue.
  for (const [label, status, code, queued] of [
    ['a plain 500', 500, '', false],
    ['a queued 500', 500, '', true],
    ['a queued 503', 503, '', true],
    ['queue_paused', 409, 'queue_paused', true],
    ['queue_item_gone', 409, 'queue_item_gone', true],
    ['turn_in_progress', 409, 'turn_in_progress', true],
  ]) {
    const w = world();
    if (!queued) w.queuedSendId = null;
    await w.postError(status, code);
    assert.strictEqual(w._doSendLive.has('tab-1'), false, `${label}: doSend is no longer live`);
    w._locallyFinishedTasks.add('old');
    w.chatDone({ type: 'chat_done', context_id: 'tab-1', task_id: 'old' });
    assert.deepStrictEqual(w.drained, ['tab-1'], `${label}: chat_done drains the queue`);
  }

  // A plain error still shows its error bubble; a refused queued send that stays queued does not.
  {
    const w = world();
    w.queuedSendId = null;
    await w.postError(500, '');
    assert.strictEqual(w.errorHtml.length, 1, 'a 500 shows an error bubble');
    assert.strictEqual(w.discards, 0);
  }

  // Queue paused: the attempt's bubbles are rolled back and the reason is a toast, so Resume adds the only user
  // bubble for the message.
  {
    const w = world();
    const attempt = () => w.bubbles.push('user bubble');
    attempt();
    await w.postError(409, 'queue_paused');
    assert.strictEqual(w.discards, 1, 'the attempt is rolled back');
    assert.strictEqual(w.bubbles.length, 0, 'no user bubble is left behind');
    assert.strictEqual(w.errorHtml.length, 0, 'and no error bubble');
    assert.strictEqual(w.toasts.length, 1);
    assert.match(w.toasts[0][0], /queue is paused/);
    assert.strictEqual(w.toasts[0][1], 'warn');
    assert.strictEqual(w._isStreaming, false, 'the composer is released');
    assert.strictEqual(w.queuedSendId, 'q1', 'the message stays queued, keeping its id');
    attempt(); // Resume sends the same message again
    assert.strictEqual(w.bubbles.length, 1, 'after Resume the message has exactly one user bubble');
  }

  // A message that is gone is not rolled back: the user reads that it was already sent.
  {
    const w = world();
    await w.postError(409, 'queue_item_gone');
    assert.strictEqual(w.discards, 0);
    assert.strictEqual(w.errorHtml.length, 1);
  }

  console.log('queue post error: ok');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
