// Typing while a reply runs queues the message once; the drain never starts two sends for one tab.
// The real _queueComposerMessage and _queueDrain are cut out of app.js and run against stubs.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function functionSource(name) {
  const start = source.indexOf(`async function ${name}(`);
  assert(start > 0, `${name} found`);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`${name} not closed`);
}

function world({ text = 'next question', chatRunning = true } = {}) {
  const calls = [];
  const toasts = [];
  const pending = [];
  const input = {
    textContent: text,
    style: {},
    dataset: {},
    querySelector: () => null,
  };
  const ctx = {
    _activeTabId: 'tab1',
    _slashDropdown: null,
    _mentionDropdown: null,
    _pinDropdown: null,
    _channelDropdown: null,
    _aigatorImages: [],
    _queueComposing: new Set(),
    _queueBusy: new Set(),
    _pendingSandboxFollowUps: new Set(),
    _chatTaskIds: new Map(chatRunning ? [['tab1', 'task1']] : []),
    document: { getElementById: (id) => (id === 'chat-input' ? input : null) },
    window: {},
    crypto: { randomUUID: () => `id${calls.length}` },
    setTimeout: () => 0,
    console,
    _getInputText: () => input.textContent,
    buildFinalMessage: (t) => t,
    _canSubmitMessage: (t) => !!t,
    _showConnectivityToast: (m, kind) => toasts.push([m, kind]),
    _renderAigatorPreviews: () => {},
    _updateSendSlot: () => {},
    _updatePlaceholder: () => {},
    _queueSet: () => {},
    _queueRefresh: () => {},
    _submitQueuedItem: async (item) => calls.push(['submit', item.id]),
    _queueCall: (method, url) => {
      calls.push([method, url]);
      if (method === 'GET') return Promise.resolve({ item: { id: 'a', payload: { text: 'x' } } });
      return new Promise((resolve) => pending.push(() => resolve({ items: [], paused: false })));
    },
  };
  vm.createContext(ctx);
  vm.runInContext(
    `${functionSource('_queueComposerMessage')}\n${functionSource('_queueDrain')}`,
    ctx,
  );
  // Function declarations in a vm script become properties of the context.
  return { ctx, input, calls, toasts, release: () => pending.splice(0).forEach((r) => r()) };
}

(async () => {
  {
    const w = world();
    const first = w.ctx._queueComposerMessage();
    const second = w.ctx._queueComposerMessage();
    w.release();
    await Promise.all([first, second]);
    const posts = w.calls.filter(([m]) => m === 'POST');
    assert.strictEqual(posts.length, 1, 'two Enters before the server answers queue one message');
    assert.strictEqual(w.input.textContent, '', 'the composer is cleared once the message is queued');
  }

  {
    const w = world({ text: '/demo something' });
    await w.ctx._queueComposerMessage();
    assert.strictEqual(w.calls.length, 0, 'a slash command is not queued');
    assert.strictEqual(w.toasts[0][1], 'warn', 'the refusal is a visible warning');
    assert.strictEqual(w.input.textContent, '/demo something', 'the slash command stays in the composer');
  }

  {
    const w = world({ chatRunning: false });
    const first = w.ctx._queueComposerMessage();
    w.release();
    await first;
    assert(
      w.calls.some(([m]) => m === 'GET'),
      'a message queued after the reply already ended is sent right away',
    );
  }

  {
    const w = world({ chatRunning: false });
    w.ctx._queueBusy.add('tab1');
    await w.ctx._queueDrain('tab1');
    assert.strictEqual(w.calls.length, 0, 'a send already in flight blocks a second drain');
  }

  {
    const w = world({ chatRunning: true });
    await w.ctx._queueDrain('tab1');
    assert.strictEqual(w.calls.length, 0, 'nothing is drained while a reply is running');
  }

  {
    const w = world({ chatRunning: false });
    w.ctx._pendingSandboxFollowUps.add('tab1');
    await w.ctx._queueDrain('tab1');
    assert.strictEqual(w.calls.length, 0, 'a pending sandbox follow-up goes first');
  }

  {
    const w = world({ chatRunning: false });
    await w.ctx._queueDrain('tab1');
    const submits = w.calls.filter(([m]) => m === 'submit');
    assert.strictEqual(submits.length, 1, 'an idle tab sends the head of the queue once');
    await w.ctx._queueDrain('tab1');
    assert.strictEqual(
      w.calls.filter(([m]) => m === 'submit').length,
      1,
      'the busy mark holds until the submit settles',
    );
  }

  console.log('queue composer: ok');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
